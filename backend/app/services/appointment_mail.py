"""Send confirmation + reminder emails to prospects when an agenda
event is scheduled against their ContactRequest.

Triggered on AgendaEvent create via a small hook in the agenda CRUD
flow (mobile + desktop); a daily cron sends the 24h reminder.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.agenda_event import AgendaEvent
from app.models.contact_request import ContactRequest
from app.models.employe import Employe
from app.services.ics_event import render_event_ics


log = logging.getLogger(__name__)

# Les rendez-vous sont dans l'Est (Montréal). Les datetimes en base sont
# en UTC ; on les convertit ici pour l'affichage client.
_APPT_TZ = ZoneInfo("America/Toronto")  # = heure de Montréal (Est)
_FR_JOURS = (
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
)
_FR_MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
    "août", "septembre", "octobre", "novembre", "décembre",
)


def _fmt(dt: datetime) -> str:
    """Date + heure du RV en français, à l'heure de Montréal.

    Ex. « dimanche 7 juin 2026 à 9 h 00 (heure de Montréal) ». On
    n'utilise pas strftime pour les noms (locale C = anglais sur le
    serveur) : on mappe jours/mois à la main."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(_APPT_TZ)
    jour = _FR_JOURS[local.weekday()]
    mois = _FR_MOIS[local.month - 1]
    heure = f"{local.hour} h {local.minute:02d}"
    return (
        f"{jour} {local.day} {mois} {local.year} "
        f"à {heure} (heure de Montréal)"
    )


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
    ics_line = (
        ""
        if reminder
        else "<p>Une invitation calendrier (.ics) est jointe à ce courriel — "
        "clique dessus pour ajouter le rendez-vous à ton agenda "
        "(Outlook, Google, Apple).</p>"
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
  {ics_line}
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
    """Email de confirmation au prospect avec .ics joint.

    Le .ics contient ORGANIZER + ATTENDEE pour que Outlook / Gmail /
    Apple Mail proposent un bouton natif « Ajouter au calendrier ».
    """
    mailer = get_mailer()
    if not mailer.ready or not prospect.email:
        return False
    try:
        ics_bytes = render_event_ics(event, attendee_email=prospect.email)
        await mailer.send(
            to=[prospect.email],
            subject=f"Confirmation — {event.title}",
            html_body=_body(
                prospect_name=prospect.name,
                event=event,
                when_phrase=_fmt(event.start_at),
                reminder=False,
            ),
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


async def send_appointment_owner_invite(
    owner_email: str,
    event: AgendaEvent,
    prospect: Optional[ContactRequest] = None,
) -> bool:
    """Invitation calendrier (.ics) vers l'adresse « agenda » du
    propriétaire, pour CHAQUE RDV prospect — même non assigné — afin
    qu'il atterrisse toujours dans son agenda.

    Distinct de l'invite à l'employé assigné : ici le destinataire est
    une boîte fixe (settings.appointment_owner_email). On garde un .ics
    avec ORGANIZER + ATTENDEE pour le bouton natif « Ajouter au
    calendrier ».
    """
    mailer = get_mailer()
    owner_email = (owner_email or "").strip()
    if not mailer.ready or not owner_email:
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
  <p>Un rendez-vous prospect a été planifié :</p>
  <div style="padding:12px 16px;background:#f4f1ec;border-left:3px solid #d89b3c;margin:12px 0">
    <p style="margin:0 0 4px 0"><strong>{event.title}</strong></p>
    <p style="margin:4px 0"><strong>Quand :</strong> {_fmt(event.start_at)}</p>
    {loc_line}
    {prospect_block}
  </div>
  <p>L'invitation est jointe à ce courriel (.ics) — clique dessus pour
  l'ajouter à ton agenda (Outlook, Gmail, Apple).</p>
  <p style="margin-top:24px;color:#555;font-size:12px">
    Horizon Services Immobiliers
  </p>
</div>
"""
    try:
        # PUBLISH (et non REQUEST) : la boîte agenda est une boîte interne
        # Microsoft 365 ; un .ics REQUEST y serait auto-traité par Exchange
        # (ajouté au calendrier + courriel retiré de la réception). PUBLISH
        # arrive comme un vrai courriel avec le .ics « ajouter à l'agenda ».
        ics_bytes = render_event_ics(
            event, attendee_email=owner_email, method="PUBLISH"
        )
        await mailer.send(
            to=[owner_email],
            subject=f"RDV agenda — {event.title}",
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
            "Owner agenda invite failed for %s: %s", owner_email, exc
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
            subject=f"Rappel — {event.title}",
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
