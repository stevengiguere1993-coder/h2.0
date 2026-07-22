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
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
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


def _statut(confirmee_le: Optional[date]) -> str:
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

    rows: List[AssuranceRow] = []
    for b in baux:
        lg = log_by_id.get(b.logement_id)
        im = imm_by_id.get(lg.immeuble_id) if lg else None
        lo = loc_by_id.get(b.locataire_id)
        # Gestion externe (immeuble absent du dict) → hors du suivi.
        if lo is None or im is None:
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
                statut=_statut(lo.assurance_confirmee_le),
            )
        )
    # À traiter en premier : jamais confirmées, puis à reconfirmer.
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
    Horizon Services Immobiliers<br>info@immohorizon.com
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
    mailer = get_mailer()
    try:
        await mailer.send(
            to=[dest],
            subject=f"{gabarit['titre']} — Horizon Services Immobiliers",
            html_body=_mail_demande_html(
                lo.full_name,
                gabarit["titre"],
                gabarit["paragraphes"],
                variables,
            ),
            reply_to=mailer.sender,
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
    await db.commit()
    return AssuranceDemandeResult(locataire_id=lo.id, envoye_a=dest)
