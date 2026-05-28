"""Endpoints internes pour les Ententes de confidentialité (NDA).

Routes :
    POST   /api/v1/ndas                   — créer un NDA (brouillon)
    GET    /api/v1/ndas?deal_id={id}      — lister les NDAs d'un deal
    GET    /api/v1/ndas/{id}              — détail d'un NDA
    GET    /api/v1/ndas/{id}/pdf          — preview PDF (auth)
    GET    /api/v1/ndas/{id}/signed-pdf   — PDF signé immuable (auth)
    POST   /api/v1/ndas/{id}/send         — envoyer à l'investisseur
    DELETE /api/v1/ndas/{id}              — supprimer (si pas signé)

Le flow Phil :
    1. POST /ndas avec `deal_id`, `investor_name`, `investor_email`.
    2. POST /ndas/{id}/send → email + lien public.

La page publique (signature sans auth) vit dans `public_nda.py`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.nda import NDA, NDAStatus
from app.models.prospection_deal import ProspectionDeal
from app.services.nda_pdf import (
    nda_pdf_filename,
    render_nda_pdf,
    signed_nda_pdf_filename,
)
from app.services.nda_send import NDASendError, send_nda_to_investor

log = logging.getLogger(__name__)


router = APIRouter(prefix="/ndas", tags=["ndas"])


# --------------------------- Schemas ---------------------------


class NDACreate(BaseModel):
    """Payload de création — 2 champs visibles + deal_id."""

    deal_id: int = Field(..., gt=0)
    investor_name: str = Field(..., min_length=1, max_length=255)
    investor_email: EmailStr


class NDARead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deal_id: int
    investor_name: str
    investor_email: str
    status: str
    signature_token: str | None
    signed_name: str | None
    signed_at: datetime | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime | None


# --------------------------- Helpers ---------------------------


async def _load_nda_or_404(db, nda_id: int) -> NDA:
    nda = (
        await db.execute(select(NDA).where(NDA.id == nda_id))
    ).scalar_one_or_none()
    if nda is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "NDA introuvable."
        )
    return nda


async def _ensure_deal(db, deal_id: int) -> ProspectionDeal:
    deal = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal introuvable.")
    return deal


# --------------------------- Endpoints ---------------------------


@router.post(
    "",
    response_model=NDARead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un NDA (brouillon)",
)
async def create_nda(
    payload: NDACreate,
    db: DBSession,
    _: CurrentUser,
) -> NDARead:
    # Try/except large : si la création échoue pour une raison
    # inattendue (DB, contrainte, etc.), on remonte un 500 EXPLICITE
    # avec le message d'erreur, pour que Phil voie le vrai problème
    # côté frontend au lieu d'un "Internal Server Error" générique.
    try:
        await _ensure_deal(db, payload.deal_id)

        nda = NDA(
            deal_id=payload.deal_id,
            investor_name=payload.investor_name.strip()[:255],
            investor_email=str(payload.investor_email),
            status=NDAStatus.BROUILLON.value,
        )
        db.add(nda)
        await db.flush()
        await db.refresh(nda)
        return NDARead.model_validate(nda)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception(
            "Création NDA échouée (deal_id=%s, investor=%s)",
            payload.deal_id,
            payload.investor_email,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Création du NDA échouée : {type(exc).__name__}: {exc}",
        ) from exc


@router.get(
    "",
    response_model=List[NDARead],
    summary="Lister les NDAs d'un deal",
)
async def list_ndas(
    db: DBSession,
    _: CurrentUser,
    deal_id: int = Query(..., gt=0),
) -> List[NDARead]:
    await _ensure_deal(db, deal_id)
    rows = (
        await db.execute(
            select(NDA)
            .where(NDA.deal_id == deal_id)
            .order_by(NDA.id.desc())
        )
    ).scalars().all()
    return [NDARead.model_validate(r) for r in rows]


@router.get(
    "/{nda_id}",
    response_model=NDARead,
    summary="Détail d'un NDA",
)
async def get_nda(
    nda_id: int,
    db: DBSession,
    _: CurrentUser,
) -> NDARead:
    nda = await _load_nda_or_404(db, nda_id)
    return NDARead.model_validate(nda)


@router.delete(
    "/{nda_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un NDA (sauf si signé)",
)
async def delete_nda(
    nda_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    nda = await _load_nda_or_404(db, nda_id)
    if nda.status == NDAStatus.SIGNE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "NDA signé — impossible de supprimer.",
        )
    await db.delete(nda)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{nda_id}/pdf",
    summary="Preview PDF (authentifié)",
)
async def get_nda_pdf(
    nda_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    nda = await _load_nda_or_404(db, nda_id)
    pdf_bytes = await render_nda_pdf(db, nda.id)
    filename = nda_pdf_filename(nda)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get(
    "/{nda_id}/signed-pdf",
    summary="PDF signé immuable (audit) — disponible après signature",
)
async def get_nda_signed_pdf(
    nda_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    """Retourne le PDF *signé* archivé en DB (`signed_pdf_blob`).

    Différent de `/pdf` : ce PDF contient le bloc Récepteur rempli,
    le bandeau emerald « SIGNEE ELECTRONIQUEMENT » avec horodatage,
    IP de signature, et hash SHA-256 — c'est la pièce juridiquement
    valable pour archivage et preuve. Pas re-rendu à chaque appel :
    sert exactement les octets stockés au moment de la signature.

    Renvoie 404 explicite si le NDA n'est pas encore signé (le
    blob n'a pas été généré).
    """
    nda = await _load_nda_or_404(db, nda_id)
    if not nda.signed_pdf_blob:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "PDF signé indisponible — entente pas encore signée.",
        )
    filename = signed_nda_pdf_filename(nda)
    return Response(
        content=bytes(nda.signed_pdf_blob),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.post(
    "/{nda_id}/send",
    response_model=NDARead,
    summary="Envoyer l'entente à l'investisseur par courriel",
)
async def send_nda(
    nda_id: int,
    db: DBSession,
    _: CurrentUser,
) -> NDARead:
    nda = await _load_nda_or_404(db, nda_id)
    if nda.status not in (
        NDAStatus.BROUILLON.value,
        NDAStatus.ENVOYE.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "NDA déjà finalisé — impossible de renvoyer.",
        )
    if not nda.investor_email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Adresse courriel de l'investisseur manquante.",
        )
    try:
        await send_nda_to_investor(db, nda.id)
    except NDASendError as exc:
        # Erreur gérée (mailer absent, PDF rendu KO, Graph KO) :
        # message clair côté frontend.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, str(exc)
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        # Filet de sécurité : toute autre exception non gérée
        # devient un 500 avec message explicite, pour éviter le
        # "Internal Server Error" générique vu par Phil.
        log.exception("Envoi NDA %s échoué (cause inattendue)", nda_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Envoi du NDA échoué : {type(exc).__name__}: {exc}",
        ) from exc
    await db.refresh(nda)
    return NDARead.model_validate(nda)
