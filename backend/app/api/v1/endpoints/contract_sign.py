"""Contrat d'entreprise — signature de l'entrepreneur (Horizon) et
documents archivés dans la fiche client.

  POST /api/v1/soumissions/{id}/contractor-sign   l'entrepreneur signe
  GET  /api/v1/clients/{id}/documents             liste des documents
  GET  /api/v1/clients/{id}/documents/{doc}/download   téléchargement

Le chargé de projet signe le contrat pour la compagnie AVANT l'envoi
au client. La signature du client passe ensuite par le lien public
existant (public_soumission.py). À la signature du client, le contrat
signé est archivé dans la fiche client (voir client_documents ci-bas).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.api.v1.endpoints.public_soumission import _decode_data_url
from app.models.client_document import ClientDocument
from app.models.soumission import Soumission
from app.schemas.business import SoumissionRead

router = APIRouter(prefix="/soumissions", tags=["soumissions"])
docs_router = APIRouter(prefix="/clients", tags=["client-documents"])


class ContractorSignRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    signature_image_data_url: Optional[str] = Field(
        default=None, max_length=2_000_000
    )


@router.post(
    "/{soumission_id}/contractor-sign",
    response_model=SoumissionRead,
    summary="L'entrepreneur (Horizon) signe le contrat",
)
async def contractor_sign(
    soumission_id: int,
    data: ContractorSignRequest,
    request: Request,
    db: DBSession,
    _: RequireManager,
) -> SoumissionRead:
    sm = (
        await db.execute(
            select(Soumission).where(Soumission.id == soumission_id)
        )
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Soumission introuvable.")
    if getattr(sm, "kind", "quote") != "contract":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La signature de l'entrepreneur ne s'applique qu'à un contrat.",
        )
    sm.contractor_signed_name = data.name.strip()[:255]
    sm.contractor_signed_at = datetime.now(timezone.utc)
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
    # get_db committe en fin de requête ; un flush + refresh suffit.
    await db.flush()
    await db.refresh(sm)
    return SoumissionRead.model_validate(sm)


class ClientDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: int
    name: str
    content_type: str
    source: Optional[str]
    soumission_id: Optional[int]
    created_at: datetime


@docs_router.get(
    "/{client_id}/documents",
    response_model=list[ClientDocumentRead],
    summary="Liste les documents archivés d'un client",
)
async def list_client_documents(
    client_id: int, db: DBSession, _: CurrentUser
) -> list[ClientDocumentRead]:
    rows = (
        await db.execute(
            select(ClientDocument)
            .where(ClientDocument.client_id == client_id)
            .order_by(ClientDocument.created_at.desc())
        )
    ).scalars().all()
    return [ClientDocumentRead.model_validate(r) for r in rows]


@docs_router.get(
    "/{client_id}/documents/{doc_id}/download",
    summary="Télécharge un document d'un client",
)
async def download_client_document(
    client_id: int, doc_id: int, db: DBSession, _: CurrentUser
) -> Response:
    doc = (
        await db.execute(
            select(ClientDocument)
            .options(undefer(ClientDocument.blob))
            .where(
                ClientDocument.id == doc_id,
                ClientDocument.client_id == client_id,
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document introuvable.")
    return Response(
        content=doc.blob,
        media_type=doc.content_type or "application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc.name}"'
        },
    )
