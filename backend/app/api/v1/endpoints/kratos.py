"""Endpoints Kratos — routeur d'intentions + inbox.

  POST /api/v1/kratos/route        — soumet un texte, route + inbox entry
  GET  /api/v1/kratos/inbox        — liste paginée des entrées récentes
  POST /api/v1/kratos/{id}/confirm — applique manuellement un routage
                                     (cas needs_review)
  POST /api/v1/kratos/{id}/discard — marque un message comme rejeté
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.kratos_message import (
    KratosIntentKind,
    KratosMessage,
    KratosMessageStatus,
)
from app.services.kratos_router import route_text


log = logging.getLogger(__name__)

router = APIRouter(prefix="/kratos", tags=["kratos"])


class KratosRouteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000)


class KratosMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: Optional[int]
    original_text: str
    intent_kind: str
    summary: Optional[str]
    target_type: Optional[str]
    target_id: Optional[int]
    status: str
    intent_json: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]


@router.post(
    "/route",
    response_model=KratosMessageRead,
    summary="Route une entrée vers le bon endroit via Claude",
)
async def route(
    data: KratosRouteRequest,
    db: DBSession,
    user: CurrentUser,
) -> KratosMessageRead:
    try:
        msg = await route_text(db, user, data.text)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Kratos /route failed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"kratos_route_failed: {type(exc).__name__}",
        ) from exc
    await db.commit()
    return KratosMessageRead.model_validate(msg)


@router.get(
    "/inbox",
    response_model=List[KratosMessageRead],
    summary="Inbox Kratos — liste paginée des entrées récentes",
)
async def inbox(
    db: DBSession,
    user: CurrentUser,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> List[KratosMessageRead]:
    stmt = (
        select(KratosMessage)
        .order_by(KratosMessage.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(KratosMessage.status == status_filter)
    # Pour l'instant, chaque user voit ses propres messages OU les
    # messages système (user_id NULL). Les admins voient tout.
    if (getattr(user, "role", "") or "").lower() not in ("owner", "admin"):
        stmt = stmt.where(
            (KratosMessage.user_id == user.id)
            | (KratosMessage.user_id.is_(None))
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [KratosMessageRead.model_validate(r) for r in rows]


@router.post(
    "/{msg_id}/discard",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Rejeter un message (manual discard)",
)
async def discard(
    msg_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    msg = (
        await db.execute(
            select(KratosMessage).where(KratosMessage.id == msg_id)
        )
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message introuvable.")
    msg.status = KratosMessageStatus.DISCARDED.value
    await db.commit()


class ConfirmRequest(BaseModel):
    """Manual override d'un routage. Pour l'instant on supporte juste
    le ré-attachement à une entité explicite (entreprise_id, lead_id…).
    Phase 2+ : ré-router complètement."""

    target_type: str = Field(..., max_length=48)
    target_id: int


@router.post(
    "/{msg_id}/confirm",
    response_model=KratosMessageRead,
    summary="Confirmer manuellement le routage d'un message",
)
async def confirm(
    msg_id: int,
    data: ConfirmRequest,
    db: DBSession,
    _: CurrentUser,
) -> KratosMessageRead:
    msg = (
        await db.execute(
            select(KratosMessage).where(KratosMessage.id == msg_id)
        )
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message introuvable.")
    msg.target_type = data.target_type
    msg.target_id = data.target_id
    msg.status = KratosMessageStatus.ROUTED.value
    await db.commit()
    await db.refresh(msg)
    return KratosMessageRead.model_validate(msg)
