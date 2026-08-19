"""Page COMMUNICATIONS — Gestion locative (retour Phil 2026-07-27).

    GET  /immobilier/communications/destinataires  → immeubles + locataires
         (immeubles en gestion externe TOUJOURS exclus)
    GET  /immobilier/communications/reglages       → expéditeur par défaut
    PUT  /immobilier/communications/reglages       (manager+)
    POST /immobilier/communications/envoyer        → envoi individualisé
    GET  /immobilier/communications                → audit filtrable

Principe : ce qui PART vers le locataire sans exiger de signature vit
ici — modèles d'avis « courriel » (rappel de paiement, avis d'accès,
demande d'assurance) + message libre. Un envoi de masse produit UN
courriel PAR locataire (jamais d'adresses visibles entre eux), avec ses
propres variables, et chaque courriel laisse une trace : ligne d'audit
``imm_communications`` + entrée Communications sur la fiche du
locataire. Les avis TAL à signature restent dans le flux Documents.

Expéditeur : boîte du tenant M365 (Graph n'envoie pas depuis un domaine
externe). Un gestionnaire contractuel (ex. kyle.gestion@gmail.com) est
géré par ``from_name`` (nom affiché) + ``reply_to`` (les réponses des
locataires vont chez lui). Défauts réglables ici, modifiables à l'envoi.
"""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.integrations.email_graph import get_mailer
from app.models.immobilier import (
    Bail,
    BailStatus,
    FraisLocatif,
    ImmCommunication,
    Immeuble,
    ImmeubleOwnership,
    Locataire,
    LocataireCommunication,
    Logement,
    PaiementLoyer,
)
from app.models.entreprise import Entreprise
from app.services.automation_state import (
    get_automation_config,
    set_automation_config,
)
from app.services.tal_forms import (
    GABARITS_DEFAUT,
    SIGNATURE_NON_REQUISE,
    TalContext,
    render_lettre_courriel,
)

log = logging.getLogger("immobilier.communications")

router = APIRouter(
    prefix="/immobilier/communications", tags=["immobilier-communications"]
)

#: Types envoyables depuis la page : les lettres SANS signature (le
#: relevé 31 reste dans Suivis annuels — demande Phil) + message libre.
TYPES_ENVOYABLES = tuple(GABARITS_DEFAUT.keys()) + ("libre",)

_REGLAGES_KEY = "immo.communications"


async def expediteur_defaut() -> tuple:
    """(from_email, from_name, reply_to) du PROFIL PAR DÉFAUT des
    Communications — réutilisé par la demande de preuve d'assurance
    (retour Phil 2026-07-31 : « faudrait que ça soit pareil à
    Communications »). Repli sur les défauts plats, puis (None, None,
    None) = boîte système."""
    try:
        cfg = await get_automation_config(_REGLAGES_KEY) or {}
    except Exception:  # noqa: BLE001 — fail-safe
        cfg = {}
    profils = cfg.get("profils") or []
    defaut = str(cfg.get("profil_defaut") or "")
    prof = next(
        (p for p in profils if p.get("label") == defaut), None
    )
    if prof:
        return (
            str(prof.get("from_email") or "").strip() or None,
            str(prof.get("from_name") or "").strip() or None,
            str(prof.get("reply_to") or "").strip() or None,
        )
    return (
        str(cfg.get("from_email") or "").strip() or None,
        str(cfg.get("from_name") or "").strip() or None,
        str(cfg.get("reply_to") or "").strip() or None,
    )
_MAX_DESTINATAIRES = 500


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé.",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Destinataires ──────────────────────────────────────────────────────


class DestinataireOut(BaseModel):
    locataire_id: int
    bail_id: int
    nom: str
    email: Optional[str] = None
    logement: Optional[str] = None
    #: Dû du MOIS COURANT (loyer + frais − payé) — alimente le bouton
    #: « Retards du mois » de la page (retour Phil 2026-07-27).
    du_mois: float = 0.0


class ImmeubleDestinatairesOut(BaseModel):
    immeuble_id: int
    immeuble_name: str
    locataires: List[DestinataireOut]


@router.get(
    "/destinataires", response_model=List[ImmeubleDestinatairesOut]
)
async def list_destinataires(
    db: DBSession,
    user: CurrentUser,
) -> List[ImmeubleDestinatairesOut]:
    """Tous les locataires à bail ACTIF, groupés par immeuble — la
    matière du sélecteur « À qui ».

    La GESTION EXTERNE est TOUJOURS exclue (décision Phil 2026-08-19,
    après le retour du 2026-08-13 « comment ça l'immeuble 1-3-5 Elgin y
    apparaît ? Il est gestion externe pourtant ») : c'est le
    gestionnaire tiers qui parle à ses locataires, et nous n'avons de
    toute façon presque aucun de leurs courriels. La case « Inclure les
    immeubles en gestion externe » a été retirée — elle n'ajoutait
    quasiment personne tout en ouvrant la porte à un envoi hors
    mandat."""
    _require_volet(user)
    query = (
        select(Bail, Locataire, Logement, Immeuble)
        .join(Locataire, Locataire.id == Bail.locataire_id)
        .join(Logement, Logement.id == Bail.logement_id)
        .join(Immeuble, Immeuble.id == Logement.immeuble_id)
        .where(
            Bail.status == BailStatus.ACTIF.value,
            Immeuble.is_active.is_(True),
        )
        .order_by(Immeuble.name.asc(), Logement.numero.asc())
    )
    query = query.where(Immeuble.gestion_externe.isnot(True))
    rows = (await db.execute(query)).all()
    mois_courant = _now().date().replace(day=1)
    dus = await _du_du_mois(db, [b.id for b, _l, _lg, _i in rows], mois_courant)
    par_immeuble: Dict[int, ImmeubleDestinatairesOut] = {}
    for bail, loc, lg, imm in rows:
        bloc = par_immeuble.get(imm.id)
        if bloc is None:
            bloc = ImmeubleDestinatairesOut(
                immeuble_id=imm.id, immeuble_name=imm.name, locataires=[]
            )
            par_immeuble[imm.id] = bloc
        bloc.locataires.append(
            DestinataireOut(
                locataire_id=loc.id,
                bail_id=bail.id,
                nom=loc.full_name or f"Locataire {loc.id}",
                email=(loc.email or "").strip() or None,
                logement=lg.numero,
                du_mois=max(
                    0.0,
                    round(
                        float(bail.loyer_mensuel or 0)
                        + dus["frais"].get(bail.id, 0.0)
                        - dus["payes"].get(bail.id, 0.0),
                        2,
                    ),
                ),
            )
        )
    return list(par_immeuble.values())


# ── Réglages d'envoi (expéditeur par défaut) ───────────────────────────


class ProfilEnvoi(BaseModel):
    """Un EXPÉDITEUR approuvé (retour Phil : « si j'ai deux gestionnaires
    différents ») — les non-managers choisissent parmi ces profils, sans
    jamais taper d'adresse libre."""

    label: str = Field(min_length=1, max_length=80)
    from_email: str = ""
    from_name: str = ""
    reply_to: str = ""


class ReglagesEnvoi(BaseModel):
    #: Boîte M365 d'envoi (vide = celle du système, info@…).
    from_email: str = ""
    #: Nom affiché dans « De : » (vide = nom de la compagnie).
    from_name: str = ""
    #: Adresse de RÉPONSE — peut être externe (gmail du gestionnaire).
    reply_to: str = ""
    #: Expéditeurs supplémentaires approuvés (gérés par les managers).
    profils: List[ProfilEnvoi] = []
    #: Label du profil PAR DÉFAUT (retour Phil v4 : « je choisis le par
    #: défaut ») — pré-sélectionné pour tous, l'employé peut en choisir un
    #: autre parmi la liste mais ne peut pas en créer.
    profil_defaut: str = ""


class ExpediteurEffectif(BaseModel):
    """Ce que le locataire verra RÉELLEMENT dans son « De : »."""

    from_email: str = ""
    from_name: str = ""
    #: Là où atterrit une RÉPONSE du locataire. Vide = boîte système.
    reply_to: str = ""


@router.get("/expediteur", response_model=ExpediteurEffectif)
async def get_expediteur_effectif(
    db: DBSession, user: CurrentUser
) -> ExpediteurEffectif:
    """Expéditeur RÉSOLU (profil par défaut appliqué, replis compris).

    Sert l'aperçu affiché avant un envoi CONTEXTUEL — depuis la fiche
    d'un locataire, la page Assurances, un bouton DPA… (retour Phil
    2026-08-19 : « je dis pas nécessairement de me rendre jusqu'à la
    page de communication à chaque fois »). L'aperçu doit montrer ce qui
    partira vraiment : on appelle donc la MÊME fonction que le chemin
    d'envoi, jamais une copie des réglages bruts — sinon l'aperçu
    dériverait de la réalité sans que personne ne le voie.
    """
    _require_volet(user)
    from_email, from_name, reply_to = await expediteur_defaut()
    return ExpediteurEffectif(
        from_email=from_email or "",
        from_name=from_name or "",
        reply_to=reply_to or "",
    )


@router.get("/reglages", response_model=ReglagesEnvoi)
async def get_reglages(db: DBSession, user: CurrentUser) -> ReglagesEnvoi:
    _require_volet(user)
    cfg = await get_automation_config(_REGLAGES_KEY)
    profils = []
    for raw in cfg.get("profils") or []:
        try:
            profils.append(ProfilEnvoi(**raw))
        except Exception:  # noqa: BLE001 — profil corrompu ignoré
            continue
    return ReglagesEnvoi(
        from_email=str(cfg.get("from_email") or ""),
        from_name=str(cfg.get("from_name") or ""),
        reply_to=str(cfg.get("reply_to") or ""),
        profils=profils,
        profil_defaut=str(cfg.get("profil_defaut") or ""),
    )


@router.put("/reglages", response_model=ReglagesEnvoi)
async def put_reglages(
    payload: ReglagesEnvoi, db: DBSession, user: CurrentUser
) -> ReglagesEnvoi:
    _require_volet(user)
    if not user.has_min_role("manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Réservé aux gestionnaires.",
        )
    profils_propres = [
        ProfilEnvoi(
            label=pr.label.strip(),
            from_email=pr.from_email.strip(),
            from_name=pr.from_name.strip(),
            reply_to=pr.reply_to.strip(),
        )
        for pr in payload.profils
        if pr.label.strip()
    ][:10]
    # Le profil par défaut doit exister parmi les profils (sinon ignoré).
    labels = {p.label for p in profils_propres}
    defaut = payload.profil_defaut.strip()
    clean = ReglagesEnvoi(
        from_email=payload.from_email.strip(),
        from_name=payload.from_name.strip(),
        reply_to=payload.reply_to.strip(),
        profils=profils_propres,
        profil_defaut=defaut if defaut in labels else "",
    )
    await set_automation_config(
        db, _REGLAGES_KEY, clean.model_dump(), user_id=user.id
    )
    await db.commit()
    return clean


# ── Envoi ──────────────────────────────────────────────────────────────


class EnvoyerIn(BaseModel):
    #: 'rappel_paiement' | 'avis_acces' | 'demande_assurance' | 'libre'
    type: str
    immeuble_ids: List[int] = []
    locataire_ids: List[int] = []
    #: Message libre : sujet + corps (variables {locataire} {adresse}
    #: {logement} {locateur} remplacées par destinataire).
    sujet: Optional[str] = Field(default=None, max_length=255)
    corps: Optional[str] = None
    #: Rappel de paiement : 1er du mois réclamé (défaut = mois courant).
    mois: Optional[date] = None
    #: Avis d'accès : quand / plage horaire / motif (communs à tous).
    acces_date: Optional[date] = None
    acces_plage: Optional[str] = Field(default=None, max_length=120)
    acces_motif: Optional[str] = Field(default=None, max_length=255)
    #: Expéditeur (défauts = réglages).
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    #: Label d'un PROFIL approuvé des réglages — seule façon pour un
    #: non-manager de choisir un autre expéditeur que le défaut.
    profil: Optional[str] = Field(default=None, max_length=80)

class EnvoyerOut(BaseModel):
    group_id: str
    envoyes: int
    #: Rappel de paiement : locataires sautés car le mois est payé.
    ignores_payes: List[str] = []
    #: Locataires sans adresse courriel (à compléter sur leur fiche).
    sans_email: List[str] = []
    #: Échecs d'envoi (nom — erreur).
    echecs: List[str] = []


async def _resoudre_destinataires(
    db,
    immeuble_ids: List[int],
    locataire_ids: List[int],
) -> List[tuple]:
    """(bail, locataire, logement, immeuble) des baux ACTIFS visés —
    union immeubles ∪ locataires, dédupliquée par locataire.

    Même règle que ``list_destinataires`` : la gestion externe est
    TOUJOURS exclue. Le filtre est appliqué ici AUSSI (et pas seulement
    dans le sélecteur) pour qu'un identifiant forgé dans la requête ne
    puisse pas viser un locataire hors mandat."""
    if not immeuble_ids and not locataire_ids:
        return []
    q = (
        select(Bail, Locataire, Logement, Immeuble)
        .join(Locataire, Locataire.id == Bail.locataire_id)
        .join(Logement, Logement.id == Bail.logement_id)
        .join(Immeuble, Immeuble.id == Logement.immeuble_id)
        .where(Bail.status == BailStatus.ACTIF.value)
        .order_by(Immeuble.name.asc(), Logement.numero.asc())
    )
    q = q.where(Immeuble.gestion_externe.isnot(True))
    rows = (await db.execute(q)).all()
    vus: set[int] = set()
    out: List[tuple] = []
    imm_set = set(immeuble_ids)
    loc_set = set(locataire_ids)
    for bail, loc, lg, imm in rows:
        if imm.id not in imm_set and loc.id not in loc_set:
            continue
        if loc.id in vus:
            continue
        vus.add(loc.id)
        out.append((bail, loc, lg, imm))
    return out


async def _locateurs_par_immeuble(db, imm_ids: List[int]) -> Dict[int, str]:
    """Nom de l'entreprise propriétaire (première ownership) par immeuble."""
    if not imm_ids:
        return {}
    rows = (
        await db.execute(
            select(ImmeubleOwnership.immeuble_id, Entreprise.name)
            .join(Entreprise, Entreprise.id == ImmeubleOwnership.entreprise_id)
            .where(ImmeubleOwnership.immeuble_id.in_(imm_ids))
        )
    ).all()
    out: Dict[int, str] = {}
    for iid, name in rows:
        out.setdefault(int(iid), name)
    return out


async def _du_du_mois(
    db, bail_ids: List[int], mois: date
) -> Dict[str, Dict[int, float]]:
    """Sommes payées et frais du mois par bail — le dû du rappel se
    calcule ensuite loyer + frais − payé (même logique que la page
    Loyers). Sert à personnaliser le montant ET à sauter les payés."""
    if not bail_ids:
        return {"payes": {}, "frais": {}}
    payes: Dict[int, float] = {}
    for bid, total in (
        await db.execute(
            select(PaiementLoyer.bail_id, func.sum(PaiementLoyer.montant))
            .where(
                PaiementLoyer.bail_id.in_(bail_ids),
                PaiementLoyer.mois_couvert == mois,
            )
            .group_by(PaiementLoyer.bail_id)
        )
    ).all():
        payes[int(bid)] = float(total or 0)
    frais: Dict[int, float] = {}
    for bid, total in (
        await db.execute(
            select(FraisLocatif.bail_id, func.sum(FraisLocatif.montant))
            .where(
                FraisLocatif.bail_id.in_(bail_ids),
                FraisLocatif.mois_couvert == mois,
            )
            .group_by(FraisLocatif.bail_id)
        )
    ).all():
        frais[int(bid)] = float(total or 0)
    return {"payes": payes, "frais": frais}  # type: ignore[return-value]


def _corps_html(texte: str) -> str:
    """Texte → HTML minimal (paragraphes), échappé."""
    import html as _html

    paras = [p.strip() for p in texte.split("\n\n") if p.strip()]
    return "".join(
        "<p>" + _html.escape(p).replace("\n", "<br/>") + "</p>"
        for p in paras
    )


def _remplir_libre(texte: str, variables: Dict[str, str]) -> str:
    for k, v in variables.items():
        texte = texte.replace("{" + k + "}", v)
    return texte


@router.post("/envoyer", response_model=EnvoyerOut)
async def envoyer(
    payload: EnvoyerIn, db: DBSession, user: CurrentUser
) -> EnvoyerOut:
    """UN courriel individualisé PAR locataire visé + trace d'audit +
    entrée Communications sur sa fiche. Envoi MANUEL uniquement."""
    _require_volet(user)
    if payload.type not in TYPES_ENVOYABLES:
        raise HTTPException(
            status_code=422,
            detail="Type d'envoi inconnu (avis sans signature ou libre).",
        )
    assert payload.type in SIGNATURE_NON_REQUISE or payload.type == "libre"
    if payload.type == "libre":
        if not (payload.sujet or "").strip() or not (payload.corps or "").strip():
            raise HTTPException(
                status_code=422,
                detail="Message libre : sujet et corps obligatoires.",
            )
    if payload.type == "avis_acces":
        # Le motif et la plage horaire sont EXIGÉS par la loi (art. 1932
        # et 1933 C.c.Q. : l'avis doit préciser le moment et la raison)
        # — un avis sans eux ne vaut rien devant le TAL, et le gabarit
        # écrirait « Motif : — ». Retour Phil 2026-08-19.
        manque = []
        if payload.acces_date is None:
            manque.append("la date")
        if not (payload.acces_plage or "").strip():
            manque.append("la plage horaire")
        if not (payload.acces_motif or "").strip():
            manque.append("le motif")
        if manque:
            liste = (
                manque[0] if len(manque) == 1
                else ", ".join(manque[:-1]) + " et " + manque[-1]
            )
            raise HTTPException(
                status_code=422,
                detail=f"Avis d'accès : indique {liste}.",
            )

    cibles = await _resoudre_destinataires(
        db,
        payload.immeuble_ids,
        payload.locataire_ids,
    )
    if not cibles:
        raise HTTPException(
            status_code=422,
            detail="Choisis au moins un immeuble ou un locataire.",
        )
    if len(cibles) > _MAX_DESTINATAIRES:
        raise HTTPException(
            status_code=422,
            detail=f"Trop de destinataires (max {_MAX_DESTINATAIRES}).",
        )

    mailer = get_mailer()
    if not mailer.ready:
        raise HTTPException(
            status_code=503,
            detail="L'envoi de courriels (Microsoft 365) n'est pas configuré.",
        )

    # Expéditeur : les MANAGERS peuvent ajuster à l'envoi ; les autres
    # (gestionnaire contractuel, employé) sont VERROUILLÉS sur les
    # défauts posés dans les réglages — impossible d'usurper le « De qui »
    # (retour Phil 2026-07-27). Et la section De qui est OBLIGATOIRE :
    # aucun repli silencieux sur la boîte système.
    cfg = await get_automation_config(_REGLAGES_KEY)
    est_manager = bool(user.has_min_role("manager"))
    # Un PROFIL approuvé (des réglages) peut être choisi par tout le
    # monde — c'est la réponse au cas « deux gestionnaires ». À défaut de
    # choix explicite, on prend le profil PAR DÉFAUT des réglages.
    label_voulu = (payload.profil or "").strip() or str(
        cfg.get("profil_defaut") or ""
    ).strip()
    profil_choisi = None
    if label_voulu:
        for raw in cfg.get("profils") or []:
            if str(raw.get("label") or "").strip() == label_voulu:
                profil_choisi = raw
                break
        # Erreur seulement si l'utilisateur a EXPLICITEMENT demandé un
        # profil inconnu (le défaut effacé ne bloque pas l'envoi).
        if profil_choisi is None and (payload.profil or "").strip():
            raise HTTPException(
                status_code=422,
                detail="Expéditeur inconnu — choisis un profil de la liste.",
            )
    if profil_choisi is not None:
        from_email = str(profil_choisi.get("from_email") or "").strip() or None
        from_name = str(profil_choisi.get("from_name") or "").strip() or None
        reply_to = str(profil_choisi.get("reply_to") or "").strip() or None
    elif est_manager:
        from_email = (
            (payload.from_email or "").strip()
            or str(cfg.get("from_email") or "").strip()
            or None
        )
        from_name = (
            (payload.from_name or "").strip()
            or str(cfg.get("from_name") or "").strip()
            or None
        )
        reply_to = (
            (payload.reply_to or "").strip()
            or str(cfg.get("reply_to") or "").strip()
            or None
        )
    else:
        from_email = str(cfg.get("from_email") or "").strip() or None
        from_name = str(cfg.get("from_name") or "").strip() or None
        reply_to = str(cfg.get("reply_to") or "").strip() or None
    if not from_email:
        raise HTTPException(
            status_code=422,
            detail=(
                "La section « De qui » n'est pas remplie : indique "
                "l'adresse d'envoi (boîte Microsoft 365)"
                + (
                    "." if est_manager
                    else " — demande à ton gestionnaire de configurer "
                    "les défauts d'envoi."
                )
            ),
        )

    gabarit = None
    if payload.type in GABARITS_DEFAUT:
        from app.api.v1.endpoints.immobilier_extras import _gabarit_override

        gabarit = await _gabarit_override(payload.type)

    locateurs = await _locateurs_par_immeuble(
        db, list({imm.id for _b, _l, _lg, imm in cibles})
    )

    mois = (payload.mois or _now().date()).replace(day=1)
    dus: Dict[str, Dict[int, float]] = {}
    if payload.type == "rappel_paiement":
        dus = await _du_du_mois(db, [b.id for b, _l, _lg, _i in cibles], mois)

    group_id = secrets.token_hex(8)
    envoyes = 0
    ignores_payes: List[str] = []
    sans_email: List[str] = []
    echecs: List[str] = []

    for bail, loc, lg, imm in cibles:
        nom = loc.full_name or f"Locataire {loc.id}"
        email = (loc.email or "").strip()
        montant_du = None
        if payload.type == "rappel_paiement":
            montant_du = round(
                float(bail.loyer_mensuel or 0)
                + dus.get("frais", {}).get(bail.id, 0.0)
                - dus.get("payes", {}).get(bail.id, 0.0),
                2,
            )
            if montant_du <= 0.005:
                ignores_payes.append(nom)
                continue
        if not email:
            sans_email.append(nom)
            continue

        ctx = TalContext(
            locateur_nom=locateurs.get(imm.id),
            locataire_nom=nom,
            locataire_email=email,
            logement_adresse=imm.address,
            logement_numero=lg.numero,
            logement_ville=imm.city,
            bail_date_debut=bail.date_debut,
            bail_date_fin=bail.date_fin,
            bail_loyer_mensuel=(
                float(bail.loyer_mensuel) if bail.loyer_mensuel else None
            ),
            mois_concerne=mois,
            montant_du=montant_du,
            acces_date=payload.acces_date,
            acces_plage=payload.acces_plage,
            acces_motif=payload.acces_motif,
        )
        if payload.type == "libre":
            variables = {
                "locataire": nom,
                "adresse": (
                    f"{imm.address}, {lg.numero}" if lg.numero else imm.address
                ),
                "logement": lg.numero or "",
                # Retour Phil 2026-07-30 : {locateur} = le « De qui »
                # (ex. « Kyle Brown - Gestion locative ») — l'INC reste
                # le repli si aucun nom d'expéditeur n'est configuré.
                "locateur": from_name or locateurs.get(imm.id) or "",
            }
            sujet = _remplir_libre(payload.sujet or "", variables)
            corps = _remplir_libre(payload.corps or "", variables)
        else:
            sujet, corps = render_lettre_courriel(
                payload.type, ctx, gabarit=gabarit
            )

        statut, erreur = "envoye", None
        try:
            await mailer.send(
                to=[email],
                subject=sujet,
                html_body=_corps_html(corps),
                reply_to=reply_to,
                from_email=from_email,
                from_name=from_name,
            )
            envoyes += 1
        except Exception as exc:  # noqa: BLE001 — un échec ne bloque pas le lot
            statut, erreur = "echec", str(exc)[:500]
            echecs.append(f"{nom} — {str(exc)[:120]}")
            log.warning("Envoi communication à %s en échec: %s", email, exc)

        db.add(
            ImmCommunication(
                group_id=group_id,
                type=payload.type,
                sujet=sujet,
                corps=corps,
                locataire_id=loc.id,
                bail_id=bail.id,
                immeuble_id=imm.id,
                locataire_nom=nom,
                immeuble_nom=imm.name,
                destinataire_email=email,
                from_email=from_email,
                from_name=from_name,
                reply_to=reply_to,
                statut=statut,
                erreur=erreur,
                created_by_email=getattr(user, "email", None),
                created_at=_now(),
            )
        )
        if statut == "envoye":
            db.add(
                LocataireCommunication(
                    locataire_id=loc.id,
                    kind="courriel",
                    contenu=f"Courriel envoyé : {sujet} (à {email})",
                    auteur=getattr(user, "email", None),
                )
            )

    await db.commit()
    log.info(
        "Communications %s (%s) : %d envoyés, %d payés ignorés, "
        "%d sans courriel, %d échecs",
        group_id, payload.type, envoyes, len(ignores_payes),
        len(sans_email), len(echecs),
    )
    return EnvoyerOut(
        group_id=group_id,
        envoyes=envoyes,
        ignores_payes=ignores_payes,
        sans_email=sans_email,
        echecs=echecs,
    )


# ── Audit ──────────────────────────────────────────────────────────────


class CommunicationRow(BaseModel):
    id: int
    group_id: str
    type: str
    sujet: str
    corps: str
    locataire_id: Optional[int] = None
    locataire_nom: Optional[str] = None
    immeuble_id: Optional[int] = None
    immeuble_nom: Optional[str] = None
    destinataire_email: str
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    statut: str
    erreur: Optional[str] = None
    created_by_email: Optional[str] = None
    #: Nom du profil Kratos de l'auteur (prénom/nom) — None si son
    #: profil n'a pas de nom ; l'UI retombe alors sur le courriel.
    created_by_nom: Optional[str] = None
    created_at: Optional[datetime] = None
    #: SUIVI du document transmis, quand il y en a un (retour Phil
    #: 2026-08-19 : « il faut absolument que j'aie un suivi quelque
    #: part »). Un courriel simple n'en a pas — on sait qu'il est parti,
    #: pas qu'il a été lu.
    document_id: Optional[int] = None
    #: Horodatage de la PREMIÈRE ouverture du lien par le locataire.
    document_ouvert_le: Optional[datetime] = None
    document_signe_le: Optional[datetime] = None
    document_signe_par: Optional[str] = None
    #: Le document attend-il une signature ? Un document d'information
    #: n'en attend pas — « pas encore signé » y serait un faux reproche.
    document_signature_requise: bool = False


@router.get("", response_model=List[CommunicationRow])
async def list_communications(
    db: DBSession,
    user: CurrentUser,
    immeuble_id: Optional[int] = None,
    locataire_id: Optional[int] = None,
    type: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> List[CommunicationRow]:
    """Audit des envois, du plus récent au plus ancien, filtrable."""
    _require_volet(user)
    query = select(ImmCommunication)
    if immeuble_id is not None:
        query = query.where(ImmCommunication.immeuble_id == immeuble_id)
    if locataire_id is not None:
        query = query.where(ImmCommunication.locataire_id == locataire_id)
    if type:
        query = query.where(ImmCommunication.type == type)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        query = query.where(
            func.lower(ImmCommunication.sujet).like(needle)
            | func.lower(
                func.coalesce(ImmCommunication.locataire_nom, "")
            ).like(needle)
            | func.lower(ImmCommunication.destinataire_email).like(needle)
        )
    rows = (
        await db.execute(
            query.order_by(
                ImmCommunication.created_at.desc(), ImmCommunication.id.desc()
            ).limit(limit)
        )
    ).scalars().all()

    # « Par » : le nom du profil Kratos plutôt que le courriel brut,
    # quand la personne a renseigné prénom/nom.
    from app.models.user import User

    emails = {r.created_by_email for r in rows if r.created_by_email}
    noms: Dict[str, str] = {}
    if emails:
        urows = (
            await db.execute(select(User).where(User.email.in_(emails)))
        ).scalars().all()
        for u in urows:
            if u.first_name or u.last_name:
                noms[u.email] = u.display_name

    # Suivi : ouverture du lien et signature, pour les envois qui
    # portaient un document. Une seule requête pour tout le lot.
    from app.models.immobilier import ImmDocument
    from app.services.tal_forms import SIGNATURE_NON_REQUISE

    doc_ids = {r.document_id for r in rows if r.document_id}
    docs: Dict[int, ImmDocument] = {}
    if doc_ids:
        drows = (
            await db.execute(
                select(ImmDocument).where(ImmDocument.id.in_(doc_ids))
            )
        ).scalars().all()
        docs = {d.id: d for d in drows}

    out: List[CommunicationRow] = []
    for r in rows:
        row = CommunicationRow.model_validate(r, from_attributes=True)
        row.created_by_nom = noms.get(r.created_by_email or "")
        d = docs.get(r.document_id) if r.document_id else None
        if d is not None:
            row.document_ouvert_le = d.ouvert_le
            row.document_signe_le = d.signed_at
            row.document_signe_par = d.signed_by_name
            row.document_signature_requise = (
                d.type not in SIGNATURE_NON_REQUISE
            )
        out.append(row)
    return out
