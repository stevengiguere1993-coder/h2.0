"""Endpoints publics (sans auth) : le locataire consulte et signe un
document locatif (avis TAL, trousse…) via un lien tokenisé
``/document/{token}``. Miroir léger de public_bail.py."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.api.deps import DBSession
from app.models.immobilier import Bail, ImmDocument, Locataire

router = APIRouter(prefix="/public/documents", tags=["public-documents"])


class PublicDocument(BaseModel):
    titre: str
    type: str
    locataire_name: Optional[str]
    envoye_le: Optional[datetime]
    signed_at: Optional[datetime]
    signed_by_name: Optional[str]
    company_name: str = "Horizon Services Immobiliers"
    company_email: str = "info@immohorizon.com"


class SignDocument(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    signature_image_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000
    )


def _decode_data_url(
    data_url: Optional[str],
) -> tuple[Optional[bytes], Optional[str]]:
    if not data_url or not data_url.startswith("data:"):
        return None, None
    try:
        header, b64 = data_url.split(",", 1)
        ct = "image/png"
        if ":" in header:
            after = header.split(":", 1)[1]
            ct = after.split(";", 1)[0] if ";" in after else after
        raw = base64.b64decode(b64, validate=False)
        if len(raw) > 1_500_000:
            return None, None
        return raw, ct
    except Exception:  # noqa: BLE001
        return None, None


async def _load(db: AsyncSession, token: str) -> ImmDocument:
    doc = (
        await db.execute(
            select(ImmDocument).where(
                ImmDocument.signature_token == token
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Lien invalide ou expiré."
        )
    return doc


async def _to_public(db: AsyncSession, doc: ImmDocument) -> PublicDocument:
    locataire: Optional[Locataire] = None
    if doc.locataire_id:
        locataire = await db.get(Locataire, doc.locataire_id)
    elif doc.bail_id:
        bail = await db.get(Bail, doc.bail_id)
        if bail:
            locataire = await db.get(Locataire, bail.locataire_id)
    return PublicDocument(
        titre=doc.titre,
        type=doc.type,
        locataire_name=locataire.full_name if locataire else None,
        envoye_le=doc.envoye_le,
        signed_at=doc.signed_at,
        signed_by_name=doc.signed_by_name,
    )


@router.get("/{token}", response_model=PublicDocument)
async def public_read(token: str, db: DBSession) -> PublicDocument:
    doc = await _load(db, token)
    # Preuve d'ouverture : première consultation horodatée.
    if doc.ouvert_le is None:
        doc.ouvert_le = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(doc)
    return await _to_public(db, doc)


@router.get("/{token}/pdf")
async def public_pdf(token: str, db: DBSession) -> Response:
    doc = (
        await db.execute(
            select(ImmDocument)
            .options(undefer(ImmDocument.pdf_blob))
            .where(ImmDocument.signature_token == token)
        )
    ).scalar_one_or_none()
    if doc is None or not doc.pdf_blob:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Lien invalide ou expiré."
        )
    return Response(
        content=doc.pdf_blob,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="document.pdf"'},
    )


@router.post("/{token}/signer", response_model=PublicDocument)
async def public_sign(
    token: str, data: SignDocument, request: Request, db: DBSession
) -> PublicDocument:
    doc = await _load(db, token)
    if doc.signed_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Ce document est déjà signé.",
        )
    doc.signed_at = datetime.now(timezone.utc)
    doc.signed_by_name = data.name.strip()[:255]
    raw_ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else None
    )
    if raw_ip:
        doc.signature_ip = raw_ip.split(",")[0].strip()[:64]
    sig, ct = _decode_data_url(data.signature_image_data_url)
    if sig:
        doc.signature_image = sig
        doc.signature_image_content_type = ct
    await db.commit()
    await db.refresh(doc)
    return await _to_public(db, doc)
