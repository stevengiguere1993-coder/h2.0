"""Endpoints publics (no auth) pour la signature d'une Offre d'achat.

Flow vendeur :
    GET  /api/v1/public/offers/{token}        -> JSON détails publics
    GET  /api/v1/public/offers/{token}/pdf    -> PDF inline
    POST /api/v1/public/offers/{token}/sign   -> body {signed_name, accept}

Le token est opaque (32 octets URL-safe) et fait office
d'authentification + audit trail (IP + nom + heure capturés).
Si `accept=True` → status=signe. Si `accept=False` → status=refuse.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.models.offer import Offer, OfferStatus
from app.models.prospection_deal import ProspectionDeal
from app.services.offer_pdf import render_offer_pdf


router = APIRouter(prefix="/public/offers", tags=["public-offers"])


# --------------------------- Schemas ---------------------------


class PublicOffer(BaseModel):
    """Vue publique épurée pour la page de signature."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    property_address: Optional[str]
    prix_offert: Optional[float]
    date_possession: Optional[date]
    date_limite_reponse: Optional[date]
    acompte: Optional[float]
    inclusions: Optional[str]
    condition_inspection: bool
    condition_inspection_delai_jours: int
    condition_financement: bool
    condition_financement_delai_jours: int
    condition_vente: bool
    vendeur_nom: Optional[str]
    signed_name: Optional[str]
    signed_at: Optional[datetime]


class SignRequest(BaseModel):
    signed_name: str = Field(..., min_length=2, max_length=255)
    accept: bool


# --------------------------- Helpers ---------------------------


def _client_ip(request: Request) -> Optional[str]:
    raw = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else None)
    )
    if raw:
        return raw.split(",")[0].strip()[:64]
    return None


async def _load_by_token(db: AsyncSession, token: str) -> Offer:
    offer = (
        await db.execute(
            select(Offer).where(Offer.signature_token == token)
        )
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré."
        )
    return offer


async def _load_deal(
    db: AsyncSession, deal_id: int
) -> Optional[ProspectionDeal]:
    return (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()


def _maybe_mark_expired(offer: Offer) -> None:
    """Met le statut à `expire` si la date limite est dépassée et
    qu'aucune réponse n'a encore été enregistrée. Mute l'objet
    in-place — le caller doit flush si besoin."""
    if offer.status != OfferStatus.ENVOYE.value:
        return
    if (
        offer.date_limite_reponse
        and offer.date_limite_reponse < date.today()
    ):
        offer.status = OfferStatus.EXPIRE.value


async def _to_public(
    db: AsyncSession, offer: Offer
) -> PublicOffer:
    deal = await _load_deal(db, offer.deal_id)
    return PublicOffer(
        id=offer.id,
        status=offer.status,
        property_address=deal.address if deal else None,
        prix_offert=(
            float(offer.prix_offert) if offer.prix_offert is not None else None
        ),
        date_possession=offer.date_possession,
        date_limite_reponse=offer.date_limite_reponse,
        acompte=float(offer.acompte) if offer.acompte is not None else None,
        inclusions=offer.inclusions,
        condition_inspection=offer.condition_inspection,
        condition_inspection_delai_jours=offer.condition_inspection_delai_jours,
        condition_financement=offer.condition_financement,
        condition_financement_delai_jours=offer.condition_financement_delai_jours,
        condition_vente=offer.condition_vente,
        vendeur_nom=offer.vendeur_nom,
        signed_name=offer.signed_name,
        signed_at=offer.signed_at,
    )


# --------------------------- Routes ---------------------------


@router.get(
    "/{token}",
    response_model=PublicOffer,
    summary="Détails de l'offre (page publique)",
)
async def read_offer(token: str, db: DBSession) -> PublicOffer:
    offer = await _load_by_token(db, token)
    _maybe_mark_expired(offer)
    await db.flush()
    return await _to_public(db, offer)


@router.get(
    "/{token}/pdf",
    summary="PDF inline (page publique)",
)
async def public_offer_pdf(token: str, db: DBSession) -> Response:
    offer = await _load_by_token(db, token)
    pdf_bytes = await render_offer_pdf(db, offer.id)
    filename = f"offre-achat-{offer.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/{token}/sign",
    response_model=PublicOffer,
    summary="Signer (accepter) ou refuser l'offre",
)
async def sign_offer(
    token: str,
    data: SignRequest,
    request: Request,
    db: DBSession,
) -> PublicOffer:
    offer = await _load_by_token(db, token)
    if offer.status in (
        OfferStatus.SIGNE.value,
        OfferStatus.REFUSE.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Offre déjà finalisée."
        )
    _maybe_mark_expired(offer)
    if offer.status == OfferStatus.EXPIRE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cette offre a expiré.",
        )

    offer.signed_name = data.signed_name.strip()[:255]
    offer.signed_at = datetime.now(timezone.utc)
    offer.signed_ip = _client_ip(request)
    offer.status = (
        OfferStatus.SIGNE.value if data.accept else OfferStatus.REFUSE.value
    )
    await db.flush()
    await db.refresh(offer)

    # Notification interne best-effort (ne fait pas échouer la signature).
    try:
        from app.services.notifications import notify_role

        if data.accept:
            await notify_role(
                db,
                min_role="manager",
                kind="offer.signed",
                title=f"Offre #{offer.id} acceptée",
                body=f"Acceptée par {offer.signed_name}.",
                href=f"/prospection/pipeline/{offer.deal_id}",
            )
        else:
            await notify_role(
                db,
                min_role="manager",
                kind="offer.rejected",
                title=f"Offre #{offer.id} refusée",
                body=f"Refusée par {offer.signed_name}.",
                href=f"/prospection/pipeline/{offer.deal_id}",
            )
    except Exception:
        pass

    return await _to_public(db, offer)
