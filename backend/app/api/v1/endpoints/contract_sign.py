"""Contrat d'entreprise — envoi pour signature de l'entrepreneur et
documents archivés dans la fiche client.

  POST /api/v1/soumissions/{id}/send-for-contractor-signature
        → envoie au chargé de projet (responsable du projet) un
          courriel avec un lien public pour signer le contrat.
  GET  /api/v1/clients/{id}/documents               liste des documents
  GET  /api/v1/clients/{id}/documents/{doc}/download   téléchargement

Le chargé de projet signe le contrat pour la compagnie AVANT l'envoi
au client, via le lien public reçu par courriel (voir
public_contract.py). La signature du client passe ensuite par le lien
public existant (public_soumission.py).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.integrations.email_graph import get_mailer
from app.models.client import Client
from app.models.client_document import ClientDocument
from app.models.soumission import Soumission
from app.models.user import User
from app.schemas.business import SoumissionRead

log = logging.getLogger(__name__)

router = APIRouter(prefix="/soumissions", tags=["soumissions"])
docs_router = APIRouter(prefix="/clients", tags=["client-documents"])


def _public_base() -> str:
    return (
        os.getenv("PUBLIC_SITE_URL") or "https://immohorizon.com"
    ).rstrip("/")


@router.post(
    "/{soumission_id}/send-for-contractor-signature",
    response_model=SoumissionRead,
    summary="Envoie le contrat au chargé de projet pour signature",
)
async def send_for_contractor_signature(
    soumission_id: int,
    db: DBSession,
    _: RequireManager,
) -> SoumissionRead:
    """Envoie au responsable du projet un courriel contenant un lien
    public pour signer le contrat au nom d'Horizon. Génère un jeton de
    signature dédié à l'entrepreneur s'il n'existe pas encore."""
    sm = (
        await db.execute(
            select(Soumission).where(Soumission.id == soumission_id)
        )
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Soumission introuvable."
        )
    if getattr(sm, "kind", "quote") != "contract":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "L'envoi pour signature ne s'applique qu'à un contrat.",
        )
    # Responsable du projet → destinataire du courriel de signature.
    try:
        cd = json.loads(sm.contract_data) if sm.contract_data else {}
    except (TypeError, ValueError):
        cd = {}
    rid = cd.get("responsable_user_id") if isinstance(cd, dict) else None
    if not rid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Choisis d'abord un responsable du projet dans le contrat.",
        )
    user = (
        await db.execute(select(User).where(User.id == int(rid)))
    ).scalar_one_or_none()
    if user is None or not user.email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Le responsable du projet n'a pas de courriel renseigné.",
        )
    mailer = get_mailer()
    if not mailer.ready:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Service de courriel non configuré.",
        )
    if not sm.contractor_signature_token:
        sm.contractor_signature_token = secrets.token_urlsafe(32)
        await db.flush()

    link = (
        f"{_public_base()}/contrat-signature/"
        f"{sm.contractor_signature_token}"
    )
    responsable = (
        getattr(user, "display_name", None)
        or " ".join(
            p
            for p in [
                getattr(user, "first_name", None),
                getattr(user, "last_name", None),
            ]
            if p
        )
        or user.email
    )
    html = f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p style="margin:0 0 16px 0">Bonjour {responsable},</p>
  <p style="margin:0 0 16px 0">
    Le contrat d'entreprise <strong>{sm.reference}</strong> —
    <em>{sm.title}</em> est prêt et attend votre signature pour
    Horizon Services Immobiliers, en tant que responsable du projet.
  </p>
  <p style="margin:0 0 16px 0">
    Cliquez ci-dessous pour consulter le contrat et le signer. Une
    fois signé, il pourra être envoyé au client.
  </p>
  <p style="margin:20px 0 6px 0">
    <a href="{link}"
       style="display:inline-block;background:#d89b3c;color:#111;
              padding:12px 20px;border-radius:8px;font-weight:bold;
              text-decoration:none">Consulter et signer le contrat</a>
  </p>
  <p style="margin:0 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {link}
  </p>
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>
    RBQ 5868-5991-01<br>
    info@immohorizon.com &middot; immohorizon.com
  </p>
</div>
"""
    try:
        await mailer.send(
            to=[user.email],
            subject=f"Contrat {sm.reference} — signature requise",
            html_body=html,
            reply_to=mailer.sender,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "Envoi du contrat %s au chargé de projet a échoué",
            soumission_id,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Envoi du courriel échoué : {exc}",
        ) from exc

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


_DOC_MIME_ALLOWED = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}
_DOC_MAX_BYTES = 25 * 1024 * 1024  # 25 Mo (plans PDF volumineux)


@docs_router.post(
    "/{client_id}/documents",
    response_model=ClientDocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Téléverse un document (PDF, plan, image) sur un client",
)
async def upload_client_document(
    client_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> ClientDocumentRead:
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client introuvable.")
    ct = (file.content_type or "").lower()
    if ct not in _DOC_MIME_ALLOWED:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Format non supporté (PDF, JPG, PNG, WEBP, HEIC).",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(blob) > _DOC_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Fichier trop gros (> {_DOC_MAX_BYTES // (1024*1024)} Mo).",
        )
    doc = ClientDocument(
        client_id=client_id,
        name=(file.filename or "document").strip()[:255],
        content_type=ct,
        blob=blob,
        source="manual",
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return ClientDocumentRead.model_validate(doc)


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
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Document introuvable."
        )
    return Response(
        content=doc.blob,
        media_type=doc.content_type or "application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc.name}"'
        },
    )
