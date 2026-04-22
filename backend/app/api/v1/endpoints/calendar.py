"""Calendar sync + availability endpoints.

    GET    /api/v1/calendar/feed               — my current ICS feed
    PUT    /api/v1/calendar/feed               — set/replace my ICS feed URL
    DELETE /api/v1/calendar/feed               — remove my feed
    POST   /api/v1/calendar/feed/sync          — trigger a fetch now

    GET    /api/v1/calendar/busy               — opaque busy blocks in range
    GET    /api/v1/calendar/availability       — my green zones
    POST   /api/v1/calendar/availability       — add a green zone
    DELETE /api/v1/calendar/availability/{id}  — remove a green zone

    GET    /api/v1/calendar/my-agenda.ics?token=XXX   — public iCal feed
                                                        for external calendar
                                                        app subscriptions
    POST   /api/v1/calendar/my-agenda-url      — (re)generate my feed token
    GET    /api/v1/calendar/my-agenda-url      — fetch my current feed URL

The busy endpoint returns blocks for a user if ?user_id=X is given
(manager+ only), otherwise for the current user. Useful so managers
can pick a slot that overlaps nobody's external calendar.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import is_manager_plus
from app.models.calendar_sync import (
    AvailabilitySlot,
    ExternalBusyBlock,
    UserCalendarFeed,
)
from app.services.ical_sync import sync_user_feed


log = logging.getLogger(__name__)


router = APIRouter(prefix="/calendar", tags=["calendar"])


# ---------- Feed ----------

class FeedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    ics_url: str
    label: Optional[str]
    last_synced_at: Optional[datetime]
    last_sync_error: Optional[str]


class FeedUpdate(BaseModel):
    ics_url: str = Field(..., min_length=1, max_length=2048)
    label: Optional[str] = Field(default=None, max_length=64)


@router.get("/feed", response_model=Optional[FeedRead])
async def get_feed(db: DBSession, user: CurrentUser) -> Optional[FeedRead]:
    row = (
        await db.execute(
            select(UserCalendarFeed).where(UserCalendarFeed.user_id == user.id)
        )
    ).scalar_one_or_none()
    return FeedRead.model_validate(row) if row else None


@router.put("/feed", response_model=FeedRead)
async def set_feed(
    body: FeedUpdate,
    db: DBSession,
    user: CurrentUser,
) -> FeedRead:
    if not (body.ics_url.startswith("http://") or body.ics_url.startswith("https://")):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "URL invalide — doit commencer par http(s)://",
        )
    existing = (
        await db.execute(
            select(UserCalendarFeed).where(UserCalendarFeed.user_id == user.id)
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = UserCalendarFeed(
            user_id=user.id,
            ics_url=body.ics_url.strip(),
            label=(body.label.strip() if body.label else None),
        )
        db.add(existing)
    else:
        existing.ics_url = body.ics_url.strip()
        existing.label = body.label.strip() if body.label else None
        existing.last_sync_error = None
    await db.flush()
    await db.refresh(existing)
    return FeedRead.model_validate(existing)


@router.delete("/feed", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feed(db: DBSession, user: CurrentUser) -> None:
    await db.execute(
        delete(UserCalendarFeed).where(UserCalendarFeed.user_id == user.id)
    )
    await db.execute(
        delete(ExternalBusyBlock).where(
            ExternalBusyBlock.user_id == user.id
        )
    )
    await db.flush()


@router.post("/feed/sync", response_model=FeedRead)
async def sync_now(db: DBSession, user: CurrentUser) -> FeedRead:
    feed = (
        await db.execute(
            select(UserCalendarFeed).where(UserCalendarFeed.user_id == user.id)
        )
    ).scalar_one_or_none()
    if feed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun flux configuré.")
    await sync_user_feed(db, feed)
    await db.refresh(feed)
    return FeedRead.model_validate(feed)


# ---------- Busy blocks (opaque) ----------

class BusyBlock(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    start_at: datetime
    end_at: datetime
    source: str


@router.get("/busy", response_model=List[BusyBlock])
async def list_busy(
    db: DBSession,
    user: CurrentUser,
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
) -> List[BusyBlock]:
    """List busy blocks for the current user, or another user if the
    caller is a manager+ (used by the scheduler)."""
    target_id = user.id
    if user_id is not None and user_id != user.id:
        if not is_manager_plus(user):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Permissions insuffisantes.",
            )
        target_id = user_id

    now = datetime.now(timezone.utc)
    s = start or (now - timedelta(days=7))
    e = end or (now + timedelta(days=60))

    rows = (
        await db.execute(
            select(ExternalBusyBlock)
            .where(
                ExternalBusyBlock.user_id == target_id,
                ExternalBusyBlock.end_at >= s,
                ExternalBusyBlock.start_at <= e,
            )
            .order_by(ExternalBusyBlock.start_at.asc())
        )
    ).scalars().all()
    return [BusyBlock.model_validate(r) for r in rows]


# ---------- Availability (green zones) ----------

class SlotCreate(BaseModel):
    start_at: datetime
    end_at: datetime
    notes: Optional[str] = Field(default=None, max_length=255)


class SlotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    start_at: datetime
    end_at: datetime
    notes: Optional[str]


@router.get("/availability", response_model=List[SlotRead])
async def list_availability(
    db: DBSession,
    user: CurrentUser,
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
) -> List[SlotRead]:
    target_id = user.id
    if user_id is not None and user_id != user.id:
        if not is_manager_plus(user):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Permissions insuffisantes."
            )
        target_id = user_id

    now = datetime.now(timezone.utc)
    s = start or (now - timedelta(days=7))
    e = end or (now + timedelta(days=60))
    rows = (
        await db.execute(
            select(AvailabilitySlot)
            .where(
                AvailabilitySlot.user_id == target_id,
                AvailabilitySlot.end_at >= s,
                AvailabilitySlot.start_at <= e,
            )
            .order_by(AvailabilitySlot.start_at.asc())
        )
    ).scalars().all()
    return [SlotRead.model_validate(r) for r in rows]


@router.post(
    "/availability",
    response_model=SlotRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_availability(
    body: SlotCreate,
    db: DBSession,
    user: CurrentUser,
) -> SlotRead:
    if body.end_at <= body.start_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Plage horaire invalide."
        )
    s = AvailabilitySlot(
        user_id=user.id,
        start_at=body.start_at,
        end_at=body.end_at,
        notes=(body.notes.strip() if body.notes else None),
    )
    db.add(s)
    await db.flush()
    await db.refresh(s)
    return SlotRead.model_validate(s)


@router.delete(
    "/availability/{slot_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_availability(
    slot_id: int, db: DBSession, user: CurrentUser
) -> None:
    s = (
        await db.execute(
            select(AvailabilitySlot).where(AvailabilitySlot.id == slot_id)
        )
    ).scalar_one_or_none()
    if s is None or s.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Créneau introuvable.")
    await db.delete(s)
    await db.flush()


# ---------- Outbound personal ICS feed (subscription URL) ----------

import secrets

from fastapi import Request
from fastapi.responses import Response

from app.models.agenda_event import AgendaEvent
from app.models.employe import Employe
from app.models.user import User
from app.services.ics_event import _escape, _utc


class FeedUrlRead(BaseModel):
    url: str
    token: str


@router.get("/my-agenda-url", response_model=FeedUrlRead)
async def get_my_agenda_url(
    request: Request, db: DBSession, user: CurrentUser
) -> FeedUrlRead:
    """Return (or lazily generate) the user's personal ICS feed URL.

    The URL embeds a long-lived secret token so external calendar apps
    (Google, Apple, Outlook) can subscribe without an OAuth flow.
    """
    u = (
        await db.execute(select(User).where(User.id == user.id))
    ).scalar_one()
    if not u.calendar_feed_token:
        u.calendar_feed_token = secrets.token_urlsafe(32)
        await db.flush()
    base = str(request.base_url).rstrip("/")
    return FeedUrlRead(
        url=f"{base}/api/v1/calendar/my-agenda.ics?token={u.calendar_feed_token}",
        token=u.calendar_feed_token,
    )


@router.post("/my-agenda-url", response_model=FeedUrlRead)
async def rotate_my_agenda_url(
    request: Request, db: DBSession, user: CurrentUser
) -> FeedUrlRead:
    """Rotate the user's feed token — invalidates every previous
    subscription URL. Use when a device is lost or the URL leaked."""
    u = (
        await db.execute(select(User).where(User.id == user.id))
    ).scalar_one()
    u.calendar_feed_token = secrets.token_urlsafe(32)
    await db.flush()
    base = str(request.base_url).rstrip("/")
    return FeedUrlRead(
        url=f"{base}/api/v1/calendar/my-agenda.ics?token={u.calendar_feed_token}",
        token=u.calendar_feed_token,
    )


@router.get("/my-agenda.ics")
async def my_agenda_ics(
    db: DBSession, token: str = Query(..., min_length=16)
) -> Response:
    """Public ICS feed. Returns all AgendaEvents assigned to the user
    whose `calendar_feed_token` matches the query string.

    We match the User → Employe via email (users.email == employes.email)
    because AgendaEvent.assignee_id points at `employes`, not `users`.
    This is how external calendar apps will continuously poll the user's
    agenda without re-authenticating.
    """
    u = (
        await db.execute(
            select(User).where(User.calendar_feed_token == token)
        )
    ).scalar_one_or_none()
    if u is None:
        # 404 instead of 401 so scrapers don't learn anything
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feed not found.")

    emp = None
    if u.email:
        emp = (
            await db.execute(select(Employe).where(Employe.email == u.email))
        ).scalar_one_or_none()

    events: list[AgendaEvent] = []
    if emp is not None:
        events = list(
            (
                await db.execute(
                    select(AgendaEvent)
                    .where(AgendaEvent.assignee_id == emp.id)
                    .order_by(AgendaEvent.start_at.asc())
                )
            ).scalars().all()
        )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Horizon Services Immobiliers//Agenda Personnel//FR",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Horizon — Mon agenda",
        "X-WR-TIMEZONE:America/Montreal",
    ]
    now = datetime.now(timezone.utc)
    for ev in events:
        end = ev.end_at or ev.start_at
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:agenda-{ev.id}@immohorizon.com",
                f"DTSTAMP:{_utc(now)}",
                f"DTSTART:{_utc(ev.start_at)}",
                f"DTEND:{_utc(end)}",
                f"SUMMARY:{_escape(ev.title)}",
            ]
        )
        if ev.location:
            lines.append(f"LOCATION:{_escape(ev.location)}")
        if ev.description:
            lines.append(f"DESCRIPTION:{_escape(ev.description)}")
        lines.extend(["STATUS:CONFIRMED", "END:VEVENT"])
    lines.append("END:VCALENDAR")

    body = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            # Short cache so subscribers re-pull within minutes
            "Cache-Control": "public, max-age=300",
        },
    )
