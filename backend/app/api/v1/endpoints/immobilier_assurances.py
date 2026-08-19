"""Assurances locataires — onglet « Assurances » de la page Suivis
annuels (retour Steven/Phil 2026-07-22).

Le locateur doit revalider la preuve d'assurance habitation de chaque
locataire une fois par année. Kratos fournit :

    GET  /immobilier/assurances/overview
         — tous les locataires avec bail ACTIF (gestion externe exclue)
           + date de dernière confirmation + statut ok/a_reconfirmer/
           jamais.
    POST /immobilier/locataires/{id}/assurance/confirmer
         — confirme AUJOURD'HUI + entrée au journal (historique visible
           dans la fiche locataire).
    DELETE .../assurance/confirmer — retire la confirmation (erreur).
    POST /immobilier/locataires/{id}/assurance/demande
         — courriel MANUEL au locataire pour demander la preuve
           (journalisé).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_immeuble_ids
from app.integrations.email_graph import get_mailer
from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    LocataireCommunication,
    Logement,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier", tags=["immobilier-assurances"])


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé.",
        )


def _statut(confirmee_le: Optional[date], cfg=None) -> str:
    """Statut d'assurance selon la bascule annuelle configurée (défaut :
    re-confirmation à partir du 1er janvier)."""
    if cfg is not None:
        return cfg.statut_assurance(confirmee_le)
    # Repli (fenêtre par défaut) si la config n'est pas chargée.
    if confirmee_le is None:
        return "jamais"
    delta = (date.today() - confirmee_le).days
    return "ok" if delta < 365 else "a_reconfirmer"


class AssuranceRow(BaseModel):
    locataire_id: int
    locataire_nom: str
    locataire_email: Optional[str] = None
    bail_id: int
    immeuble_id: Optional[int] = None
    immeuble_name: Optional[str] = None
    logement_id: Optional[int] = None
    logement_numero: Optional[str] = None
    assurance_confirmee_le: Optional[date] = None
    statut: str  # "ok" | "a_reconfirmer" | "jamais"
    #: Dernière demande de preuve envoyée (Assurances OU
    #: Communications).
    derniere_demande_le: Optional[datetime] = None


class AssuranceOverview(BaseModel):
    rows: List[AssuranceRow] = []
    nb_ok: int = 0
    nb_a_reconfirmer: int = 0
    nb_jamais: int = 0


@router.get("/assurances/overview", response_model=AssuranceOverview)
async def assurances_overview(
    db: DBSession, user: CurrentUser
) -> AssuranceOverview:
    _require_volet(user)
    baux = (
        await db.execute(
            select(Bail).where(Bail.status == BailStatus.ACTIF.value)
        )
    ).scalars().all()

    log_ids = {b.logement_id for b in baux if b.logement_id}
    log_by_id = {}
    if log_ids:
        log_by_id = {
            lg.id: lg
            for lg in (
                await db.execute(
                    select(Logement).where(Logement.id.in_(list(log_ids)))
                )
            ).scalars().all()
        }
    imm_ids = {lg.immeuble_id for lg in log_by_id.values() if lg.immeuble_id}
    imm_by_id = {}
    if imm_ids:
        imm_by_id = {
            im.id: im
            for im in (
                await db.execute(
                    select(Immeuble).where(
                        Immeuble.id.in_(list(imm_ids)),
                        Immeuble.gestion_externe.isnot(True),
                    )
                )
            ).scalars().all()
        }
    loc_ids = {b.locataire_id for b in baux if b.locataire_id}
    loc_by_id = {}
    if loc_ids:
        loc_by_id = {
            lo.id: lo
            for lo in (
                await db.execute(
                    select(Locataire).where(Locataire.id.in_(list(loc_ids)))
                )
            ).scalars().all()
        }

    from app.services.locatif_suivis import get_suivis

    suivis_cfg = await get_suivis()

    # Dernière DEMANDE de preuve par locataire — envoyée depuis l'onglet
    # Assurances OU la page Communications (type demande_assurance).
    from app.models.immobilier import ImmCommunication

    demandes: dict = {}
    if loc_ids:
        for lid, quand in (
            await db.execute(
                select(
                    ImmCommunication.locataire_id,
                    func.max(ImmCommunication.created_at),
                ).where(
                    ImmCommunication.type == "demande_assurance",
                    ImmCommunication.locataire_id.in_(list(loc_ids)),
                    ImmCommunication.statut == "envoye",
                ).group_by(ImmCommunication.locataire_id)
            )
        ).all():
            demandes[lid] = quand

    rows: List[AssuranceRow] = []
    for b in baux:
        lg = log_by_id.get(b.logement_id)
        im = imm_by_id.get(lg.immeuble_id) if lg else None
        lo = loc_by_id.get(b.locataire_id)
        # Gestion externe (immeuble absent du dict) → hors du suivi.
        if lo is None or im is None:
            continue
        # Baux AU MOIS (chambres) : pas d'assurance exigée par défaut —
        # réglable dans Paramètres → Suivis annuels.
        if b.au_mois and not suivis_cfg.assurance_inclut_au_mois:
            continue
        rows.append(
            AssuranceRow(
                locataire_id=lo.id,
                locataire_nom=lo.full_name,
                locataire_email=lo.email,
                bail_id=b.id,
                immeuble_id=im.id,
                immeuble_name=im.name,
                logement_id=lg.id if lg else None,
                logement_numero=lg.numero if lg else None,
                assurance_confirmee_le=lo.assurance_confirmee_le,
                statut=_statut(lo.assurance_confirmee_le, suivis_cfg),
                derniere_demande_le=demandes.get(lo.id),
            )
        )
    # À traiter en premier : jamais confirmées, puis à reconfirmer, OK en bas.
    ordre = {"jamais": 0, "a_reconfirmer": 1, "ok": 2}
    rows.sort(
        key=lambda r: (ordre.get(r.statut, 9), r.immeuble_name or "", r.logement_numero or "")
    )
    return AssuranceOverview(
        rows=rows,
        nb_ok=sum(1 for r in rows if r.statut == "ok"),
        nb_a_reconfirmer=sum(1 for r in rows if r.statut == "a_reconfirmer"),
        nb_jamais=sum(1 for r in rows if r.statut == "jamais"),
    )


class AssuranceConfirmResult(BaseModel):
    locataire_id: int
    assurance_confirmee_le: Optional[date] = None
    statut: str


@router.post(
    "/locataires/{locataire_id}/assurance/confirmer",
    response_model=AssuranceConfirmResult,
)
async def confirmer_assurance(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> AssuranceConfirmResult:
    """Confirme la preuve d'assurance AUJOURD'HUI + journalise (l'entrée
    reste dans l'historique de la fiche même après reconfirmation)."""
    _require_volet(user)
    lo = await db.get(Locataire, locataire_id)
    if lo is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")
    today = date.today()
    lo.assurance_confirmee_le = today
    db.add(
        LocataireCommunication(
            locataire_id=lo.id,
            kind="note",
            contenu=f"Preuve d'assurance vérifiée et confirmée ({today.isoformat()}).",
            auteur=getattr(user, "email", None),
        )
    )
    await db.commit()
    return AssuranceConfirmResult(
        locataire_id=lo.id,
        assurance_confirmee_le=lo.assurance_confirmee_le,
        statut=_statut(lo.assurance_confirmee_le),
    )


@router.delete(
    "/locataires/{locataire_id}/assurance/confirmer",
    response_model=AssuranceConfirmResult,
)
async def retirer_confirmation_assurance(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> AssuranceConfirmResult:
    _require_volet(user)
    lo = await db.get(Locataire, locataire_id)
    if lo is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")
    lo.assurance_confirmee_le = None
    await db.commit()
    return AssuranceConfirmResult(
        locataire_id=lo.id, assurance_confirmee_le=None, statut="jamais"
    )


class AssuranceDemandeResult(BaseModel):
    locataire_id: int
    envoye_a: str


async def _adresse_locataire(db, locataire_id: int) -> str:
    """Adresse du logement du bail actif (pour la variable {adresse})."""
    bail = (
        await db.execute(
            select(Bail).where(
                Bail.locataire_id == locataire_id,
                Bail.status == BailStatus.ACTIF.value,
            )
        )
    ).scalars().first()
    if bail is None or bail.logement_id is None:
        return ""
    lg = await db.get(Logement, bail.logement_id)
    im = await db.get(Immeuble, lg.immeuble_id) if lg else None
    parts = [p for p in [im.address if im else None, lg.numero if lg else None] if p]
    return ", ".join(parts)


async def _demande_gabarit() -> dict:
    """Texte du courriel — GABARIT ÉDITABLE comme les autres lettres
    (Paramètres → Modèles de documents, clé immo.gabarit.demande_assurance).
    Titre = objet du courriel ; fail-safe = texte par défaut."""
    from app.services.automation_state import get_automation_config
    from app.services.tal_forms import GABARITS_DEFAUT

    defaut = GABARITS_DEFAUT["demande_assurance"]
    try:
        cfg = await get_automation_config("immo.gabarit.demande_assurance")
    except Exception:  # noqa: BLE001 — fail-safe
        cfg = None
    if isinstance(cfg, dict) and cfg.get("paragraphes"):
        return {
            "titre": cfg.get("titre") or defaut["titre"],
            "paragraphes": list(cfg["paragraphes"]),
        }
    return defaut


def _mail_demande_html(
    nom: str, titre: str, paragraphes: list[str], variables: dict[str, str]
) -> str:
    from app.services.tal_forms import _rendre_paragraphe

    first = (nom or "").strip().split(" ")[0] or "Bonjour"
    corps = "".join(
        f'<p>{_rendre_paragraphe(str(p), variables)}</p>'
        for p in paragraphes
        if str(p).strip()
    )
    return f"""
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;color:#111">
  <h2 style="margin:0 0 16px 0">{titre}</h2>
  <p>Bonjour {first},</p>
  {corps}
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers
  </p>
</div>
"""


@router.post(
    "/locataires/{locataire_id}/assurance/demande",
    response_model=AssuranceDemandeResult,
)
async def demander_preuve_assurance(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> AssuranceDemandeResult:
    """Courriel MANUEL demandant la preuve d'assurance (rien d'auto)."""
    _require_volet(user)
    lo = await db.get(Locataire, locataire_id)
    if lo is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")
    dest = (lo.email or "").strip()
    if not dest:
        raise HTTPException(
            status_code=400,
            detail="Ce locataire n'a pas de courriel — ajoute-le d'abord.",
        )
    gabarit = await _demande_gabarit()
    variables = {
        "locataire": lo.full_name,
        "locateur": "Horizon Services Immobiliers",
        "adresse": await _adresse_locataire(db, lo.id),
    }
    # MÊME expéditeur que la page Communications (profil par défaut :
    # boîte, nom affiché, reply-to) — retour Phil 2026-07-31.
    from app.api.v1.endpoints.immobilier_communications import (
        expediteur_defaut,
    )

    from_email, from_name, reply_to = await expediteur_defaut()
    sujet_mail = f"{gabarit['titre']} — Horizon Services Immobiliers"
    corps_html = _mail_demande_html(
        lo.full_name,
        gabarit["titre"],
        gabarit["paragraphes"],
        variables,
    )
    mailer = get_mailer()
    try:
        await mailer.send(
            to=[dest],
            subject=sujet_mail,
            html_body=corps_html,
            reply_to=reply_to,
            from_email=from_email,
            from_name=from_name,
        )
    except Exception as exc:  # noqa: BLE001 — réseau/Graph
        log.exception("Demande d'assurance au locataire %s échouée", lo.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Envoi courriel échoué : {exc}",
        )
    db.add(
        LocataireCommunication(
            locataire_id=lo.id,
            kind="courriel",
            contenu=f"Demande de preuve d'assurance envoyée (à {dest}).",
            auteur=getattr(user, "email", None),
        )
    )
    # Trace d'audit UNIFIÉE avec la page Communications : la date de la
    # dernière demande s'affiche dans l'onglet Assurances.
    try:
        import uuid as _uuid

        from app.models.immobilier import ImmCommunication

        db.add(
            ImmCommunication(
                group_id=str(_uuid.uuid4()),
                type="demande_assurance",
                sujet=sujet_mail,
                corps=corps_html,
                locataire_id=lo.id,
                locataire_nom=lo.full_name,
                destinataire_email=dest,
                from_email=from_email,
                from_name=from_name,
                reply_to=reply_to,
                statut="envoye",
                created_by_email=getattr(user, "email", None),
                created_at=datetime.now(timezone.utc),
            )
        )
    except Exception:  # noqa: BLE001 — l'audit ne bloque pas l'envoi
        log.exception("Audit imm_communications échoué")
    await db.commit()
    return AssuranceDemandeResult(locataire_id=lo.id, envoye_a=dest)


# ─── Consentement aux communications électroniques ─────────────────────


class ConsentementRow(BaseModel):
    locataire_id: int
    locataire_nom: str
    locataire_email: Optional[str] = None
    bail_id: Optional[int] = None
    immeuble_id: Optional[int] = None
    immeuble_name: Optional[str] = None
    logement_numero: Optional[str] = None
    document_id: Optional[int] = None
    #: "signe" | "refuse" | "ouvert" | "envoye" | "pret" | "aucun"
    statut: str
    envoye_le: Optional[datetime] = None
    ouvert_le: Optional[datetime] = None
    signe_le: Optional[datetime] = None
    refuse_le: Optional[datetime] = None


class ConsentementOverview(BaseModel):
    rows: List[ConsentementRow] = []
    nb_signe: int = 0
    nb_refuse: int = 0
    nb_en_attente: int = 0
    nb_jamais_envoye: int = 0


@router.get("/consentements/overview", response_model=ConsentementOverview)
async def consentements_overview(
    db: DBSession, user: CurrentUser
) -> ConsentementOverview:
    """Où en est le consentement aux communications électroniques de
    chaque locataire à bail actif.

    Retour Phil 2026-08-19 : le document était bien PRÉPARÉ à la création
    du bail — il dormait dans la section Documents en « brouillon » —
    mais rien ne disait qu'il fallait l'envoyer, ni qui avait consenti.
    « Ça va tomber entre les craques. »

    Le consentement peut aussi être REFUSÉ : c'est un consentement, pas
    une formalité. Le refus est un état à part entière ici, pas une
    absence de réponse.
    """
    _require_volet(user)
    from app.models.immobilier import Bail, BailStatus, ImmDocument, Logement

    baux = (
        await db.execute(
            select(Bail).where(Bail.status == BailStatus.ACTIF.value)
        )
    ).scalars().all()
    if not baux:
        return ConsentementOverview()

    log_by_id = {
        lg.id: lg
        for lg in (
            await db.execute(
                select(Logement).where(
                    Logement.id.in_([b.logement_id for b in baux])
                )
            )
        ).scalars().all()
    }
    imm_by_id = {
        im.id: im
        for im in (
            await db.execute(
                select(Immeuble).where(
                    Immeuble.id.in_(
                        [lg.immeuble_id for lg in log_by_id.values()]
                    ),
                    # La gestion externe ne nous appartient pas.
                    Immeuble.gestion_externe.isnot(True),
                )
            )
        ).scalars().all()
    }
    visible = await visible_immeuble_ids(db, user)
    loc_by_id = {
        lo.id: lo
        for lo in (
            await db.execute(
                select(Locataire).where(
                    Locataire.id.in_([b.locataire_id for b in baux])
                )
            )
        ).scalars().all()
    }
    docs = (
        await db.execute(
            select(ImmDocument).where(
                ImmDocument.type == "consentement_communications",
                ImmDocument.locataire_id.in_(list(loc_by_id.keys())),
            )
        )
    ).scalars().all()
    # Le PLUS RÉCENT par locataire fait foi.
    doc_by_loc: dict = {}
    for d in sorted(docs, key=lambda x: x.id):
        doc_by_loc[d.locataire_id] = d

    rows: List[ConsentementRow] = []
    for b in baux:
        lg = log_by_id.get(b.logement_id)
        im = imm_by_id.get(lg.immeuble_id) if lg else None
        if im is None:
            continue
        if visible is not None and im.id not in visible:
            continue
        lo = loc_by_id.get(b.locataire_id)
        if lo is None:
            continue
        d = doc_by_loc.get(lo.id)
        if d is None:
            statut = "aucun"
        elif d.signed_at is not None:
            statut = "signe"
        elif getattr(d, "refuse_le", None) is not None:
            statut = "refuse"
        elif d.ouvert_le is not None:
            statut = "ouvert"
        elif d.envoye_le is not None:
            statut = "envoye"
        else:
            statut = "pret"
        rows.append(
            ConsentementRow(
                locataire_id=lo.id,
                locataire_nom=lo.full_name,
                locataire_email=lo.email,
                bail_id=b.id,
                immeuble_id=im.id,
                immeuble_name=im.name,
                logement_numero=(lg.numero if lg else None),
                document_id=(d.id if d else None),
                statut=statut,
                envoye_le=(d.envoye_le if d else None),
                ouvert_le=(d.ouvert_le if d else None),
                signe_le=(d.signed_at if d else None),
                refuse_le=(getattr(d, "refuse_le", None) if d else None),
            )
        )
    # Ce qui reste à faire d'abord.
    ordre = {"aucun": 0, "pret": 1, "envoye": 2, "ouvert": 3,
             "refuse": 4, "signe": 5}
    rows.sort(key=lambda r: (ordre.get(r.statut, 9), r.locataire_nom))
    return ConsentementOverview(
        rows=rows,
        nb_signe=sum(1 for r in rows if r.statut == "signe"),
        nb_refuse=sum(1 for r in rows if r.statut == "refuse"),
        nb_en_attente=sum(
            1 for r in rows if r.statut in ("envoye", "ouvert")
        ),
        nb_jamais_envoye=sum(
            1 for r in rows if r.statut in ("aucun", "pret")
        ),
    )
