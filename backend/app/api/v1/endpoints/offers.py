"""Endpoints internes pour les Offres d'achat minimalistes.

Routes :
    POST   /api/v1/offers                   — créer une offre (brouillon)
    GET    /api/v1/offers?deal_id={id}      — lister les offres d'un deal
    GET    /api/v1/offers/{id}              — détail d'une offre
    GET    /api/v1/offers/{id}/pdf          — preview PDF (interne, authentifié)
    POST   /api/v1/offers/{id}/send         — envoyer au vendeur
    DELETE /api/v1/offers/{id}              — supprimer (si pas signée)

Le flow Phil :
    1. POST /offers avec les 5 champs visibles (les autres champs
       gardent leur défaut SQL).
    2. POST /offers/{id}/send → email au vendeur avec lien public.

La page publique (signature sans auth) vit dans `public_offer.py`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.offer import DEFAULT_INCLUSIONS, Offer, OfferStatus
from app.models.prospection_deal import ProspectionDeal
from app.services.offer_pdf import render_offer_pdf
from app.services.offer_send import OfferSendError, send_offer_to_seller


router = APIRouter(prefix="/offers", tags=["offers"])


# --------------------------- Schemas ---------------------------


class OfferCreate(BaseModel):
    """Payload de création — `deal_id` obligatoire, le reste optionnel.

    Les 5 champs « visibles » sont validés ici. Les conditions
    booléennes ont un défaut (inspection + financement cochés, vente
    décochée). Tous les autres champs (acompte, inclusions) utilisent
    les défauts SQL du modèle.
    """

    deal_id: int = Field(..., gt=0)
    prix_offert: Optional[float] = Field(default=None, ge=0)
    date_possession: Optional[date] = None
    # Si non fourni, on calcule J+5 côté serveur (voir create_offer).
    date_limite_reponse: Optional[date] = None
    vendeur_email: Optional[EmailStr] = None
    vendeur_nom: Optional[str] = Field(default=None, max_length=255)
    condition_inspection: bool = True
    condition_inspection_delai_jours: int = Field(default=10, ge=1, le=120)
    condition_financement: bool = True
    condition_financement_delai_jours: int = Field(default=21, ge=1, le=120)
    condition_vente: bool = False
    acompte: Optional[float] = Field(default=None, ge=0)


class OfferUpdate(BaseModel):
    """PATCH partiel — uniquement valable tant que le statut est
    `brouillon` (une fois envoyée, l'offre est figée)."""

    prix_offert: Optional[float] = Field(default=None, ge=0)
    date_possession: Optional[date] = None
    date_limite_reponse: Optional[date] = None
    vendeur_email: Optional[EmailStr] = None
    vendeur_nom: Optional[str] = Field(default=None, max_length=255)
    condition_inspection: Optional[bool] = None
    condition_inspection_delai_jours: Optional[int] = Field(default=None, ge=1, le=120)
    condition_financement: Optional[bool] = None
    condition_financement_delai_jours: Optional[int] = Field(default=None, ge=1, le=120)
    condition_vente: Optional[bool] = None
    acompte: Optional[float] = Field(default=None, ge=0)


class OfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deal_id: int
    prix_offert: Optional[float]
    date_possession: Optional[date]
    date_limite_reponse: Optional[date]
    vendeur_email: Optional[str]
    vendeur_nom: Optional[str]
    condition_inspection: bool
    condition_inspection_delai_jours: int
    condition_financement: bool
    condition_financement_delai_jours: int
    condition_vente: bool
    acompte: Optional[float]
    inclusions: Optional[str]
    status: str
    signature_token: Optional[str]
    signed_name: Optional[str]
    signed_at: Optional[datetime]
    sent_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]


# --------------------------- Helpers ---------------------------


async def _load_offer_or_404(db, offer_id: int) -> Offer:
    offer = (
        await db.execute(select(Offer).where(Offer.id == offer_id))
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Offre introuvable."
        )
    return offer


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
    response_model=OfferRead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une offre d'achat (brouillon)",
)
async def create_offer(
    payload: OfferCreate,
    db: DBSession,
    _: CurrentUser,
) -> OfferRead:
    await _ensure_deal(db, payload.deal_id)

    # Date limite par défaut : J+5 si l'utilisateur n'a rien saisi.
    deadline = payload.date_limite_reponse
    if deadline is None:
        deadline = date.today() + timedelta(days=5)

    offer = Offer(
        deal_id=payload.deal_id,
        prix_offert=payload.prix_offert,
        date_possession=payload.date_possession,
        date_limite_reponse=deadline,
        vendeur_email=(
            str(payload.vendeur_email) if payload.vendeur_email else None
        ),
        vendeur_nom=(
            payload.vendeur_nom.strip() if payload.vendeur_nom else None
        ),
        condition_inspection=payload.condition_inspection,
        condition_inspection_delai_jours=payload.condition_inspection_delai_jours,
        condition_financement=payload.condition_financement,
        condition_financement_delai_jours=payload.condition_financement_delai_jours,
        condition_vente=payload.condition_vente,
        acompte=payload.acompte if payload.acompte is not None else 1000,
        inclusions=DEFAULT_INCLUSIONS,
        status=OfferStatus.BROUILLON.value,
    )
    db.add(offer)
    await db.flush()
    await db.refresh(offer)
    return OfferRead.model_validate(offer)


@router.get(
    "",
    response_model=List[OfferRead],
    summary="Lister les offres d'un deal",
)
async def list_offers(
    db: DBSession,
    _: CurrentUser,
    deal_id: int = Query(..., gt=0),
) -> List[OfferRead]:
    await _ensure_deal(db, deal_id)
    rows = (
        await db.execute(
            select(Offer)
            .where(Offer.deal_id == deal_id)
            .order_by(Offer.id.desc())
        )
    ).scalars().all()
    return [OfferRead.model_validate(r) for r in rows]


@router.get(
    "/{offer_id}",
    response_model=OfferRead,
    summary="Détail d'une offre",
)
async def get_offer(
    offer_id: int,
    db: DBSession,
    _: CurrentUser,
) -> OfferRead:
    offer = await _load_offer_or_404(db, offer_id)
    return OfferRead.model_validate(offer)


@router.patch(
    "/{offer_id}",
    response_model=OfferRead,
    summary="Modifier une offre brouillon",
)
async def update_offer(
    offer_id: int,
    payload: OfferUpdate,
    db: DBSession,
    _: CurrentUser,
) -> OfferRead:
    offer = await _load_offer_or_404(db, offer_id)
    if offer.status != OfferStatus.BROUILLON.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Offre déjà envoyée — non modifiable.",
        )
    data = payload.model_dump(exclude_unset=True)
    if "vendeur_email" in data and data["vendeur_email"] is not None:
        data["vendeur_email"] = str(data["vendeur_email"])
    if "vendeur_nom" in data and data["vendeur_nom"]:
        data["vendeur_nom"] = data["vendeur_nom"].strip()
    for key, value in data.items():
        setattr(offer, key, value)
    await db.flush()
    await db.refresh(offer)
    return OfferRead.model_validate(offer)


@router.delete(
    "/{offer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une offre (sauf si signée)",
)
async def delete_offer(
    offer_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    offer = await _load_offer_or_404(db, offer_id)
    if offer.status == OfferStatus.SIGNE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Offre signée — impossible de supprimer.",
        )
    await db.delete(offer)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{offer_id}/pdf",
    summary="Preview PDF (authentifié)",
)
async def get_offer_pdf(
    offer_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    offer = await _load_offer_or_404(db, offer_id)
    pdf_bytes = await render_offer_pdf(db, offer.id)
    filename = f"offre-achat-{offer.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/{offer_id}/send",
    response_model=OfferRead,
    summary="Envoyer l'offre au vendeur par courriel",
)
async def send_offer(
    offer_id: int,
    db: DBSession,
    _: CurrentUser,
) -> OfferRead:
    offer = await _load_offer_or_404(db, offer_id)
    if offer.status not in (OfferStatus.BROUILLON.value, OfferStatus.ENVOYE.value):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Offre déjà finalisée — impossible de renvoyer.",
        )
    if not offer.vendeur_email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Adresse courriel du vendeur manquante.",
        )
    try:
        await send_offer_to_seller(db, offer.id)
    except OfferSendError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, str(exc)
        ) from exc
    await db.refresh(offer)
    return OfferRead.model_validate(offer)
