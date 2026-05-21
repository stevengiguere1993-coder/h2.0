"""Public (no-auth) endpoints so a client can view & e-sign a final
facture from a unique tokenized link sent by email.

    GET  /api/v1/public/factures/{token}        -> JSON details
    GET  /api/v1/public/factures/{token}/pdf    -> inline PDF
    POST /api/v1/public/factures/{token}/sign   -> record signature

The token is opaque and acts as both authentication and audit trail —
the signed IP and name are captured when signed.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.models.facture import Facture
from app.services.facture_pdf import render_facture_pdf


router = APIRouter(prefix="/public/factures", tags=["public-factures"])


class PublicFacture(BaseModel):
    reference: str
    status: str
    is_final: bool
    issued_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    total: Optional[float] = None
    signed_name: Optional[str] = None
    signed_at: Optional[datetime] = None
    company_name: str = "Horizon Services Immobiliers"
    company_rbq: str = "RBQ 5868-5991-01"
    company_email: str = "info@immohorizon.com"


class SignRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    # Signature tracée, envoyée en data URL ("data:image/png;base64,…").
    signature_image_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000
    )


def _decode_data_url(
    data_url: Optional[str],
) -> tuple[Optional[bytes], Optional[str]]:
    """Parse une URL 'data:...;base64,...' → (bytes, content_type).
    (None, None) si l'entrée est nulle ou malformée."""
    if not data_url or not data_url.startswith("data:"):
        return None, None
    try:
        header, b64 = data_url.split(",", 1)
        content_type = "image/png"
        if ":" in header:
            after_colon = header.split(":", 1)[1]
            content_type = (
                after_colon.split(";", 1)[0]
                if ";" in after_colon
                else (after_colon or content_type)
            )
        raw = base64.b64decode(b64, validate=False)
        if len(raw) > 1_500_000:  # plafond ~1.5 Mo
            return None, None
        return raw, content_type
    except Exception:  # noqa: BLE001
        return None, None


async def _load_by_token(db: AsyncSession, token: str) -> Facture:
    fa = (
        await db.execute(
            select(Facture).where(Facture.signature_token == token)
        )
    ).scalar_one_or_none()
    if fa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lien invalide ou expiré.",
        )
    return fa


def _to_public(fa: Facture) -> PublicFacture:
    return PublicFacture(
        reference=fa.reference,
        status=fa.status,
        is_final=bool(fa.is_final),
        issued_at=fa.issued_at,
        due_at=fa.due_at,
        total=float(fa.total) if fa.total is not None else None,
        signed_name=fa.signed_name,
        signed_at=fa.signed_at,
    )


@router.get(
    "/{token}",
    response_model=PublicFacture,
    summary="Read the facture attached to a public signature token",
)
async def public_read(token: str, db: DBSession) -> PublicFacture:
    fa = await _load_by_token(db, token)
    return _to_public(fa)


@router.get(
    "/{token}/pdf",
    summary="Inline PDF preview for the public link",
)
async def public_pdf(token: str, db: DBSession) -> Response:
    fa = await _load_by_token(db, token)
    rendered = await render_facture_pdf(db, fa.id)
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF introuvable.")
    _, pdf_bytes = rendered
    filename = f"facture-{fa.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/{token}/sign",
    response_model=PublicFacture,
    summary="Client signs the final facture online",
)
async def public_sign(
    token: str,
    data: SignRequest,
    request: Request,
    db: DBSession,
) -> PublicFacture:
    fa = await _load_by_token(db, token)
    if not fa.is_final:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette facture n'est pas une facture finale.",
        )
    if fa.signed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette facture a déjà été signée.",
        )
    now = datetime.now(timezone.utc)
    fa.signed_name = data.name.strip()[:255]
    raw_ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else None
    )
    # x-forwarded-for peut chaîner plusieurs sauts — on garde le
    # premier (client d'origine) et on borne la longueur.
    if raw_ip:
        raw_ip = raw_ip.split(",")[0].strip()[:64]
    fa.signed_ip = raw_ip
    fa.signed_at = now

    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if sig_bytes:
        fa.signature_image = sig_bytes
        fa.signature_image_content_type = sig_ct

    await db.flush()
    return _to_public(fa)
