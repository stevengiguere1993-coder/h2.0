"""Public (no-auth) endpoints so a client can view & e-sign a
soumission from a unique tokenized link sent by email.

    GET  /api/v1/public/soumissions/{token}          -> JSON details
    GET  /api/v1/public/soumissions/{token}/pdf      -> inline PDF
    POST /api/v1/public/soumissions/{token}/accept   -> mark accepted
    POST /api/v1/public/soumissions/{token}/reject   -> mark rejected

The token is opaque and acts as both authentication and audit
trail — the signed IP and name are captured when accepted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.models.client import Client
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.soumission import Soumission, SoumissionStatus
from app.models.soumission_item import SoumissionItem
from app.services.soumission_pdf import render_soumission_pdf


router = APIRouter(prefix="/public/soumissions", tags=["public-soumissions"])


class PublicItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    position: int
    description: str
    unit: Optional[str]
    quantity: float
    unit_price: float
    total: float


class PublicSoumission(BaseModel):
    reference: str
    title: str
    description: Optional[str]
    status: str
    valid_until: Optional[datetime]
    signed_name: Optional[str]
    items: list[PublicItem]
    subtotal: float
    tps: float
    tvq: float
    total: float
    company_name: str = "Horizon Services Immobiliers"
    company_rbq: str = "RBQ 5868-5991-01"
    company_email: str = "info@immohorizon.com"


class AcceptRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    # Drawn signature, sent as a data URL ("data:image/png;base64,…").
    # Optional for backward compat (a typed name still works).
    signature_image_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000
    )


def _decode_data_url(data_url: Optional[str]) -> tuple[Optional[bytes], Optional[str]]:
    """Parse a 'data:...;base64,...' URL and return (bytes, content_type).
    Returns (None, None) if the input is None or malformed."""
    import base64
    if not data_url:
        return None, None
    if not data_url.startswith("data:"):
        return None, None
    try:
        header, b64 = data_url.split(",", 1)
        # header looks like "data:image/png;base64"
        content_type = "image/png"
        if ":" in header:
            after_colon = header.split(":", 1)[1]
            if ";" in after_colon:
                content_type = after_colon.split(";", 1)[0]
            else:
                content_type = after_colon or content_type
        raw = base64.b64decode(b64, validate=False)
        if len(raw) > 1_500_000:  # ~1.5 MB cap
            return None, None
        return raw, content_type
    except Exception:
        return None, None


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


async def _load_by_token(
    db: AsyncSession, token: str
) -> Soumission:
    sm = (
        await db.execute(
            select(Soumission).where(Soumission.signature_token == token)
        )
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lien invalide ou expiré.",
        )
    return sm


@router.get(
    "/{token}",
    response_model=PublicSoumission,
    summary="Read the soumission attached to a public signature token",
)
async def public_read(token: str, db: DBSession) -> PublicSoumission:
    sm = await _load_by_token(db, token)
    rows = list(
        (
            await db.execute(
                select(SoumissionItem)
                .where(SoumissionItem.soumission_id == sm.id)
                .order_by(
                    SoumissionItem.position.asc(), SoumissionItem.id.asc()
                )
            )
        ).scalars().all()
    )
    # Recompute totals from items so the client view is always
    # consistent with what the staff sees.
    subtotal = 0.0
    for it in rows:
        if it.total is not None:
            subtotal += float(it.total)
        else:
            subtotal += float(it.quantity) * float(it.unit_price)
    subtotal = round(subtotal, 2)
    tps = round(subtotal * 0.05, 2)
    tvq = round(subtotal * 0.09975, 2)
    total = round(subtotal + tps + tvq, 2)
    return PublicSoumission(
        reference=sm.reference,
        title=sm.title,
        description=sm.description,
        status=sm.status,
        valid_until=sm.valid_until,
        signed_name=sm.signed_name,
        items=[PublicItem.model_validate(r) for r in rows],
        subtotal=subtotal,
        tps=tps,
        tvq=tvq,
        total=total,
    )


@router.get(
    "/{token}/pdf",
    summary="Inline PDF preview for the public link",
)
async def public_pdf(token: str, db: DBSession) -> Response:
    sm = await _load_by_token(db, token)
    rendered = await render_soumission_pdf(db, sm.id)
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF introuvable.")
    _, pdf_bytes = rendered
    filename = f"soumission-{sm.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/{token}/accept",
    response_model=PublicSoumission,
    summary="Client accepts the soumission online",
)
async def public_accept(
    token: str,
    data: AcceptRequest,
    request: Request,
    db: DBSession,
) -> PublicSoumission:
    sm = await _load_by_token(db, token)
    if sm.status in (
        SoumissionStatus.REJECTED.value,
        SoumissionStatus.EXPIRED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette soumission n'est plus active.",
        )
    now = datetime.now(timezone.utc)
    sm.status = SoumissionStatus.ACCEPTED.value
    if sm.accepted_at is None:
        sm.accepted_at = now
    sm.signed_name = data.name.strip()[:255]
    raw_ip = (
        request.headers.get("x-forwarded-for") or (
            request.client.host if request.client else None
        )
    )
    # x-forwarded-for can chain multiple hops (CF + Render + client),
    # easily exceeding the VARCHAR(64) column. Keep only the first
    # (original client) IP and cap the length defensively.
    if raw_ip:
        raw_ip = raw_ip.split(",")[0].strip()[:64]
    sm.signed_ip = raw_ip

    # Persist the drawn signature when provided.
    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if sig_bytes:
        sm.signature_image = sig_bytes
        sm.signature_image_content_type = sig_ct

    # Propagate to prospect + auto-create client (same logic as the
    # internal /status endpoint).
    if sm.contact_request_id:
        cr = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == sm.contact_request_id
                )
            )
        ).scalar_one_or_none()
        if cr is not None:
            cr.status = ContactRequestStatus.WON.value
            existing = (
                await db.execute(
                    select(Client).where(Client.contact_request_id == cr.id)
                )
            ).scalar_one_or_none()
            if existing is None:
                client = Client(
                    name=cr.name,
                    email=cr.email,
                    phone=cr.phone,
                    address=cr.address,
                    contact_request_id=cr.id,
                )
                db.add(client)
                await db.flush()
                if sm.client_id is None:
                    sm.client_id = client.id
            elif sm.client_id is None:
                sm.client_id = existing.id

    await db.flush()
    await db.refresh(sm)

    # Notify managers+ that the quote was signed online
    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="soumission.accepted",
            title=f"Soumission acceptée — {sm.reference}",
            body=f"Signée par {sm.signed_name} en ligne.",
            href=f"/app/soumissions/{sm.id}",
        )
    except Exception:
        pass

    return await public_read(token, db)


@router.post(
    "/{token}/reject",
    response_model=PublicSoumission,
    summary="Client rejects the soumission online",
)
async def public_reject(
    token: str,
    data: RejectRequest,
    db: DBSession,
) -> PublicSoumission:
    sm = await _load_by_token(db, token)
    sm.status = SoumissionStatus.REJECTED.value
    # Append the reason to the internal notes for staff visibility.
    if data.reason:
        reason = data.reason.strip()
        prefix = "[Refus client] "
        new_note = f"{prefix}{reason}"
        sm.notes = f"{sm.notes}\n{new_note}" if sm.notes else new_note

    # Propagate to prospect as "lost".
    if sm.contact_request_id:
        cr = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == sm.contact_request_id
                )
            )
        ).scalar_one_or_none()
        if cr is not None:
            cr.status = ContactRequestStatus.LOST.value

    await db.flush()
    await db.refresh(sm)
    return await public_read(token, db)
