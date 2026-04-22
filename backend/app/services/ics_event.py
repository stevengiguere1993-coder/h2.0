"""Generate a single-event .ics (RFC 5545) for an AgendaEvent.

Deux usages:
 - Joindre l'invitation au courriel envoyé à l'employé assigné, pour
   qu'il puisse cliquer « Ajouter au calendrier » depuis Outlook,
   Gmail, Apple Mail, etc.
 - Futur: exposer un feed personnel (VCALENDAR avec plusieurs VEVENT)
   dans /api/v1/calendar/agenda.ics pour un abonnement continu.

On garde l'implémentation volontairement simple — pas de VTIMEZONE,
on convertit tout en UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.models.agenda_event import AgendaEvent


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    # RFC 5545 §3.3.11: escape \ ; , and newlines.
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def render_event_ics(
    event: AgendaEvent,
    *,
    organizer_email: str = "info@immohorizon.com",
    attendee_email: Optional[str] = None,
) -> bytes:
    """Render a single VEVENT wrapped in a VCALENDAR."""
    end = event.end_at or event.start_at
    uid = f"agenda-{event.id}@immohorizon.com"
    now = datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Horizon Services Immobiliers//Agenda//FR",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_utc(now)}",
        f"DTSTART:{_utc(event.start_at)}",
        f"DTEND:{_utc(end)}",
        f"SUMMARY:{_escape(event.title)}",
    ]
    if event.location:
        lines.append(f"LOCATION:{_escape(event.location)}")
    if event.description:
        lines.append(f"DESCRIPTION:{_escape(event.description)}")
    lines.append(f"ORGANIZER:mailto:{organizer_email}")
    if attendee_email:
        lines.append(
            f"ATTENDEE;RSVP=FALSE;PARTSTAT=NEEDS-ACTION:mailto:{attendee_email}"
        )
    lines.extend(
        [
            "STATUS:CONFIRMED",
            "TRANSP:OPAQUE",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    # RFC 5545 requires CRLF line endings.
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")
