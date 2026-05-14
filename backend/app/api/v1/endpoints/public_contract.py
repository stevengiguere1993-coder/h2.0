"""Endpoints publics (sans authentification) — le chargé de projet
(responsable du projet) signe le contrat d'entreprise pour Horizon via
un lien tokenisé reçu par courriel.

    GET  /api/v1/public/contracts/{token}                 -> infos
    GET  /api/v1/public/contracts/{token}/pdf             -> PDF inline
    POST /api/v1/public/contracts/{token}/contractor-sign -> signe

Le jeton est opaque et sert d'authentification + piste d'audit : le
nom, l'IP et l'horodatage sont capturés à la signature.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.api.v1.endpoints.public_soumission import _decode_data_url
from app.models.soumission import Soumission
from app.services.soumission_pdf import render_soumission_pdf

router = APIRouter(
    prefix="/public/contracts", tags=["public-contracts"]
)


class PublicContract(BaseModel):
    reference: str
    title: str
    company_name: str = "Horizon Services Immobiliers"
    contractor_signed_name: Optional[str]
    contractor_signed_at: Optional[datetime]
    client_signed: bool = False
    status: str


class ContractorSignRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    signature_image_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000
    )


async def _load_by_token(db: AsyncSession, token: str) -> Soumission:
    sm = (
        await db.execute(
            select(Soumission).where(
                Soumission.contractor_signature_token == token
            )
        )
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lien invalide ou expiré.",
        )
    return sm


def _to_public(sm: Soumission) -> PublicContract:
    return PublicContract(
        reference=sm.reference,
        title=sm.title,
        contractor_signed_name=sm.contractor_signed_name,
        contractor_signed_at=sm.contractor_signed_at,
        client_signed=bool(sm.signed_name),
        status=sm.status,
    )


@router.get(
    "/{token}",
    response_model=PublicContract,
    summary="Lit le contrat attaché à un jeton de signature entrepreneur",
)
async def public_contract_read(token: str, db: DBSession) -> PublicContract:
    sm = await _load_by_token(db, token)
    return _to_public(sm)


@router.get(
    "/{token}/pdf",
    summary="PDF du contrat pour le lien de signature entrepreneur",
)
async def public_contract_pdf(token: str, db: DBSession) -> Response:
    sm = await _load_by_token(db, token)
    rendered = await render_soumission_pdf(db, sm.id)
    if rendered is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "PDF introuvable."
        )
    _, pdf_bytes = rendered
    filename = f"contrat-{sm.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"'
        },
    )


@router.post(
    "/{token}/contractor-sign",
    response_model=PublicContract,
    summary="Le chargé de projet signe le contrat pour Horizon",
)
async def public_contractor_sign(
    token: str,
    data: ContractorSignRequest,
    request: Request,
    db: DBSession,
) -> PublicContract:
    sm = await _load_by_token(db, token)
    now = datetime.now(timezone.utc)
    sm.contractor_signed_name = data.name.strip()[:255]
    sm.contractor_signed_at = now
    raw_ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else None
    )
    if raw_ip:
        raw_ip = raw_ip.split(",")[0].strip()[:64]
    sm.contractor_signed_ip = raw_ip
    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if sig_bytes:
        sm.contractor_signature_image = sig_bytes
        sm.contractor_signature_image_content_type = sig_ct
    await db.flush()

    # Notifie les gestionnaires que le contrat est signé côté Horizon.
    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="contract.contractor_signed",
            title=f"Contrat signé par Horizon — {sm.reference}",
            body=(
                f"Signé par {sm.contractor_signed_name}. "
                "Le contrat peut être envoyé au client."
            ),
            href=f"/app/soumissions/{sm.id}",
        )
    except Exception:  # noqa: BLE001
        pass

    await db.refresh(sm)
    return _to_public(sm)
