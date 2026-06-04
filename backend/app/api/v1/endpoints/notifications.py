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
from sqlalchemy import and_, func, or_, select, update

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


# Préfixes de href par volet. Sert à cloisonner la cloche : une
# notification dont le href cible explicitement un AUTRE volet
# n'apparaît pas (ex. un NDA signé — href /prospection/… — ne doit
# pas s'afficher dans la cloche du volet construction /app).
_VOLET_PREFIXES: dict[str, tuple[str, ...]] = {
    "construction": ("/app", "/m"),
    "prospection": ("/prospection",),
    "immobilier": ("/immobilier",),
    "entreprises": ("/entreprises",),
    "devlog": ("/dev-logiciel",),
}

# Certaines notifications appartiennent à un volet de façon non ambiguë,
# peu importe leur href (qui peut être nul sur d'anciennes notifs, ou
# pointer vers un autre volet pour des raisons de routage historique).
# On les rattache par `kind` pour cloisonner la cloche de façon fiable —
# ex. « NDA signé » est de la prospection et ne doit jamais apparaître
# dans la cloche du volet construction.
_KIND_VOLET: dict[str, str] = {
    "nda.signed": "prospection",
}


def _volet_filter(scope: Optional[str]):
    """Condition SQL ne gardant que les notifications du volet `scope`.

    Une notification est conservée si son href est nul, appartient au
    volet demandé, ou ne correspond à aucun volet connu. Elle est
    écartée si son href vise explicitement un autre volet, ou si son
    `kind` est rattaché à un autre volet.
    Retourne ``None`` si `scope` est absent/inconnu (aucun filtre).
    """
    if not scope or scope not in _VOLET_PREFIXES:
        return None
    conditions = []
    foreign = [
        pfx
        for volet, prefixes in _VOLET_PREFIXES.items()
        if volet != scope
        for pfx in prefixes
    ]
    if foreign:
        conditions.append(
            or_(
                Notification.href.is_(None),
                ~or_(*[Notification.href.like(f"{p}%") for p in foreign]),
            )
        )
    foreign_kinds = [k for k, volet in _KIND_VOLET.items() if volet != scope]
    if foreign_kinds:
        conditions.append(Notification.kind.notin_(foreign_kinds))
    if not conditions:
        return None
    return and_(*conditions)


@router.get("", response_model=List[NotificationRead])
async def list_notifications(
    db: DBSession,
    user: CurrentUser,
    limit: int = Query(default=30, ge=1, le=100),
    only_unread: bool = Query(default=False),
    scope: Optional[str] = Query(default=None),
) -> List[NotificationRead]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if only_unread:
        stmt = stmt.where(Notification.is_read.is_(False))
    clause = _volet_filter(scope)
    if clause is not None:
        stmt = stmt.where(clause)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [NotificationRead.model_validate(r) for r in rows]


@router.get("/unread-count")
async def unread_count(
    db: DBSession,
    user: CurrentUser,
    scope: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
) -> int:
    stmt = select(func.count(Notification.id)).where(
        Notification.user_id == user.id,
        Notification.is_read.is_(False),
    )
    if kind:
        # Filtre par type (ex. voicemail_received) — sert aux badges
        # ciblés dans les menus latéraux.
        stmt = stmt.where(Notification.kind == kind)
    clause = _volet_filter(scope)
    if clause is not None:
        stmt = stmt.where(clause)
    n = (await db.execute(stmt)).scalar_one()
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
