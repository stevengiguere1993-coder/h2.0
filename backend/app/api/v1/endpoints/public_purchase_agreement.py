"""Endpoints publics (no auth) pour la signature d'une PA.

Flow étape 1 — acheteur interne :
    GET  /public/purchase-agreements/buyer/{token}        -> JSON détails
    GET  /public/purchase-agreements/buyer/{token}/pdf    -> PDF inline
    POST /public/purchase-agreements/buyer/{token}/sign   -> signe la PA

Flow étape 2 — vendeur :
    GET  /public/purchase-agreements/seller/{token}        -> JSON détails
    GET  /public/purchase-agreements/seller/{token}/pdf    -> PDF inline
    POST /public/purchase-agreements/seller/{token}/accept -> accepte
    POST /public/purchase-agreements/seller/{token}/reject -> refuse

Le token est opaque et fait office d'authentification + audit trail
(IP + nom + heure capturés à la signature).
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.models.purchase_agreement import (
    PurchaseAgreement,
    PurchaseAgreementStatus,
)
from app.services.purchase_agreement_pdf import render_purchase_agreement_pdf


router = APIRouter(
    prefix="/public/purchase-agreements", tags=["public-purchase-agreements"]
)


# --------------------------- Schemas publics ---------------------------


class PublicPurchaseAgreement(BaseModel):
    """Vue publique épurée pour les pages de signature."""

    model_config = ConfigDict(from_attributes=True)

    reference: str
    status: str
    role: str  # "buyer" ou "seller" — calculé selon le token utilisé
    property_address: Optional[str]
    price: Optional[float]
    down_payment: Optional[float]
    mortgage_amount: Optional[float]
    deposit_amount: Optional[float]
    inspection_enabled: bool
    inspection_days: int
    visit_units_enabled: bool
    water_septic_enabled: bool
    buyer_property_sale_enabled: bool
    conditional_other_offer_enabled: bool
    act_of_sale_date: Optional[str]
    occupation_date: Optional[str]
    acceptance_deadline_date: Optional[str]
    acceptance_deadline_time: Optional[str]
    seller_1_name: Optional[str]
    buyer_1_name: Optional[str]
    buyer_signed_at: Optional[datetime]
    buyer_signed_name: Optional[str]
    seller_signed_at: Optional[datetime]
    seller_signed_name: Optional[str]
    seller_response: Optional[str]


class SignRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    signature_image_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000
    )


class RejectRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    signature_image_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000
    )
    reason: Optional[str] = Field(default=None, max_length=1000)


# --------------------------- Helpers ---------------------------


def _decode_data_url(
    data_url: Optional[str],
) -> tuple[Optional[bytes], Optional[str]]:
    if not data_url or not data_url.startswith("data:"):
        return None, None
    try:
        header, b64 = data_url.split(",", 1)
        content_type = "image/png"
        if ":" in header:
            after = header.split(":", 1)[1]
            content_type = after.split(";", 1)[0] if ";" in after else after
        raw = base64.b64decode(b64, validate=False)
        if len(raw) > 1_500_000:
            return None, None
        return raw, content_type or "image/png"
    except Exception:
        return None, None


def _client_ip(request: Request) -> Optional[str]:
    raw = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else None)
    )
    if raw:
        return raw.split(",")[0].strip()[:64]
    return None


async def _load_by_buyer_token(
    db: AsyncSession, token: str
) -> PurchaseAgreement:
    pa = (
        await db.execute(
            select(PurchaseAgreement).where(
                PurchaseAgreement.buyer_signature_token == token
            )
        )
    ).scalar_one_or_none()
    if pa is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré."
        )
    return pa


async def _load_by_seller_token(
    db: AsyncSession, token: str
) -> PurchaseAgreement:
    pa = (
        await db.execute(
            select(PurchaseAgreement).where(
                PurchaseAgreement.seller_signature_token == token
            )
        )
    ).scalar_one_or_none()
    if pa is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré."
        )
    return pa


def _to_public(pa: PurchaseAgreement, role: str) -> PublicPurchaseAgreement:
    return PublicPurchaseAgreement(
        reference=pa.reference,
        status=pa.status,
        role=role,
        property_address=pa.property_address,
        price=float(pa.price) if pa.price is not None else None,
        down_payment=float(pa.down_payment)
        if pa.down_payment is not None
        else None,
        mortgage_amount=float(pa.mortgage_amount)
        if pa.mortgage_amount is not None
        else None,
        deposit_amount=float(pa.deposit_amount)
        if pa.deposit_amount is not None
        else None,
        inspection_enabled=pa.inspection_enabled,
        inspection_days=pa.inspection_days,
        visit_units_enabled=pa.visit_units_enabled,
        water_septic_enabled=pa.water_septic_enabled,
        buyer_property_sale_enabled=pa.buyer_property_sale_enabled,
        conditional_other_offer_enabled=pa.conditional_other_offer_enabled,
        act_of_sale_date=pa.act_of_sale_date.isoformat()
        if pa.act_of_sale_date
        else None,
        occupation_date=pa.occupation_date.isoformat()
        if pa.occupation_date
        else None,
        acceptance_deadline_date=pa.acceptance_deadline_date.isoformat()
        if pa.acceptance_deadline_date
        else None,
        acceptance_deadline_time=pa.acceptance_deadline_time,
        seller_1_name=pa.seller_1_name,
        buyer_1_name=pa.buyer_1_name,
        buyer_signed_at=pa.buyer_signed_at,
        buyer_signed_name=pa.buyer_signed_name,
        seller_signed_at=pa.seller_signed_at,
        seller_signed_name=pa.seller_signed_name,
        seller_response=pa.seller_response,
    )


async def _pdf_response(
    db: AsyncSession, pa: PurchaseAgreement
) -> Response:
    pdf_bytes = await render_purchase_agreement_pdf(db, pa.id)
    filename = f"promesse-achat-{pa.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# --------------------------- Buyer routes ---------------------------


@router.get(
    "/buyer/{token}",
    response_model=PublicPurchaseAgreement,
    summary="Vue publique pour l'acheteur (étape 1)",
)
async def buyer_read(token: str, db: DBSession) -> PublicPurchaseAgreement:
    pa = await _load_by_buyer_token(db, token)
    return _to_public(pa, "buyer")


@router.get(
    "/buyer/{token}/pdf",
    summary="PDF inline pour l'acheteur",
)
async def buyer_pdf(token: str, db: DBSession) -> Response:
    pa = await _load_by_buyer_token(db, token)
    return await _pdf_response(db, pa)


@router.post(
    "/buyer/{token}/sign",
    response_model=PublicPurchaseAgreement,
    summary="Signature de l'acheteur — passe la PA en attente du vendeur",
)
async def buyer_sign(
    token: str,
    data: SignRequest,
    request: Request,
    db: DBSession,
) -> PublicPurchaseAgreement:
    pa = await _load_by_buyer_token(db, token)
    if pa.buyer_signed_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "PA déjà signée par l'acheteur."
        )
    if pa.status not in (
        PurchaseAgreementStatus.DRAFT.value,
        PurchaseAgreementStatus.PENDING_BUYER_SIGNATURE.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Statut PA incompatible."
        )

    pa.buyer_signed_name = data.name.strip()[:255]
    pa.buyer_signed_at = datetime.now(timezone.utc)
    pa.buyer_signed_ip = _client_ip(request)

    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if sig_bytes:
        pa.buyer_signature_image = sig_bytes
        pa.buyer_signature_image_content_type = sig_ct

    pa.status = PurchaseAgreementStatus.PENDING_SELLER_SIGNATURE.value

    await db.flush()
    await db.refresh(pa)

    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="purchase_agreement.buyer_signed",
            title=f"PA {pa.reference} signée par l'acheteur",
            body=f"Prête à envoyer au vendeur.",
            href=f"/app/prospection/{pa.lead_id}",
        )
    except Exception:
        pass

    return _to_public(pa, "buyer")


# --------------------------- Seller routes ---------------------------


@router.get(
    "/seller/{token}",
    response_model=PublicPurchaseAgreement,
    summary="Vue publique pour le vendeur (étape 2)",
)
async def seller_read(token: str, db: DBSession) -> PublicPurchaseAgreement:
    pa = await _load_by_seller_token(db, token)
    return _to_public(pa, "seller")


@router.get(
    "/seller/{token}/pdf",
    summary="PDF inline pour le vendeur",
)
async def seller_pdf(token: str, db: DBSession) -> Response:
    pa = await _load_by_seller_token(db, token)
    return await _pdf_response(db, pa)


@router.post(
    "/seller/{token}/accept",
    response_model=PublicPurchaseAgreement,
    summary="Le vendeur accepte la PA",
)
async def seller_accept(
    token: str,
    data: SignRequest,
    request: Request,
    db: DBSession,
) -> PublicPurchaseAgreement:
    pa = await _load_by_seller_token(db, token)
    if pa.status in (
        PurchaseAgreementStatus.ACCEPTED.value,
        PurchaseAgreementStatus.REJECTED.value,
        PurchaseAgreementStatus.EXPIRED.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "PA déjà finalisée."
        )

    pa.seller_signed_name = data.name.strip()[:255]
    pa.seller_signed_at = datetime.now(timezone.utc)
    pa.seller_signed_ip = _client_ip(request)
    pa.seller_response = "accepted"

    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if sig_bytes:
        pa.seller_signature_image = sig_bytes
        pa.seller_signature_image_content_type = sig_ct

    pa.status = PurchaseAgreementStatus.ACCEPTED.value

    await db.flush()
    await db.refresh(pa)

    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="purchase_agreement.accepted",
            title=f"PA {pa.reference} acceptée",
            body=f"Acceptée par {pa.seller_signed_name}.",
            href=f"/app/prospection/{pa.lead_id}",
        )
    except Exception:
        pass

    return _to_public(pa, "seller")


@router.post(
    "/seller/{token}/reject",
    response_model=PublicPurchaseAgreement,
    summary="Le vendeur refuse la PA",
)
async def seller_reject(
    token: str,
    data: RejectRequest,
    request: Request,
    db: DBSession,
) -> PublicPurchaseAgreement:
    pa = await _load_by_seller_token(db, token)
    if pa.status in (
        PurchaseAgreementStatus.ACCEPTED.value,
        PurchaseAgreementStatus.REJECTED.value,
        PurchaseAgreementStatus.EXPIRED.value,
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "PA déjà finalisée.")

    pa.seller_signed_name = data.name.strip()[:255]
    pa.seller_signed_at = datetime.now(timezone.utc)
    pa.seller_signed_ip = _client_ip(request)
    pa.seller_response = "rejected"
    if data.reason:
        pa.seller_rejection_reason = data.reason.strip()[:1000]

    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if sig_bytes:
        pa.seller_signature_image = sig_bytes
        pa.seller_signature_image_content_type = sig_ct

    pa.status = PurchaseAgreementStatus.REJECTED.value

    await db.flush()
    await db.refresh(pa)

    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="purchase_agreement.rejected",
            title=f"PA {pa.reference} refusée",
            body=(data.reason or "")[:200] or "Aucun motif fourni.",
            href=f"/app/prospection/{pa.lead_id}",
        )
    except Exception:
        pass

    return _to_public(pa, "seller")
