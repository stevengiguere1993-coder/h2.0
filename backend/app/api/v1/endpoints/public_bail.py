"""Endpoints publics (sans auth) : un locataire consulte et signe son
bail via un lien tokenisé `/bail/{token}`."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.models.immobilier import Bail, Immeuble, Logement, Locataire

router = APIRouter(prefix="/public/baux", tags=["public-baux"])


class PublicBail(BaseModel):
    locataire_name: Optional[str]
    immeuble_name: Optional[str]
    adresse: Optional[str]
    logement: Optional[str]
    loyer_mensuel: float
    date_debut: str
    date_fin: str
    depot_garantie: Optional[float]
    chauffage_inclus: bool
    eau_chaude_inclus: bool
    electricite_inclus: bool
    internet_inclus: bool
    signed_at: Optional[datetime]
    signed_by_name: Optional[str]
    company_name: str = "Horizon Services Immobiliers"
    company_email: str = "info@immohorizon.com"


class AcceptBail(BaseModel):
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
    except Exception:
        return None, None


async def _load(db: AsyncSession, token: str) -> Bail:
    bail = (
        await db.execute(
            select(Bail).where(Bail.signature_token == token)
        )
    ).scalar_one_or_none()
    if bail is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Lien invalide ou expiré."
        )
    return bail


async def _to_public(db: AsyncSession, bail: Bail) -> PublicBail:
    logement = await db.get(Logement, bail.logement_id)
    locataire = await db.get(Locataire, bail.locataire_id)
    immeuble = (
        await db.get(Immeuble, logement.immeuble_id) if logement else None
    )
    adresse = None
    if immeuble:
        adresse = immeuble.address + (
            f", {immeuble.city}" if immeuble.city else ""
        )
    return PublicBail(
        locataire_name=locataire.full_name if locataire else None,
        immeuble_name=immeuble.name if immeuble else None,
        adresse=adresse,
        logement=logement.numero if logement else None,
        loyer_mensuel=float(bail.loyer_mensuel),
        date_debut=str(bail.date_debut),
        date_fin=str(bail.date_fin),
        depot_garantie=(
            float(bail.depot_garantie)
            if bail.depot_garantie is not None
            else None
        ),
        chauffage_inclus=bail.chauffage_inclus,
        eau_chaude_inclus=bail.eau_chaude_inclus,
        electricite_inclus=bail.electricite_inclus,
        internet_inclus=bail.internet_inclus,
        signed_at=bail.signed_at,
        signed_by_name=bail.signed_by_name,
    )


@router.get("/{token}", response_model=PublicBail)
async def public_read(token: str, db: DBSession) -> PublicBail:
    bail = await _load(db, token)
    return await _to_public(db, bail)


@router.post("/{token}/accept", response_model=PublicBail)
async def public_accept(
    token: str, data: AcceptBail, request: Request, db: DBSession
) -> PublicBail:
    bail = await _load(db, token)
    if bail.signed_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Ce bail est déjà signé."
        )
    bail.signed_at = datetime.now(timezone.utc)
    bail.signed_by_name = data.name.strip()[:255]
    raw_ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else None
    )
    if raw_ip:
        bail.signature_ip = raw_ip.split(",")[0].strip()[:64]
    sig, ct = _decode_data_url(data.signature_image_data_url)
    if sig:
        bail.signature_image = sig
        bail.signature_image_content_type = ct
    # Un bail proposé qui vient d'être signé devient actif.
    if bail.status == "propose":
        bail.status = "actif"
    await db.flush()
    await db.refresh(bail)
    return await _to_public(db, bail)
