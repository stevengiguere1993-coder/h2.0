"""Partage contrôlé des codes d'accès (Steven 2026-11-13).

Règles :

- Les gestionnaires (rôle ``manager`` et plus) voient et gèrent tous les
  codes. Un employé ne voit un code QUE par un partage actif — être
  affecté à l'immeuble ne suffit plus.
- Un partage (``CodeAccesPartage``) couvre un code, les codes d'un
  logement (+ ceux de son immeuble) ou tous les codes d'un immeuble, et
  se ferme tout seul : à une date (``jours`` / ``date``), à la fin d'un BT
  (signé, complété, facturé, annulé), à la livraison d'un projet, ou à la
  désactivation du compte. L'état actif est TOUJOURS recalculé à la
  lecture ; le filet horaire ne fait que noter la fermeture et alerter.
- Le code est caché dans les listes ; « Afficher » passe par
  ``afficher_code`` qui journalise la consultation.
- Assigner un BT rattaché à un lieu donne d'office l'accès aux codes du
  lieu à l'assigné jusqu'à la fin du BT (``accorder_pour_bon``), sauf
  ``donner_acces_codes: false``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bon_travail import BonTravail
from app.models.code_acces import CodeAccesConsultation, CodeAccesPartage
from app.models.immobilier import Immeuble, ImmeubleCode, Logement
from app.models.project import Project
from app.models.user import User

log = logging.getLogger(__name__)

MTL = ZoneInfo("America/Montreal")

#: Statuts d'un BT « terminé » : l'accès lié au BT se ferme.
BT_TERMINES = frozenset({"signed", "cancelled", "complete_a_refacturer", "facture"})
#: Statuts d'un projet « terminé ».
PROJET_TERMINES = frozenset({"delivered"})

MODES = ("jours", "date", "bt", "projet")
JOURS_MAX = 365

TYPES_CODE = {
    "porte_unite": "Porte de l'unité",
    "porte_entree": "Porte d'entrée",
    "boite_cles": "Boîte à clés",
    "garage": "Garage",
    "alarme": "Alarme",
    "autre": "Autre",
}


class PartageInvalide(ValueError):
    """Demande de partage refusée (message lisible pour l'utilisateur)."""


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite (tests) relit des datetimes naïfs : on les tient pour UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fin_de_journee(jour: date) -> datetime:
    """23 h 59 min 59 s, heure de Montréal, du jour donné (en UTC)."""
    return datetime.combine(jour, time(23, 59, 59), tzinfo=MTL).astimezone(
        timezone.utc
    )


def fin_pour_jours(jours: int, *, now: Optional[datetime] = None) -> datetime:
    """1 jour = jusqu'à ce soir ; N jours = jusqu'au soir du N-ième jour."""
    now = now or maintenant()
    aujourd_hui = now.astimezone(MTL).date()
    return fin_de_journee(aujourd_hui + timedelta(days=max(1, jours) - 1))


def peut_gerer(user: Optional[User]) -> bool:
    return bool(user is not None and user.has_min_role("manager"))


# ─── État d'un partage ─────────────────────────────────────────────────


@dataclass
class EtatPartage:
    partage: CodeAccesPartage
    actif: bool
    #: Raison de la fermeture quand il n'est plus actif.
    raison: Optional[str] = None


async def _statuts(
    db: AsyncSession, partages: Iterable[CodeAccesPartage]
) -> tuple[dict[int, str], dict[int, str], dict[int, bool]]:
    ps = list(partages)
    bt_ids = {p.bon_travail_id for p in ps if p.bon_travail_id}
    pj_ids = {p.project_id for p in ps if p.project_id}
    u_ids = {p.user_id for p in ps}
    bts: dict[int, str] = {}
    pjs: dict[int, str] = {}
    users: dict[int, bool] = {}
    if bt_ids:
        for i, st in (
            await db.execute(
                select(BonTravail.id, BonTravail.status).where(
                    BonTravail.id.in_(bt_ids)
                )
            )
        ).all():
            bts[int(i)] = st or ""
    if pj_ids:
        for i, st in (
            await db.execute(
                select(Project.id, Project.status).where(Project.id.in_(pj_ids))
            )
        ).all():
            pjs[int(i)] = st or ""
    if u_ids:
        for i, act in (
            await db.execute(select(User.id, User.is_active).where(User.id.in_(u_ids)))
        ).all():
            users[int(i)] = bool(act)
    return bts, pjs, users


def _evaluer(
    p: CodeAccesPartage,
    bts: dict[int, str],
    pjs: dict[int, str],
    users: dict[int, bool],
    now: datetime,
) -> EtatPartage:
    if p.ferme_le is not None:
        return EtatPartage(p, False, p.ferme_motif or "retire")
    if not users.get(p.user_id, False):
        return EtatPartage(p, False, "compte_desactive")
    fin = _aware(p.fin_le)
    if fin is not None and fin <= now:
        return EtatPartage(p, False, "expire")
    if p.mode == "bt":
        st = bts.get(p.bon_travail_id or -1)
        if st is None or st in BT_TERMINES:
            return EtatPartage(p, False, "fin_bt")
    if p.mode == "projet":
        st = pjs.get(p.project_id or -1)
        if st is None or st in PROJET_TERMINES:
            return EtatPartage(p, False, "fin_projet")
    return EtatPartage(p, True)


async def etats_partages(
    db: AsyncSession,
    *,
    user_id: Optional[int] = None,
    immeuble_id: Optional[int] = None,
    logement_id: Optional[int] = None,
    bon_travail_id: Optional[int] = None,
    ouverts_seulement: bool = True,
    limite: int = 500,
) -> list[EtatPartage]:
    """Partages filtrés, chacun avec son état recalculé maintenant."""
    q = select(CodeAccesPartage)
    if ouverts_seulement:
        q = q.where(CodeAccesPartage.ferme_le.is_(None))
    if user_id is not None:
        q = q.where(CodeAccesPartage.user_id == user_id)
    if immeuble_id is not None:
        q = q.where(CodeAccesPartage.immeuble_id == immeuble_id)
    if logement_id is not None:
        # Un partage de tout l'immeuble couvre aussi ce logement.
        q = q.where(
            or_(
                CodeAccesPartage.logement_id == logement_id,
                CodeAccesPartage.logement_id.is_(None),
            )
        )
    if bon_travail_id is not None:
        q = q.where(CodeAccesPartage.bon_travail_id == bon_travail_id)
    q = q.order_by(CodeAccesPartage.created_at.desc(), CodeAccesPartage.id.desc())
    rows = list((await db.execute(q.limit(limite))).scalars().all())
    bts, pjs, users = await _statuts(db, rows)
    now = maintenant()
    return [_evaluer(p, bts, pjs, users, now) for p in rows]


async def codes_du_partage(
    db: AsyncSession, p: CodeAccesPartage
) -> list[ImmeubleCode]:
    """Codes couverts par un partage, dans l'ordre d'affichage."""
    q = select(ImmeubleCode)
    if p.code_id is not None:
        q = q.where(ImmeubleCode.id == p.code_id)
    elif p.logement_id is not None:
        q = q.where(
            or_(
                ImmeubleCode.logement_id == p.logement_id,
                (ImmeubleCode.immeuble_id == p.immeuble_id)
                & ImmeubleCode.logement_id.is_(None),
            )
        )
    else:
        q = q.where(ImmeubleCode.immeuble_id == p.immeuble_id)
    q = q.order_by(
        ImmeubleCode.logement_id.is_(None).desc(),
        ImmeubleCode.position.asc(),
        ImmeubleCode.id.asc(),
    )
    return list((await db.execute(q)).scalars().all())


def _couvre(p: CodeAccesPartage, code: ImmeubleCode) -> bool:
    if p.code_id is not None:
        return p.code_id == code.id
    if p.logement_id is not None:
        return code.logement_id == p.logement_id or (
            code.logement_id is None and code.immeuble_id == p.immeuble_id
        )
    return code.immeuble_id == p.immeuble_id


async def partage_actif_pour(
    db: AsyncSession, user: User, code: ImmeubleCode
) -> Optional[CodeAccesPartage]:
    """Le partage actif qui donne à ``user`` l'accès à ``code`` (celui
    qui dure le plus longtemps), ou None."""
    etats = await etats_partages(db, user_id=user.id)
    actifs = [e.partage for e in etats if e.actif and _couvre(e.partage, code)]
    if not actifs:
        return None
    lointain = datetime.max.replace(tzinfo=timezone.utc)
    return max(actifs, key=lambda p: _aware(p.fin_le) or lointain)


async def codes_visibles(
    db: AsyncSession,
    user: User,
    codes: list[ImmeubleCode],
) -> dict[int, Optional[CodeAccesPartage]]:
    """``{code_id: partage}`` des codes que ``user`` peut voir (partage
    None = gestionnaire)."""
    if peut_gerer(user):
        return {c.id: None for c in codes}
    if not codes:
        return {}
    etats = [
        e
        for e in await etats_partages(db, user_id=user.id)
        if e.actif
    ]
    out: dict[int, Optional[CodeAccesPartage]] = {}
    for c in codes:
        for e in etats:
            if _couvre(e.partage, c):
                out[c.id] = e.partage
                break
    return out


async def afficher_code(
    db: AsyncSession, user: User, code: ImmeubleCode
) -> Optional[str]:
    """Valeur du code si ``user`` y a droit (journalisé), sinon None."""
    if peut_gerer(user):
        via, pid = "gestion", None
    else:
        p = await partage_actif_pour(db, user, code)
        if p is None:
            return None
        via, pid = "partage", p.id
    db.add(
        CodeAccesConsultation(
            code_id=code.id,
            user_id=user.id,
            user_email=user.email,
            via=via,
            partage_id=pid,
            created_at=maintenant(),
        )
    )
    await db.flush()
    return code.code


async def peut_voir_emplacement(db: AsyncSession, user: User, code: ImmeubleCode) -> bool:
    if peut_gerer(user):
        return True
    return (await partage_actif_pour(db, user, code)) is not None


# ─── Accorder / retirer ────────────────────────────────────────────────


async def lieu_texte(
    db: AsyncSession, immeuble_id: int, logement_id: Optional[int]
) -> str:
    imm = await db.get(Immeuble, immeuble_id)
    txt = (imm.address or imm.name) if imm is not None else f"Immeuble {immeuble_id}"
    if logement_id is not None:
        lg = await db.get(Logement, logement_id)
        if lg is not None:
            txt = f"{txt}, logement {lg.numero}"
    return txt


def fin_texte(p: CodeAccesPartage, *, bt_ref: Optional[str] = None, projet: Optional[str] = None) -> str:
    if p.mode == "bt":
        return f"jusqu'à la fin du BT {bt_ref or p.bon_travail_id}"
    if p.mode == "projet":
        return f"jusqu'à la fin du projet {projet or p.project_id}"
    fin = _aware(p.fin_le)
    if fin is None:
        return "sans date de fin"
    return "jusqu'au " + fin.astimezone(MTL).strftime("%d/%m/%Y")


async def accorder(
    db: AsyncSession,
    *,
    par: User,
    user_ids: list[int],
    immeuble_id: Optional[int] = None,
    logement_id: Optional[int] = None,
    code_id: Optional[int] = None,
    mode: str,
    jours: Optional[int] = None,
    fin_le: Optional[date] = None,
    bon_travail_id: Optional[int] = None,
    project_id: Optional[int] = None,
    motif: Optional[str] = None,
    notifier: bool = True,
) -> list[CodeAccesPartage]:
    """Crée un partage par employé. Lève ``PartageInvalide`` si la
    demande ne tient pas (lieu, durée, BT / projet terminés…)."""
    if not peut_gerer(par):
        raise PartageInvalide("Seul un gestionnaire peut partager des codes.")
    if mode not in MODES:
        raise PartageInvalide("Durée inconnue (jours, date, bt ou projet).")
    ids = sorted({int(u) for u in user_ids if u})
    if not ids:
        raise PartageInvalide("Choisis au moins un employé.")

    # Lieu : le code, sinon le logement, sinon l'immeuble.
    if code_id is not None:
        code = await db.get(ImmeubleCode, code_id)
        if code is None:
            raise PartageInvalide("Code introuvable.")
        immeuble_id, logement_id = code.immeuble_id, code.logement_id
    elif logement_id is not None:
        lg = await db.get(Logement, logement_id)
        if lg is None:
            raise PartageInvalide("Logement introuvable.")
        immeuble_id = lg.immeuble_id
    if immeuble_id is None or await db.get(Immeuble, immeuble_id) is None:
        raise PartageInvalide("Immeuble introuvable.")

    fin: Optional[datetime] = None
    bt: Optional[BonTravail] = None
    pj: Optional[Project] = None
    if mode == "jours":
        if not jours or jours < 1 or jours > JOURS_MAX:
            raise PartageInvalide(f"Nombre de jours entre 1 et {JOURS_MAX}.")
        fin = fin_pour_jours(int(jours))
    elif mode == "date":
        if fin_le is None:
            raise PartageInvalide("Choisis la date de fin.")
        fin = fin_de_journee(fin_le)
        if fin <= maintenant():
            raise PartageInvalide("La date de fin est déjà passée.")
    elif mode == "bt":
        bt = await db.get(BonTravail, bon_travail_id) if bon_travail_id else None
        if bt is None:
            raise PartageInvalide("Choisis le BT.")
        if (bt.status or "") in BT_TERMINES:
            raise PartageInvalide(f"Le BT {bt.reference} est déjà terminé.")
    elif mode == "projet":
        pj = await db.get(Project, project_id) if project_id else None
        if pj is None:
            raise PartageInvalide("Choisis le projet.")
        if (pj.status or "") in PROJET_TERMINES:
            raise PartageInvalide(f"Le projet {pj.name} est déjà livré.")

    users = (
        await db.execute(select(User).where(User.id.in_(ids)))
    ).scalars().all()
    trouves = {u.id: u for u in users}
    manquants = [i for i in ids if i not in trouves or not trouves[i].is_active]
    if manquants:
        raise PartageInvalide("Employé introuvable ou compte désactivé.")

    now = maintenant()
    crees: list[CodeAccesPartage] = []
    for uid in ids:
        p = CodeAccesPartage(
            user_id=uid,
            immeuble_id=immeuble_id,
            logement_id=logement_id,
            code_id=code_id,
            mode=mode,
            fin_le=fin,
            bon_travail_id=bt.id if bt is not None else None,
            project_id=pj.id if pj is not None else None,
            motif=(motif or "").strip() or None,
            accorde_par_user_id=par.id,
            accorde_par_email=par.email,
        )
        p.created_at = now
        p.updated_at = now
        db.add(p)
        crees.append(p)
    await db.flush()

    if notifier:
        lieu = await lieu_texte(db, immeuble_id, logement_id)
        for p in crees:
            await _notifier_partage(
                db,
                trouves[p.user_id],
                p,
                lieu=lieu,
                par=par,
                bt_ref=bt.reference if bt is not None else None,
                projet=pj.name if pj is not None else None,
            )
    return crees


async def _notifier_partage(
    db: AsyncSession,
    dest: User,
    p: CodeAccesPartage,
    *,
    lieu: str,
    par: User,
    bt_ref: Optional[str],
    projet: Optional[str],
) -> None:
    """Cloche + push, et texto si l'employé a un mobile. Le texto porte un
    LIEN vers l'app, jamais le code (un texto n'est pas sécurisé)."""
    from app.services.notifications import notify

    quand = fin_texte(p, bt_ref=bt_ref, projet=projet)
    titre = f"Codes d'accès : {lieu}"
    corps = f"{par.display_name} t'a donné accès aux codes, {quand}."
    try:
        await notify(
            db,
            user_id=dest.id,
            kind="code_acces_partage",
            title=titre,
            body=corps,
            href="/m/codes",
        )
    except Exception:  # noqa: BLE001
        log.exception("Notification de partage de codes échouée (%s)", p.id)
    tel = (getattr(dest, "phone_e164", None) or "").strip()
    if not tel.startswith("+"):
        return
    try:
        from app.api.v1.endpoints.voice import _twilio_provider
        from app.core.config import settings
        from app.models.voice import PhoneNumber, VoiceSms

        pn = (
            await db.execute(
                select(PhoneNumber)
                .where(PhoneNumber.active.is_(True))
                .order_by(PhoneNumber.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if pn is None:
            return
        lien = settings.frontend_url.rstrip("/") + "/fr/m/codes"
        texte = (
            f"Kratos : accès aux codes de {lieu}, {quand}. "
            f"Ouvre l'app pour les voir : {lien}"
        )
        data = await _twilio_provider().send_sms(
            from_e164=pn.e164, to_e164=tel, body=texte
        )
        db.add(
            VoiceSms(
                phone_number_id=pn.id,
                provider_sid=str(data.get("sid") or ""),
                direction="outbound",
                status=str(data.get("status") or "queued"),
                from_e164=pn.e164,
                to_e164=tel,
                body=texte,
                sent_at=maintenant(),
                caller_kind="employe",
                entity_type="code_acces_partage",
                entity_id=p.id,
            )
        )
        await db.flush()
    except Exception:  # noqa: BLE001 — le texto n'est jamais bloquant
        log.warning("Texto de partage de codes non envoyé (%s)", p.id, exc_info=True)


async def fermer(
    db: AsyncSession,
    p: CodeAccesPartage,
    *,
    motif: str,
    par_email: Optional[str] = None,
) -> None:
    if p.ferme_le is not None:
        return
    p.ferme_le = maintenant()
    p.ferme_motif = motif
    p.ferme_par_email = par_email
    await db.flush()


async def a_des_codes(
    db: AsyncSession, immeuble_id: Optional[int], logement_id: Optional[int]
) -> bool:
    if immeuble_id is None and logement_id is None:
        return False
    conds = []
    if logement_id is not None:
        conds.append(ImmeubleCode.logement_id == logement_id)
    if immeuble_id is not None:
        conds.append(
            (ImmeubleCode.immeuble_id == immeuble_id)
            & ImmeubleCode.logement_id.is_(None)
        )
    r = await db.execute(select(ImmeubleCode.id).where(or_(*conds)).limit(1))
    return r.first() is not None


async def accorder_pour_bon(
    db: AsyncSession,
    bon: BonTravail,
    *,
    par: User,
    precedent_assignee: Optional[int] = None,
    donner: bool = True,
) -> Optional[CodeAccesPartage]:
    """Assignation d'un BT rattaché à un lieu : l'assigné reçoit l'accès
    aux codes du lieu jusqu'à la fin du BT ; l'ancien assigné perd celui
    que ce BT lui avait donné. Best-effort, jamais bloquant."""
    try:
        if precedent_assignee and precedent_assignee != bon.assignee_user_id:
            anciens = await etats_partages(
                db, user_id=precedent_assignee, bon_travail_id=bon.id
            )
            for e in anciens:
                await fermer(db, e.partage, motif="reassigne", par_email=par.email)
        uid = bon.assignee_user_id
        if not donner or not uid or not peut_gerer(par):
            return None
        if (bon.status or "") in BT_TERMINES:
            return None
        logement_id = getattr(bon, "logement_id", None)
        immeuble_id = getattr(bon, "immeuble_id", None)
        if logement_id is not None and immeuble_id is None:
            lg = await db.get(Logement, logement_id)
            immeuble_id = lg.immeuble_id if lg is not None else None
        if immeuble_id is None or not await a_des_codes(db, immeuble_id, logement_id):
            return None
        dest = await db.get(User, uid)
        # Un gestionnaire voit déjà tout : pas de partage inutile.
        if dest is None or not dest.is_active or peut_gerer(dest):
            return None
        deja = [
            e for e in await etats_partages(db, user_id=uid, bon_travail_id=bon.id)
            if e.actif
        ]
        if deja:
            return None
        crees = await accorder(
            db,
            par=par,
            user_ids=[uid],
            immeuble_id=immeuble_id,
            logement_id=logement_id,
            mode="bt",
            bon_travail_id=bon.id,
            motif=f"BT {bon.reference} — {bon.title}",
        )
        return crees[0] if crees else None
    except PartageInvalide:
        return None
    except Exception:  # noqa: BLE001
        log.exception("Accès aux codes pour le BT %s non accordé", getattr(bon, "id", None))
        return None


# ─── Filet horaire ─────────────────────────────────────────────────────


async def filet_partages(db: AsyncSession) -> dict:
    """Note la fermeture des partages arrivés à leur fin et alerte les
    gestionnaires quand un compte désactivé avait reçu des codes (« penser
    à changer le code »), une seule fois par partage."""
    from app.services.notifications import notify_role

    etats = await etats_partages(db, limite=5000)
    fermes = 0
    alertes: dict[int, list[CodeAccesPartage]] = {}
    for e in etats:
        if e.actif:
            continue
        await fermer(db, e.partage, motif=e.raison or "expire")
        fermes += 1
    # Comptes désactivés : tout partage (même fermé depuis) pas encore
    # signalé, des 180 derniers jours.
    depuis = maintenant() - timedelta(days=180)
    rows = (
        await db.execute(
            select(CodeAccesPartage)
            .join(User, User.id == CodeAccesPartage.user_id)
            .where(
                User.is_active.is_(False),
                CodeAccesPartage.alerte_compte_le.is_(None),
                CodeAccesPartage.created_at >= depuis,
            )
        )
    ).scalars().all()
    for p in rows:
        alertes.setdefault(p.user_id, []).append(p)
    for uid, ps in alertes.items():
        u = await db.get(User, uid)
        lieux = []
        for p in ps:
            t = await lieu_texte(db, p.immeuble_id, p.logement_id)
            if t not in lieux:
                lieux.append(t)
        try:
            await notify_role(
                db,
                min_role="manager",
                kind="code_acces_compte_desactive",
                title=(
                    "Codes partagés à un compte désactivé : "
                    + (u.display_name if u is not None else f"#{uid}")
                ),
                body="Penser à changer les codes de : " + " ; ".join(lieux[:10]),
                href=f"/immobilier/immeubles/{ps[0].immeuble_id}",
            )
        except Exception:  # noqa: BLE001
            log.exception("Alerte codes / compte désactivé échouée")
        now = maintenant()
        for p in ps:
            p.alerte_compte_le = now
        await db.flush()
    return {"fermes": fermes, "alertes": len(alertes)}


async def filet_partages_une_session() -> dict:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        out = await filet_partages(db)
        await db.commit()
        return out
