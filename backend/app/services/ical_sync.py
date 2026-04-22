"""Minimal iCalendar (.ics) feed import.

We ONLY care about event date ranges — titles, attendees, locations
are deliberately ignored so we respect user privacy (the PWA displays
"Indisponible" for these blocks, never the original content).

The iCalendar spec is huge; we implement just enough to handle the
feeds Google Calendar, Outlook, and Apple iCloud publish:
 - VEVENT boundaries
 - DTSTART / DTEND with optional ;TZID=
 - DTSTART;VALUE=DATE for all-day events
 - Basic line folding (a leading space/tab continues the previous line)

Anything unrecognized is silently skipped — a valid "subset" is far
better than blowing up on an edge case.
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_sync import ExternalBusyBlock, UserCalendarFeed


log = logging.getLogger(__name__)


_DT_BASIC = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)$")
_DATE_ONLY = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def _parse_dt(raw: str) -> Optional[datetime]:
    """Accept "20260413T143000Z", "20260413T143000", "20260413" (all-day)."""
    raw = raw.strip()
    if not raw:
        return None
    m = _DT_BASIC.match(raw)
    if m:
        y, mo, d, h, mi, s, z = m.groups()
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
        # Assume UTC if trailing Z, otherwise local — the iCalendar spec
        # says "floating" local time without TZID. We treat floating as
        # UTC too to avoid timezone db complexity; slight inaccuracy is
        # acceptable for opaque busy blocks.
        return dt.replace(tzinfo=timezone.utc)
    m = _DATE_ONLY.match(raw)
    if m:
        y, mo, d = m.groups()
        return datetime(int(y), int(mo), int(d), tzinfo=timezone.utc)
    return None


def _unfold(lines: Iterable[str]) -> list[str]:
    """Join continuation lines (leading space/tab) into their parent."""
    out: list[str] = []
    for line in lines:
        if (line.startswith(" ") or line.startswith("\t")) and out:
            out[-1] += line[1:].rstrip("\r\n")
        else:
            out.append(line.rstrip("\r\n"))
    return out


def parse_events(ics: str) -> list[tuple[datetime, datetime]]:
    """Return (start, end) tuples for each VEVENT, both UTC."""
    lines = _unfold(ics.splitlines())
    events: list[tuple[datetime, datetime]] = []
    in_event = False
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    start_is_date = False
    for raw in lines:
        if raw == "BEGIN:VEVENT":
            in_event, start, end, start_is_date = True, None, None, False
            continue
        if raw == "END:VEVENT":
            if start:
                # All-day: iCal convention says DTEND is exclusive and
                # omitted DTEND defaults to DTSTART + 1 day.
                if end is None:
                    end = start + timedelta(days=1 if start_is_date else 0)
                if end > start:
                    events.append((start, end))
            in_event = False
            continue
        if not in_event:
            continue
        # Only look at DTSTART / DTEND. Strip parameters (e.g. TZID=).
        if raw.startswith("DTSTART"):
            value = raw.split(":", 1)[1] if ":" in raw else ""
            start = _parse_dt(value)
            start_is_date = bool(_DATE_ONLY.match(value.strip()))
        elif raw.startswith("DTEND"):
            value = raw.split(":", 1)[1] if ":" in raw else ""
            end = _parse_dt(value)
    return events


async def _fetch_url(url: str, timeout: float = 10.0) -> str:
    """HTTP GET with a forgiving TLS context (some calendar feeds use
    slightly old chain bundles)."""

    def _blocking() -> str:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            url, headers={"User-Agent": "HorizonCalendarSync/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            data = r.read(5 * 1024 * 1024)  # hard cap 5 MB
        return data.decode("utf-8", errors="replace")

    return await asyncio.to_thread(_blocking)


async def sync_user_feed(
    db: AsyncSession, feed: UserCalendarFeed
) -> int:
    """Fetch + parse + replace ExternalBusyBlock rows for this feed.
    Returns the number of blocks persisted."""
    try:
        ics = await _fetch_url(feed.ics_url)
    except Exception as exc:
        feed.last_sync_error = f"Fetch error: {exc}"[:2000]
        log.warning(
            "iCal fetch failed for user %s: %s", feed.user_id, exc
        )
        await db.flush()
        return 0

    try:
        events = parse_events(ics)
    except Exception as exc:
        feed.last_sync_error = f"Parse error: {exc}"[:2000]
        await db.flush()
        return 0

    # Only keep events in a reasonable window (past 30d → future 180d)
    # to keep the table small. Anything older/further is dropped.
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=30)
    window_end = now + timedelta(days=180)
    clean = [
        (s, e)
        for (s, e) in events
        if e >= window_start and s <= window_end
    ]

    # Wipe + reinsert — small rowcounts make this safe and simple.
    await db.execute(
        delete(ExternalBusyBlock).where(
            ExternalBusyBlock.user_id == feed.user_id
        )
    )
    for (s, e) in clean:
        db.add(
            ExternalBusyBlock(
                user_id=feed.user_id,
                start_at=s,
                end_at=e,
                source="ics",
            )
        )
    feed.last_synced_at = now
    feed.last_sync_error = None
    await db.flush()
    return len(clean)
