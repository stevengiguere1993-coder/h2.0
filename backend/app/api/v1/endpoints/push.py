"""WebPush — endpoints utilisés par la PWA pour s'enregistrer et
recevoir les notifications push (urgences, SMS, appels manqués).

    GET  /api/v1/push/vapid-public-key  — clé publique VAPID (public)
    POST /api/v1/push/subscribe         — enregistre une subscription
    POST /api/v1/push/unsubscribe       — supprime une subscription
    POST /api/v1/push/test              — envoi de test à l'user
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DBSession
from app.integrations.webpush import push_to_user
from app.models.push_subscription import PushSubscription

log = logging.getLogger(__name__)


router = APIRouter(prefix="/push", tags=["push"])


class VapidKey(BaseModel):
    public_key: Optional[str]
    configured: bool


@router.get(
    "/vapid-public-key",
    response_model=VapidKey,
    summary="Renvoie la clé publique VAPID (utilisée par sw.js pour s'enregistrer)",
)
async def get_vapid_public_key() -> VapidKey:
    pk = os.getenv("VAPID_PUBLIC_KEY", "").strip() or None
    return VapidKey(public_key=pk, configured=bool(pk))


class SubscribePayload(BaseModel):
    endpoint: str = Field(..., min_length=8, max_length=2000)
    keys: dict


@router.post(
    "/subscribe",
    status_code=status.HTTP_201_CREATED,
    summary="Enregistre une PushSubscription pour l'user courant",
)
async def subscribe(
    payload: SubscribePayload,
    user: CurrentUser,
    db: DBSession,
    request: Request,
) -> dict:
    p256dh = (payload.keys or {}).get("p256dh", "")
    auth = (payload.keys or {}).get("auth", "")
    if not p256dh or not auth:
        raise HTTPException(
            status_code=400, detail="keys.p256dh et keys.auth requis"
        )
    # Upsert par endpoint (unique). Si une autre user avait la même
    # subscription (cas rare), on la déplace au user courant.
    existing = (
        await db.execute(
            select(PushSubscription).where(
                PushSubscription.endpoint == payload.endpoint
            )
        )
    ).scalar_one_or_none()
    ua = (request.headers.get("user-agent") or "")[:500]
    if existing is None:
        sub = PushSubscription(
            user_id=user.id,
            endpoint=payload.endpoint,
            p256dh=p256dh[:255],
            auth=auth[:255],
            user_agent=ua,
        )
        db.add(sub)
        await db.flush()
        return {"id": sub.id, "created": True}
    existing.user_id = user.id
    existing.p256dh = p256dh[:255]
    existing.auth = auth[:255]
    existing.user_agent = ua
    existing.last_used_at = datetime.now(timezone.utc)
    await db.flush()
    return {"id": existing.id, "created": False}


class UnsubscribePayload(BaseModel):
    endpoint: str


@router.post(
    "/unsubscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprime une PushSubscription (logout, désactivation, etc.)",
)
async def unsubscribe(
    payload: UnsubscribePayload, user: CurrentUser, db: DBSession
) -> None:
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == payload.endpoint,
            PushSubscription.user_id == user.id,
        )
    )
    await db.flush()


@router.post(
    "/test",
    summary="Envoi de notification de test à l'user courant",
)
async def test_push(user: CurrentUser, db: DBSession) -> dict:
    sent = await push_to_user(
        db,
        user_id=user.id,
        title="✅ Notifications activées",
        body="Vous recevrez désormais les alertes Horizon ici.",
        href="/telephonie",
        tag="test",
    )
    return {"sent": sent}
