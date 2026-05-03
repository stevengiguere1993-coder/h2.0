"""External calendar subscription (read-only) + per-user availability
blocks painted manually on the Horizon agenda.

We deliberately keep this simple: users paste an .ics URL from their
Google/Outlook/Apple calendar ("Publier le calendrier"), and a cron
job fetches the feed periodically and imports busy blocks into our
DB. These blocks are opaque — we never store titles, locations or
attendees (privacy), only the time range.

On top of that, users can mark time slots as "available" (green
zones) directly in the Horizon UI so managers see when they're
explicitly free for scheduling visits/meetings.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserCalendarFeed(Base):
    """A user-submitted .ics subscription URL. We fetch the feed every
    30 minutes or so and replace the user's ExternalBusyBlock rows
    with a fresh import."""

    __tablename__ = "user_calendar_feeds"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ics_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ExternalBusyBlock(Base):
    """An opaque 'busy' time range pulled from a user's external feed.
    No title, no location — just dates. Rewritten on each sync."""

    __tablename__ = "external_busy_blocks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ics", server_default="ics"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class AvailabilitySlot(Base):
    """A time range the user has flagged as 'available' (green zone)
    for scheduling appointments. Painted via the Horizon UI."""

    __tablename__ = "availability_slots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
