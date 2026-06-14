"""Public (no-auth) endpoints for a client to view and e-sign a
bon de travail from a tokenized link."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.models.bon_item import BonItem
from app.models.bon_travail import BonTravail, BonTravailStatus
from app.services.bon_pdf import render_bon_pdf


router = APIRouter(prefix="/public/bons", tags=["public-bons"])


class PublicItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    position: int
    description: str
    unit: Optional[str]
    quantity: float
    unit_price: float
    total: float


class PublicBon(BaseModel):
    reference: str
    title: str
    description: Optional[str]
    scope_md: Optional[str]
    status: str
    amount: Optional[float]
    signed_by_name: Optional[str]
    signed_at: Optional[datetime]
    items: list[PublicItem]
    total: float
    company_name: str = "Horizon Services Immobiliers"
    company_rbq: str = "RBQ 5868-5991-01"
    company_email: str = "info@immohorizon.com"


class AcceptRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    signature_image_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000
    )


def _decode_data_url(data_url: Optional[str]) -> tuple[Optional[bytes], Optional[str]]:
    import base64
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
        return raw, content_type
    except Exception:
        return None, None


async def _load_by_token(db: AsyncSession, token: str) -> BonTravail:
    bon = (
        await db.execute(
            select(BonTravail).where(BonTravail.signature_token == token)
        )
    ).scalar_one_or_none()
    if bon is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lien invalide ou expiré.",
        )
    return bon


@router.get("/{token}", response_model=PublicBon)
async def public_read(token: str, db: DBSession) -> PublicBon:
    bon = await _load_by_token(db, token)
    rows = list(
        (
            await db.execute(
                select(BonItem)
                .where(BonItem.bon_id == bon.id)
                .order_by(BonItem.position.asc(), BonItem.id.asc())
            )
        ).scalars().all()
    )
    subtotal = sum(
        (
            float(it.total)
            if it.total is not None
            else float(it.quantity) * float(it.unit_price)
        )
        for it in rows
    )
    total = (
        round(subtotal, 2)
        if rows
        else (float(bon.amount) if bon.amount is not None else 0.0)
    )
    return PublicBon(
        reference=bon.reference,
        title=bon.title,
        description=bon.description,
        scope_md=bon.scope_md,
        status=bon.status,
        amount=float(bon.amount) if bon.amount is not None else None,
        signed_by_name=bon.signed_by_name,
        signed_at=bon.signed_at,
        items=[PublicItem.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/{token}/pdf")
async def public_pdf(token: str, db: DBSession) -> Response:
    bon = await _load_by_token(db, token)
    rendered = await render_bon_pdf(db, bon.id)
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF introuvable.")
    _, pdf_bytes = rendered
    filename = f"bon-{bon.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{token}/accept", response_model=PublicBon)
async def public_accept(
    token: str,
    data: AcceptRequest,
    request: Request,
    db: DBSession,
) -> PublicBon:
    bon = await _load_by_token(db, token)
    if bon.status in (
        BonTravailStatus.SIGNED.value,
        BonTravailStatus.CANCELLED.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Ce bon n'est plus modifiable.",
        )
    # Signature tracée OBLIGATOIRE : le nom seul ne suffit pas. Validé
    # avant toute mutation pour ne rien persister en cas de refus.
    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if not sig_bytes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La signature tracée est obligatoire.",
        )

    now = datetime.now(timezone.utc)
    bon.status = BonTravailStatus.SIGNED.value
    bon.signed_at = now
    bon.signed_by_name = data.name.strip()[:255]
    raw_ip = (
        request.headers.get("x-forwarded-for") or (
            request.client.host if request.client else None
        )
    )
    if raw_ip:
        raw_ip = raw_ip.split(",")[0].strip()[:64]
    bon.signature_ip = raw_ip

    # Persist the drawn signature (guaranteed present at this point).
    bon.signature_image = sig_bytes
    bon.signature_image_content_type = sig_ct
    await db.flush()
    await db.refresh(bon)
    return await public_read(token, db)
