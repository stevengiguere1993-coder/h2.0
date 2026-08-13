"""Relevés 31 (Revenu Québec) — page « Renouvellements & Relevés 31 ».

Obligation annuelle du locateur : produire un RL-31 pour chaque logement
OCCUPÉ au 31 décembre et en remettre copie au(x) locataire(s) avant le
dernier jour de FÉVRIER. Kratos ne produit pas le relevé officiel (ça se
fait dans le service en ligne de Revenu Québec) ; il fournit :

    GET   /immobilier/releves31?annee=AAAA   — UNE LIGNE PAR LOCATAIRE
          ayant occupé un logement PENDANT l'année (chevauchement de
          bail, pas la seule photo du 31 déc. : un locataire parti en
          juin doit rester visible — retour Phil 2026-08-13) + données à
          saisir chez RQ, jointe au suivi (statut / numéro / copie PDF).
          Deux locataires successifs dans la même année = deux lignes,
          chacune avec sa période : chacun a légalement droit à SON
          relevé (44 Kennedy, logements 101/105/107). La PRODUCTION
          n'ouvre qu'au 1er décembre de l'année fiscale
          (``SuivisConfig.ouverture_releve31``).
    POST  /immobilier/releves31                        — création MANUELLE
          d'un relevé (année + logement + bail optionnel), pour les cas
          que la détection automatique ne voit pas.
    PATCH /immobilier/releves31/{annee}/{logement_id}?bail_id=…  — statut,
          numéro de relevé, notes (upsert sur la ligne du bail visé).
    POST  /immobilier/releves31/{annee}/{logement_id}/pdf?bail_id=… —
          téléverse la copie du relevé (→ ImmDocument type « releve31 »,
          consultable et envoyable par courriel avec suivi d'ouverture).
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select

from app.api.deps import CurrentUser, DBSession
from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
    Releve31,
)

router = APIRouter(prefix="/immobilier", tags=["immobilier-releves31"])

_STATUTS = {"a_produire", "produit", "remis"}


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé.",
        )


class Releve31Row(BaseModel):
    """UN relevé = UN locataire. La ligne est identifiée par
    (annee, logement_id, bail_id) — deux occupants successifs d'un même
    logement produisent deux lignes, jamais fusionnées."""

    annee: int
    logement_id: int
    logement_numero: Optional[str] = None
    immeuble_id: Optional[int] = None
    immeuble_name: Optional[str] = None
    immeuble_adresse: Optional[str] = None
    bail_id: Optional[int] = None
    locataire_id: Optional[int] = None
    locataire_nom: Optional[str] = None
    locataire_email: Optional[str] = None
    # Assurance locataire : dernière confirmation (> 12 mois = à refaire).
    assurance_confirmee_le: Optional[date] = None
    loyer_31_dec: Optional[float] = None
    # Suivi
    statut: str = "a_produire"
    numero_releve: Optional[str] = None
    notes: Optional[str] = None
    document_id: Optional[int] = None
    #: Période d'occupation retenue DANS l'année (bornée au 1er janv. /
    #: 31 déc.) — un bail qui se termine en juin s'affiche tel quel.
    occupation_debut: Optional[date] = None
    occupation_fin: Optional[date] = None
    #: Nombre d'occupants du logement DANS l'année (≥ 2 = changement de
    #: locataire) — l'UI regroupe alors les lignes l'une sous l'autre.
    nb_occupants_logement: int = 1


class Releve31Overview(BaseModel):
    annee: int
    echeance: date  # dernier jour de février de annee+1
    rows: List[Releve31Row] = []
    nb_a_produire: int = 0
    nb_produits: int = 0
    nb_remis: int = 0
    #: Fenêtre de production : les relevés de ``annee`` ne se créent qu'à
    #: partir de ``ouverture_le`` (1er décembre de ``annee`` par défaut).
    creation_ouverte: bool = True
    ouverture_le: Optional[date] = None


class Releve31Update(BaseModel):
    statut: Optional[str] = Field(default=None, max_length=16)
    numero_releve: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None


class Releve31Create(BaseModel):
    """Création MANUELLE d'un relevé (retour Phil 2026-08-13) : les cas
    que la détection automatique ne voit pas — bail absent de Kratos,
    logement passé hors location, colocataire à part."""

    annee: int = Field(ge=2000, le=2100)
    logement_id: int
    #: Le locataire visé. Sans bail, le relevé est rattaché au logement
    #: seul (une seule ligne « sans bail » possible par année).
    bail_id: Optional[int] = None


def _fin_fevrier(annee: int) -> date:
    """Dernier jour de février de ``annee + 1`` (échéance du RL-31)."""
    an = annee + 1
    bissextile = an % 4 == 0 and (an % 100 != 0 or an % 400 == 0)
    return date(an, 2, 29 if bissextile else 28)


_MOIS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _date_fr(d: date) -> str:
    """« 1er décembre 2026 » — pour les messages d'erreur lisibles."""
    jour = "1er" if d.day == 1 else str(d.day)
    return f"{jour} {_MOIS_FR[d.month - 1]} {d.year}"


async def _garde_fenetre(annee: int) -> None:
    """Refuse de PRODUIRE un relevé avant l'ouverture de sa fenêtre.

    Retour Phil 2026-08-13 : « il devrait avoir un mécanisme m'empêchant
    de les créer avant ». On réutilise la bascule déjà en place
    (``releve31_bascule_mois``, défaut novembre) : les relevés de N
    s'ouvrent le 1er décembre N — décembre, janvier et février pour les
    produire et les remettre avant l'échéance légale."""
    from app.services.locatif_suivis import get_suivis

    cfg = await get_suivis()
    if cfg.releve31_creation_ouverte(annee, date.today()):
        return
    raise HTTPException(
        status_code=422,
        detail=(
            f"Les relevés 31 de {annee} pourront être produits à partir "
            f"du {_date_fr(cfg.ouverture_releve31(annee))} (remise au "
            f"locataire avant la fin février {annee + 1})."
        ),
    )


def _fin_effective(b: Bail, today: date) -> date:
    """Fin RÉELLE de l'occupation d'un bail.

    Un bail AU MOIS actif se reconduit automatiquement : sa ``date_fin``
    peut être dépassée alors que le locataire occupe toujours. On la
    prolonge jusqu'à aujourd'hui pour ne pas le faire disparaître des
    années récentes."""
    fin = b.date_fin
    if getattr(b, "au_mois", False) and b.status == BailStatus.ACTIF.value:
        return max(fin, today) if fin else today
    return fin


def _occupants_annee(baux: List[Bail], annee: int, today: date) -> List[Bail]:
    """Baux CHEVAUCHANT l'année d'imposition, du plus ancien au plus
    récent. Le RL-31 vise le locataire qui a occupé le logement pendant
    l'année : un bail qui commence en octobre N-1 et se termine en juin N
    compte pour N-1 ET pour N (retour Phil 2026-08-13)."""
    jan1, dec31 = date(annee, 1, 1), date(annee, 12, 31)
    dedans = [
        b
        for b in baux
        if b.date_debut
        and b.date_debut <= dec31
        and _fin_effective(b, today) >= jan1
    ]
    dedans.sort(key=lambda b: (b.date_debut, b.id or 0))
    return dedans


def _bail_principal(
    baux: List[Bail], annee: int, today: date
) -> Optional[Bail]:
    """Le DERNIER occupant de l'année (celui du 31 décembre en priorité).

    Ne sert plus à choisir QUI a droit au relevé — depuis 2026-08-13
    chaque occupant a le sien, personne n'est masqué. Il reste utile
    pour deux choses : rattacher un suivi HÉRITÉ (ligne créée avant la
    scission, ``bail_id`` vide) au bon locataire, et servir de cible par
    défaut aux appels qui ne précisent pas de bail."""
    occupants = _occupants_annee(baux, annee, today)
    if not occupants:
        return None
    dec31 = date(annee, 12, 31)
    au_31 = [
        b
        for b in occupants
        if b.date_debut <= dec31 <= _fin_effective(b, today)
    ]
    pool = au_31 or occupants
    return max(
        pool,
        key=lambda b: (_fin_effective(b, today), b.date_debut, b.id or 0),
    )


async def _baux_du_logement(db, logement_id: int) -> List[Bail]:
    """Tous les baux retenus (hors « proposé ») d'un logement."""
    return list(
        (
            await db.execute(
                select(Bail).where(
                    Bail.logement_id == logement_id,
                    Bail.status != BailStatus.PROPOSE.value,
                )
            )
        ).scalars().all()
    )


async def _occupations_annee(db, annee: int) -> List[dict]:
    """UNE ENTRÉE PAR OCCUPANT (par bail) ayant occupé un logement
    pendant ``annee`` — chevauchement de période, et non plus la seule
    photo du 31 décembre. Immeubles actifs hors gestion externe (le
    gestionnaire tiers produit ses relevés).

    Un logement avec deux locataires successifs dans l'année produit
    donc DEUX entrées, chacune bornée à sa période : chacun a droit à
    son propre RL-31 (Revenu Québec). Le tri reste immeuble → numéro de
    logement → date de début, pour que les occupants d'un même logement
    s'affichent l'un sous l'autre dans l'ordre chronologique."""
    today = date.today()
    dec31 = date(annee, 12, 31)
    immeubles = {
        im.id: im
        for im in (
            await db.execute(
                select(Immeuble).where(
                    Immeuble.is_active.is_(True),
                    Immeuble.gestion_externe.isnot(True),
                )
            )
        ).scalars().all()
    }
    if not immeubles:
        return []
    logements = {
        lg.id: lg
        for lg in (
            await db.execute(
                select(Logement).where(
                    Logement.immeuble_id.in_(list(immeubles.keys())),
                    Logement.status != LogementStatus.HORS_LOC.value,
                )
            )
        ).scalars().all()
    }
    if not logements:
        return []
    jan1 = date(annee, 1, 1)
    baux = (
        await db.execute(
            select(Bail).where(
                Bail.logement_id.in_(list(logements.keys())),
                Bail.date_debut <= dec31,
                # Chevauchement de l'année (et non « présent au 31 déc ») :
                # bail terminé en cours d'année inclus, plus les baux AU
                # MOIS actifs dont la date_fin est dépassée (reconduction).
                or_(
                    Bail.date_fin >= jan1,
                    and_(
                        Bail.au_mois.is_(True),
                        Bail.status == BailStatus.ACTIF.value,
                    ),
                ),
                Bail.status != BailStatus.PROPOSE.value,
            ).order_by(Bail.date_debut.asc())
        )
    ).scalars().all()
    par_logement: dict[int, List[Bail]] = {}
    for b in baux:
        par_logement.setdefault(b.logement_id, []).append(b)
    loc_ids = {b.locataire_id for b in baux if b.locataire_id}
    locataires = {}
    if loc_ids:
        for lo in (
            await db.execute(
                select(Locataire).where(Locataire.id.in_(list(loc_ids)))
            )
        ).scalars().all():
            locataires[lo.id] = lo

    out: List[dict] = []
    for lg_id, lst in par_logement.items():
        occupants = _occupants_annee(lst, annee, today)
        if not occupants:
            continue
        principal = _bail_principal(lst, annee, today)
        lg = logements[lg_id]
        im = immeubles.get(lg.immeuble_id)
        for o in occupants:
            out.append(
                {
                    "logement": lg,
                    "immeuble": im,
                    "bail": o,
                    "locataire": locataires.get(o.locataire_id),
                    # Période bornée à l'année d'imposition : « 1er janv.
                    # → 31 mai » puis « 1er juin → 31 déc. ».
                    "debut": max(o.date_debut, jan1),
                    "fin": min(_fin_effective(o, today), dec31),
                    # Dernier occupant de l'année : seul lui peut hériter
                    # d'un suivi créé avant la scission par locataire.
                    "principal": principal is not None and o.id == principal.id,
                    "nb_occupants": len(occupants),
                }
            )
    out.sort(
        key=lambda o: (
            o["immeuble"].name if o["immeuble"] else "",
            str(o["logement"].numero or ""),
            o["debut"],
            o["bail"].id or 0,
        )
    )
    return out


@router.get("/releves31", response_model=Releve31Overview)
async def releves31_overview(
    db: DBSession, user: CurrentUser, annee: Optional[int] = None
) -> Releve31Overview:
    _require_volet(user)
    today = date.today()
    # Année fiscale « en cours » : jusqu'au mois de bascule inclus (réglable,
    # défaut février) on travaille encore sur l'année précédente. Après, sur
    # l'année courante (retour Phil 2026-07-28).
    from app.services.locatif_suivis import get_suivis

    suivis_cfg = await get_suivis()
    if annee is None:
        annee = suivis_cfg.annee_releve31_defaut(today)
    occupations = await _occupations_annee(db, annee)

    # Suivis indexés par (logement, bail). Les lignes HÉRITÉES (créées
    # avant la scission par locataire, donc sans bail_id) sont rangées à
    # part et rattachées au dernier occupant de l'année — celui qui
    # portait le relevé unique du logement à l'époque.
    suivis: dict[tuple[int, Optional[int]], Releve31] = {}
    for r in (
        await db.execute(select(Releve31).where(Releve31.annee == annee))
    ).scalars().all():
        suivis[(r.logement_id, r.bail_id)] = r

    # Dès qu'une ligne du logement porte un bail, la ligne « sans bail »
    # n'est plus un vestige de l'époque « un relevé par logement » : elle
    # a été posée à la main, et on la laisse tranquille au lieu de
    # l'accrocher à un occupant qui a déjà la sienne.
    logements_scindes = {
        lg_id for (lg_id, bid) in suivis if bid is not None
    }

    rows: List[Releve31Row] = []
    for o in occupations:
        lg, im, b, lo = (
            o["logement"], o["immeuble"], o["bail"], o["locataire"],
        )
        suivi = suivis.get((lg.id, b.id))
        if (
            suivi is None
            and o["principal"]
            and lg.id not in logements_scindes
        ):
            suivi = suivis.get((lg.id, None))
        rows.append(
            Releve31Row(
                annee=annee,
                logement_id=lg.id,
                occupation_debut=o["debut"],
                occupation_fin=o["fin"],
                nb_occupants_logement=o["nb_occupants"],
                logement_numero=lg.numero,
                immeuble_id=im.id if im else None,
                immeuble_name=im.name if im else None,
                immeuble_adresse=(
                    f"{im.address}, {im.city}" if im and im.city else
                    (im.address if im else None)
                ),
                bail_id=b.id,
                locataire_id=lo.id if lo else None,
                locataire_nom=lo.full_name if lo else None,
                locataire_email=lo.email if lo else None,
                assurance_confirmee_le=(
                    lo.assurance_confirmee_le if lo else None
                ),
                loyer_31_dec=float(b.loyer_mensuel or 0),
                statut=suivi.statut if suivi else "a_produire",
                numero_releve=suivi.numero_releve if suivi else None,
                notes=suivi.notes if suivi else None,
                document_id=suivi.document_id if suivi else None,
            )
        )
    return Releve31Overview(
        annee=annee,
        echeance=_fin_fevrier(annee),
        rows=rows,
        nb_a_produire=sum(1 for r in rows if r.statut == "a_produire"),
        nb_produits=sum(1 for r in rows if r.statut == "produit"),
        nb_remis=sum(1 for r in rows if r.statut == "remis"),
        creation_ouverte=suivis_cfg.releve31_creation_ouverte(annee, today),
        ouverture_le=suivis_cfg.ouverture_releve31(annee),
    )


async def _ligne_existante(
    db, annee: int, logement_id: int, bail_id: Optional[int]
) -> Optional[Releve31]:
    """La ligne de suivi du (annee, logement, bail) visé, si elle existe.

    Repli sur la ligne HÉRITÉE (sans ``bail_id``, créée avant la
    scission par locataire) UNIQUEMENT quand le bail visé est le dernier
    occupant de l'année : c'est lui qui portait le relevé unique du
    logement à l'époque. Sans ce garde-fou, annuler le relevé du sortant
    effacerait celui de l'entrant."""
    lignes = list(
        (
            await db.execute(
                select(Releve31).where(
                    Releve31.annee == annee,
                    Releve31.logement_id == logement_id,
                )
            )
        ).scalars().all()
    )
    obj = next((r for r in lignes if r.bail_id == bail_id), None)
    if obj is not None or bail_id is None:
        return obj
    orpheline = next((r for r in lignes if r.bail_id is None), None)
    if orpheline is None:
        return None
    principal = _bail_principal(
        await _baux_du_logement(db, logement_id), annee, date.today()
    )
    if principal is None or principal.id != bail_id:
        return None
    return orpheline


async def _upsert(
    db, annee: int, logement_id: int, bail_id: Optional[int] = None
) -> Releve31:
    """La ligne de suivi du (annee, logement, bail) visé — créée au
    besoin. ``bail_id`` identifie LE locataire : deux occupants
    successifs d'un logement ont chacun leur ligne."""
    obj = await _ligne_existante(db, annee, logement_id, bail_id)
    if obj is not None and obj.bail_id is None and bail_id is not None:
        # Ligne héritée reprise par son locataire : on la lui rattache
        # au lieu d'en créer une seconde, qui perdrait son numéro de
        # relevé et sa copie PDF.
        bail = await db.get(Bail, bail_id)
        obj.bail_id = bail_id
        obj.locataire_id = bail.locataire_id if bail else None
    if obj is None:
        # CRÉATION seulement : un relevé déjà commencé reste modifiable.
        await _garde_fenetre(annee)
        lg = await db.get(Logement, logement_id)
        if lg is None:
            raise HTTPException(
                status_code=404, detail="Logement introuvable."
            )
        bail = None
        if bail_id is not None:
            bail = await db.get(Bail, bail_id)
            if bail is None or bail.logement_id != logement_id:
                raise HTTPException(
                    status_code=404,
                    detail="Bail introuvable pour ce logement.",
                )
        obj = Releve31(
            annee=annee,
            logement_id=logement_id,
            immeuble_id=lg.immeuble_id,
            bail_id=bail_id,
            locataire_id=bail.locataire_id if bail else None,
        )
        db.add(obj)
        await db.flush()
    return obj


async def _bail_cible(
    db, logement_id: int, annee: int, bail_id: Optional[int]
) -> Optional[Bail]:
    """Le bail (= le locataire) visé par une action de production.

    Explicite quand l'UI passe ``bail_id`` — c'est le cas normal depuis
    qu'une ligne = un locataire. Sans lui, on retombe sur le dernier
    occupant de l'année, pour que les anciens appels (et les liens
    profonds) continuent de viser quelque chose de sensé."""
    if bail_id is not None:
        b = await db.get(Bail, bail_id)
        if b is None or b.logement_id != logement_id:
            raise HTTPException(
                status_code=404, detail="Bail introuvable pour ce logement."
            )
        return b
    return _bail_principal(
        await _baux_du_logement(db, logement_id), annee, date.today()
    )


def _row_suivi(obj: Releve31, logement: Optional[Logement]) -> Releve31Row:
    """Écho minimal d'une ligne de suivi après écriture — l'UI recharge
    la liste complète juste après (statuts, périodes, compteurs)."""
    return Releve31Row(
        annee=obj.annee,
        logement_id=obj.logement_id,
        logement_numero=logement.numero if logement else None,
        bail_id=obj.bail_id,
        locataire_id=obj.locataire_id,
        statut=obj.statut,
        numero_releve=obj.numero_releve,
        notes=obj.notes,
        document_id=obj.document_id,
    )


@router.post(
    "/releves31",
    response_model=Releve31Row,
    status_code=status.HTTP_201_CREATED,
)
async def create_releve31(
    payload: Releve31Create, db: DBSession, user: CurrentUser
) -> Releve31Row:
    """Crée un relevé À LA MAIN (retour Phil 2026-08-13) quand la
    détection automatique ne voit pas le cas — bail absent de Kratos,
    logement passé hors location, colocataire à part. La fenêtre de
    production s'applique comme partout : rien avant le 1er décembre de
    l'année fiscale. Idempotent : re-créer la même ligne la renvoie."""
    _require_volet(user)
    obj = await _upsert(db, payload.annee, payload.logement_id, payload.bail_id)
    await db.commit()
    await db.refresh(obj)
    return _row_suivi(obj, await db.get(Logement, payload.logement_id))


@router.patch(
    "/releves31/{annee}/{logement_id}", response_model=Releve31Row
)
async def update_releve31(
    annee: int,
    logement_id: int,
    payload: Releve31Update,
    db: DBSession,
    user: CurrentUser,
    bail_id: Optional[int] = None,
) -> Releve31Row:
    """``bail_id`` = LE locataire visé (une ligne du tableau). Absent,
    on retombe sur le dernier occupant de l'année."""
    _require_volet(user)
    if payload.statut is not None and payload.statut not in _STATUTS:
        raise HTTPException(status_code=422, detail="Statut invalide.")
    obj = await _upsert(db, annee, logement_id, bail_id)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(obj, k, v)
    # Coller un numéro de relevé = il a été produit chez Revenu Québec.
    if data.get("numero_releve") and obj.statut == "a_produire":
        obj.statut = "produit"
    await db.commit()
    await db.refresh(obj)
    return _row_suivi(obj, await db.get(Logement, logement_id))


@router.delete(
    "/releves31/{annee}/{logement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_releve31(
    annee: int,
    logement_id: int,
    db: DBSession,
    user: CurrentUser,
    bail_id: Optional[int] = None,
) -> None:
    """Annule le suivi d'un relevé 31 : la copie PDF liée est supprimée
    et la ligne redevient « à produire » (retour Phil 2026-07-30 —
    miroir de DELETE /documents/{id}). Ne touche QUE la ligne du
    locataire visé (``bail_id``) : annuler le relevé du sortant laisse
    celui de l'entrant intact."""
    _require_volet(user)
    obj = await _ligne_existante(db, annee, logement_id, bail_id)
    if obj is None:
        return  # déjà « à produire »
    if obj.document_id:
        from app.models.immobilier import ImmDocument

        doc = await db.get(ImmDocument, obj.document_id)
        if doc is not None and doc.signed_at is None:
            await db.delete(doc)
    await db.delete(obj)
    await db.commit()


@router.post(
    "/releves31/{annee}/{logement_id}/pdf", response_model=Releve31Row
)
async def upload_releve31_pdf(
    annee: int,
    logement_id: int,
    db: DBSession,
    user: CurrentUser,
    bail_id: Optional[int] = None,
    file: UploadFile = File(...),
) -> Releve31Row:
    """Téléverse la copie PDF du relevé (émise par Revenu Québec) —
    conservée dans imm_documents (type « releve31 ») : visible dans la
    fiche du locataire/logement et envoyable par courriel avec suivi
    d'ouverture. Statut → « produit » (l'envoi le passera à « remis »).
    Le PDF est rattaché au locataire de la ligne (``bail_id``)."""
    _require_volet(user)
    data = await file.read()
    if not data or not data[:5].startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Le fichier doit être un PDF.")
    if len(data) > 15_000_000:
        raise HTTPException(status_code=400, detail="PDF trop volumineux (max 15 Mo).")

    obj = await _upsert(db, annee, logement_id, bail_id)
    bail = await _bail_cible(db, logement_id, annee, bail_id)

    from app.api.v1.endpoints.immobilier_documents import save_document

    doc = await save_document(
        db,
        bail_id=bail.id if bail else None,
        locataire_id=bail.locataire_id if bail else None,
        immeuble_id=obj.immeuble_id,
        doc_type="releve31",
        titre=f"Relevé 31 — {annee}",
        params={"annee": annee, "logement_id": logement_id},
        pdf=data,
        created_by_email=getattr(user, "email", None),
    )
    # Pièce téléversée (pas générée) + chaîne des versions : re-téléverser
    # remplace LE relevé courant, l'ancien reste dans les Documents
    # (retour Phil 2026-07-27).
    doc.source = "importe"
    doc.filename = (file.filename or f"releve31-{annee}.pdf")[:255]
    doc.remplace_document_id = obj.document_id
    obj.document_id = doc.id
    if bail is not None:
        obj.bail_id = bail.id
        obj.locataire_id = bail.locataire_id
    if obj.statut == "a_produire":
        obj.statut = "produit"
    await db.commit()
    await db.refresh(obj)
    return _row_suivi(obj, await db.get(Logement, logement_id))




def _pdf_copie_releve31(
    annee: int,
    numero: str,
    locataire_nom: str,
    adresse: str,
    logement_numero: str,
    loyer_mensuel,
) -> bytes:
    """Copie d'information du relevé 31, générée automatiquement — le
    NUMÉRO officiel vient de Revenu Québec (collé par le staff). Sert de
    copie remise au locataire ; l'import manuel permet de la remplacer
    par le PDF officiel de RQ (retour Phil 2026-07-31)."""
    import io as _io

    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as _canvas

    buf = _io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=letter)
    _w, h = letter
    x = 25 * mm
    y = h - 30 * mm
    c.setFont("Helvetica-Bold", 18)
    c.drawString(x, y, f"Relevé 31 — {annee}")
    y -= 7 * mm
    c.setFont("Helvetica", 10)
    c.drawString(
        x, y, "Renseignements sur l'occupation d'un logement — copie du locataire"
    )
    y -= 4 * mm
    c.setLineWidth(0.8)
    c.line(x, y, _w - 25 * mm, y)
    y -= 12 * mm

    def ligne(label: str, valeur: str, gras: bool = False) -> None:
        nonlocal y
        c.setFont("Helvetica", 10)
        c.setFillGray(0.35)
        c.drawString(x, y, label)
        c.setFillGray(0.0)
        c.setFont("Helvetica-Bold" if gras else "Helvetica", 12)
        c.drawString(x + 72 * mm, y, valeur)
        y -= 10 * mm

    ligne("Numéro du relevé (RQ)", numero, gras=True)
    ligne("Année d'imposition", str(annee))
    ligne("Locataire (bénéficiaire)", locataire_nom or "—")
    ligne("Adresse du logement", adresse or "—")
    ligne("Logement", str(logement_numero or "—"))
    if loyer_mensuel is not None:
        ligne("Loyer mensuel au 31 déc.", f"{float(loyer_mensuel):,.2f} $".replace(",", " "))
    ligne("Locateur", "Horizon Services Immobiliers")

    y -= 4 * mm
    c.setFont("Helvetica", 9)
    c.setFillGray(0.35)
    for t in (
        "Ce numéro de relevé a été attribué par Revenu Québec lors de la production",
        "du relevé 31. Reportez-le dans votre déclaration de revenus (crédit d'impôt",
        "pour solidarité).",
    ):
        c.drawString(x, y, t)
        y -= 5 * mm
    c.showPage()
    c.save()
    return buf.getvalue()


@router.post(
    "/releves31/{annee}/{logement_id}/generer", response_model=Releve31Row
)
async def generer_releve31_pdf(
    annee: int,
    logement_id: int,
    db: DBSession,
    user: CurrentUser,
    bail_id: Optional[int] = None,
) -> Releve31Row:
    """Génère AUTOMATIQUEMENT la copie PDF du relevé (numéro officiel
    déjà collé) et la classe comme document courant — plus besoin
    d'importer un fichier pour pouvoir l'envoyer au locataire. La copie
    est établie AU NOM du locataire de la ligne (``bail_id``)."""
    _require_volet(user)
    obj = await _upsert(db, annee, logement_id, bail_id)
    if not (obj.numero_releve or "").strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "Colle d'abord le numéro du relevé (émis par Revenu "
                "Québec) — la copie se génère avec."
            ),
        )
    bail = await _bail_cible(db, logement_id, annee, bail_id)
    locataire = (
        await db.get(Locataire, bail.locataire_id) if bail else None
    )
    lg = await db.get(Logement, logement_id)
    im = await db.get(Immeuble, lg.immeuble_id) if lg else None
    adresse = (
        f"{im.address}, {im.city}" if im and im.city else
        (im.address if im else "")
    )
    pdf = _pdf_copie_releve31(
        annee,
        obj.numero_releve.strip(),
        locataire.full_name if locataire else "",
        adresse,
        lg.numero if lg else "",
        float(bail.loyer_mensuel) if bail and bail.loyer_mensuel else None,
    )

    from app.api.v1.endpoints.immobilier_documents import save_document

    doc = await save_document(
        db,
        bail_id=bail.id if bail else None,
        locataire_id=bail.locataire_id if bail else None,
        immeuble_id=obj.immeuble_id,
        doc_type="releve31",
        titre=f"Relevé 31 — {annee}",
        params={"annee": annee, "logement_id": logement_id},
        pdf=pdf,
        created_by_email=getattr(user, "email", None),
    )
    doc.remplace_document_id = obj.document_id
    obj.document_id = doc.id
    if bail is not None:
        obj.bail_id = bail.id
        obj.locataire_id = bail.locataire_id
    if obj.statut == "a_produire":
        obj.statut = "produit"
    await db.commit()
    await db.refresh(obj)
    return _row_suivi(obj, lg)


class Releve31LocataireRow(BaseModel):
    annee: int
    logement_id: int
    logement_numero: Optional[str] = None
    immeuble_name: Optional[str] = None
    #: Le bail auquel le relevé est rattaché (une ligne = un locataire).
    bail_id: Optional[int] = None
    statut: str
    numero_releve: Optional[str] = None
    document_id: Optional[int] = None


@router.get(
    "/locataires/{locataire_id}/releves31",
    response_model=List[Releve31LocataireRow],
)
async def releves31_locataire(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> List[Releve31LocataireRow]:
    """Relevés 31 de CE locataire — section « Relevés 31 » de sa fiche
    (retour Phil 2026-07-31).

    Depuis la scission par locataire (2026-08-13), un relevé porte le
    bail auquel il appartient : on ne montre à ce locataire QUE les
    siens. Les lignes héritées (sans bail) restent visibles via les
    paires (logement, année) couvertes par ses baux — c'était la seule
    façon de les rattacher avant."""
    _require_volet(user)
    from datetime import date as _date

    baux = (
        await db.execute(
            select(Bail).where(Bail.locataire_id == locataire_id)
        )
    ).scalars().all()
    if not baux:
        return []
    paires = set()
    log_ids = set()
    mes_baux = {b.id for b in baux}
    for b in baux:
        if not b.logement_id or not b.date_debut:
            continue
        log_ids.add(b.logement_id)
        fin = b.date_fin or _date.today()
        for annee in range(b.date_debut.year, fin.year + 1):
            paires.add((b.logement_id, annee))
    if not log_ids:
        return []
    rels = (
        await db.execute(
            select(Releve31)
            .where(Releve31.logement_id.in_(list(log_ids)))
            .order_by(Releve31.annee.desc())
        )
    ).scalars().all()
    rels = [
        r
        for r in rels
        if (
            r.bail_id in mes_baux
            # Ligne héritée : rattachée au logement, pas encore au bail.
            or (r.bail_id is None and (r.logement_id, r.annee) in paires)
        )
    ]
    lgs = {
        lg.id: lg
        for lg in (
            await db.execute(
                select(Logement).where(Logement.id.in_(list(log_ids)))
            )
        ).scalars().all()
    }
    imm_ids = {lg.immeuble_id for lg in lgs.values() if lg.immeuble_id}
    imms = {}
    if imm_ids:
        imms = {
            im.id: im
            for im in (
                await db.execute(
                    select(Immeuble).where(Immeuble.id.in_(list(imm_ids)))
                )
            ).scalars().all()
        }
    out: List[Releve31LocataireRow] = []
    for r in rels:
        lg = lgs.get(r.logement_id)
        im = imms.get(lg.immeuble_id) if lg else None
        out.append(
            Releve31LocataireRow(
                annee=r.annee,
                logement_id=r.logement_id,
                logement_numero=lg.numero if lg else None,
                immeuble_name=im.name if im else None,
                bail_id=r.bail_id,
                statut=r.statut,
                numero_releve=r.numero_releve,
                document_id=r.document_id,
            )
        )
    return out
