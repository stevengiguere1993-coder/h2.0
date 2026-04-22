"""In-app notifications — cloche 🔔 du topbar.

    GET    /api/v1/notifications           — liste (unread d'abord)
    GET    /api/v1/notifications/unread-count
    POST   /api/v1/notifications/{id}/read
    POST   /api/v1/notifications/read-all
    DELETE /api/v1/notifications/{id}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DBSession
from app.models.notification import Notification


router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    title: str
    body: Optional[str]
    href: Optional[str]
    is_read: bool
    created_at: datetime


@router.get("", response_model=List[NotificationRead])
async def list_notifications(
    db: DBSession,
    user: CurrentUser,
    limit: int = Query(default=30, ge=1, le=100),
    only_unread: bool = Query(default=False),
) -> List[NotificationRead]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if only_unread:
        stmt = stmt.where(Notification.is_read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [NotificationRead.model_validate(r) for r in rows]


@router.get("/unread-count")
async def unread_count(db: DBSession, user: CurrentUser) -> int:
    n = (
        await db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.is_read.is_(False),
            )
        )
    ).scalar_one()
    return int(n or 0)


@router.post("/{nid}/read", response_model=NotificationRead)
async def mark_read(
    nid: int, db: DBSession, user: CurrentUser
) -> NotificationRead:
    n = (
        await db.execute(
            select(Notification).where(
                Notification.id == nid, Notification.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification introuvable.")
    n.is_read = True
    n.read_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(n)
    return NotificationRead.model_validate(n)


@router.post("/read-all")
async def mark_all_read(db: DBSession, user: CurrentUser) -> dict:
    res = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True, read_at=datetime.now(timezone.utc))
    )
    await db.flush()
    return {"updated": res.rowcount or 0}


@router.delete("/{nid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    nid: int, db: DBSession, user: CurrentUser
) -> None:
    n = (
        await db.execute(
            select(Notification).where(
                Notification.id == nid, Notification.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification introuvable.")
    await db.delete(n)
    await db.flush()
