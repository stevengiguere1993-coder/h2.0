"""Endpoints publics (no auth) — formulaire NPS post-livraison.

Flow client (7 jours après livraison) :

    GET  /api/v1/public/devlog/nps/{token}   -> infos minimales + statut
    POST /api/v1/public/devlog/nps/{token}   -> {score: 0-10, comment?}

Le token est opaque (32 octets URL-safe, généré par le cron
``devlog_nps_dispatch``) et authentifie le destinataire. Idempotent côté
soumission : un second POST sur le même token renvoie ``already_submitted``
sans rien écraser.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.models.devlog_client import DevlogClient
from app.models.devlog_nps_response import DevlogNpsResponse
from app.models.devlog_project import DevlogProject
from app.services.audit import log_action


log = logging.getLogger(__name__)

router = APIRouter(prefix="/public/devlog/nps", tags=["devlog-public"])


class PublicNpsView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_name: str
    client_name: Optional[str] = None
    already_submitted: bool = False


class NpsSubmitRequest(BaseModel):
    score: int = Field(..., ge=0, le=10)
    comment: Optional[str] = Field(default=None, max_length=4000)


class NpsSubmitResponse(BaseModel):
    ok: bool
    already_submitted: bool = False


async def _load_by_token(
    db: AsyncSession, token: str
) -> tuple[DevlogNpsResponse, DevlogProject, Optional[DevlogClient]]:
    nps = (
        await db.execute(
            select(DevlogNpsResponse).where(DevlogNpsResponse.token == token)
        )
    ).scalar_one_or_none()
    if nps is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré."
        )
    project = (
        await db.execute(
            select(DevlogProject).where(DevlogProject.id == nps.project_id)
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable."
        )
    client = None
    if project.client_id is not None:
        client = (
            await db.execute(
                select(DevlogClient).where(DevlogClient.id == project.client_id)
            )
        ).scalar_one_or_none()
    return nps, project, client


@router.get("/{token}", response_model=PublicNpsView)
async def get_nps(token: str, db: DBSession) -> PublicNpsView:
    nps, project, client = await _load_by_token(db, token)
    # Best-effort : marque la première ouverture.
    if nps.opened_at is None:
        nps.opened_at = datetime.now(timezone.utc)
        await db.commit()
    return PublicNpsView(
        project_name=project.name,
        client_name=client.name if client is not None else None,
        already_submitted=nps.submitted_at is not None,
    )


@router.post("/{token}", response_model=NpsSubmitResponse)
async def submit_nps(
    token: str, payload: NpsSubmitRequest, db: DBSession
) -> NpsSubmitResponse:
    nps, project, _ = await _load_by_token(db, token)
    if nps.submitted_at is not None:
        # Idempotent : pas d'écrasement.
        return NpsSubmitResponse(ok=True, already_submitted=True)
    nps.score = int(payload.score)
    nps.comment = (payload.comment or None)
    nps.submitted_at = datetime.now(timezone.utc)
    await log_action(
        db,
        user=None,
        action="devlog_nps.submitted",
        entity_type="devlog_project",
        entity_id=project.id,
        details={
            "nps_response_id": nps.id,
            "score": nps.score,
            "has_comment": bool(nps.comment),
        },
    )
    await db.commit()
    return NpsSubmitResponse(ok=True, already_submitted=False)
