"""Send confirmation + reminder emails to prospects when an agenda
event is scheduled against their ContactRequest.

Triggered on AgendaEvent create via a small hook in the agenda CRUD
flow (mobile + desktop); a daily cron sends the 24h reminder.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.agenda_event import AgendaEvent
from app.models.contact_request import ContactRequest
from app.models.employe import Employe
from app.services.ics_event import render_event_ics


log = logging.getLogger(__name__)


def _fmt(dt: datetime) -> str:
    # Local-looking format, readable by the prospect.
    return dt.astimezone(timezone.utc).strftime("%A %d %B %Y à %H:%M UTC")


def _body(
    *,
    prospect_name: str,
    event: AgendaEvent,
    when_phrase: str,
    reminder: bool,
) -> str:
    prefix = (
        "Rappel — " if reminder else ""
    )
    loc_line = (
        f"<p style='margin:4px 0'><strong>Lieu :</strong> {event.location}</p>"
        if event.location
        else ""
    )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p>Bonjour {prospect_name},</p>
  <p>{prefix}Nous confirmons notre rendez-vous :</p>
  <div style="padding:12px 16px;background:#f4f1ec;border-left:3px solid #d89b3c;margin:12px 0">
    <p style="margin:0 0 4px 0"><strong>{event.title}</strong></p>
    <p style="margin:4px 0"><strong>Quand :</strong> {when_phrase}</p>
    {loc_line}
  </div>
  <p>Si tu dois modifier ou annuler, réponds simplement à ce courriel.</p>
  <p style="margin-top:24px;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>
    RBQ 5868-5991-01 — info@immohorizon.com
  </p>
</div>
"""


async def send_appointment_confirmation(
    prospect: ContactRequest,
    event: AgendaEvent,
) -> bool:
    mailer = get_mailer()
    if not mailer.ready or not prospect.email:
        return False
    try:
        await mailer.send(
            to=[prospect.email],
            subject=f"Confirmation — {event.title}",
            html_body=_body(
                prospect_name=prospect.name,
                event=event,
                when_phrase=_fmt(event.start_at),
                reminder=False,
            ),
        )
        return True
    except Exception as exc:
        log.exception(
            "Appointment confirmation failed for prospect %s: %s",
            prospect.id,
            exc,
        )
        return False


async def send_appointment_assignee_invite(
    assignee: Employe,
    event: AgendaEvent,
    prospect: Optional[ContactRequest] = None,
) -> bool:
    """Send the assigned employee a calendar invite (.ics attached).

    The .ics contains ORGANIZER + ATTENDEE so Outlook/Gmail/Apple Mail
    offer a native "Add to calendar" button. The employee's calendar
    app keeps a copy so they see the RDV in their own calendar.
    """
    mailer = get_mailer()
    if not mailer.ready or not assignee.email:
        return False
    prospect_block = ""
    if prospect is not None:
        prospect_block = (
            f"<p style='margin:4px 0'><strong>Prospect :</strong> "
            f"{prospect.name}"
            + (f" — {prospect.phone}" if prospect.phone else "")
            + (f" — {prospect.email}" if prospect.email else "")
            + "</p>"
        )
    loc_line = (
        f"<p style='margin:4px 0'><strong>Lieu :</strong> {event.location}</p>"
        if event.location
        else ""
    )
    html = f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p>Bonjour {assignee.full_name.split(' ')[0] or assignee.full_name},</p>
  <p>Tu as été assigné·e à ce rendez-vous :</p>
  <div style="padding:12px 16px;background:#f4f1ec;border-left:3px solid #d89b3c;margin:12px 0">
    <p style="margin:0 0 4px 0"><strong>{event.title}</strong></p>
    <p style="margin:4px 0"><strong>Quand :</strong> {_fmt(event.start_at)}</p>
    {loc_line}
    {prospect_block}
  </div>
  <p>L'invitation est jointe à ce courriel (.ics) — clique dessus pour
  l'ajouter à ton calendrier (Outlook, Gmail, Apple).</p>
  <p style="margin-top:24px;color:#555;font-size:12px">
    Horizon Services Immobiliers
  </p>
</div>
"""
    try:
        ics_bytes = render_event_ics(event, attendee_email=assignee.email)
        await mailer.send(
            to=[assignee.email],
            subject=f"Assignation — {event.title}",
            html_body=html,
            attachments=[
                EmailAttachment(
                    name=f"rdv-{event.id}.ics",
                    content_bytes=ics_bytes,
                    content_type="text/calendar",
                )
            ],
        )
        return True
    except Exception as exc:
        log.exception(
            "Assignee invite failed for employe %s: %s", assignee.id, exc
        )
        return False


async def send_appointment_reminder(
    prospect: ContactRequest,
    event: AgendaEvent,
) -> bool:
    mailer = get_mailer()
    if not mailer.ready or not prospect.email:
        return False
    try:
        await mailer.send(
            to=[prospect.email],
            subject=f"Rappel 24h — {event.title}",
            html_body=_body(
                prospect_name=prospect.name,
                event=event,
                when_phrase=_fmt(event.start_at),
                reminder=True,
            ),
        )
        return True
    except Exception as exc:
        log.exception("Reminder failed: %s", exc)
        return False
