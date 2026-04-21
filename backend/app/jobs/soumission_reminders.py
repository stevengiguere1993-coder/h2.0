"""Daily cron: nudge clients on soumissions that were sent but have
received no response after N days.

For every Soumission with status="sent" and sent_at older than
SOUMISSION_REMINDER_DAYS (default 5 days), send a friendly reminder
via Microsoft Graph once. We track this via `last_reminder_at` so we
don't spam the client on every cron run.

Usage (Render cron):
    python -m app.jobs.soumission_reminders
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.integrations.email_graph import get_mailer
from app.models.contact_request import ContactRequest
from app.models.soumission import Soumission, SoumissionStatus


log = logging.getLogger(__name__)


DEFAULT_REMINDER_DAYS = 5
REMINDER_DAYS = int(
    os.environ.get("SOUMISSION_REMINDER_DAYS", DEFAULT_REMINDER_DAYS)
)


async def _recipient_for(soumission: Soumission, db) -> Optional[str]:
    if soumission.contact_request_id:
        cr = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == soumission.contact_request_id
                )
            )
        ).scalar_one_or_none()
        if cr and cr.email:
            return cr.email
    # We could also lookup Client.email here, but the soumission wasn't
    # necessarily tied to a Client at send time.
    return None


def _body_html(sm: Soumission, total: Optional[float]) -> str:
    total_line = (
        f"<p><strong>Total :</strong> {float(total):,.2f} $ CAD</p>".replace(
            ",", " "
        )
        if total is not None
        else ""
    )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5">
  <p>Bonjour,</p>
  <p>Un petit rappel amical concernant la soumission <strong>{sm.reference}</strong> —
     {sm.title} — que nous vous avons envoyée récemment.</p>
  {total_line}
  <p>Si vous avez des questions ou souhaitez ajuster le contenu, répondez à ce
  courriel — nous nous ferons un plaisir de vous accompagner.</p>
  <p style="margin-top:20px;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>
    RBQ 5868-5991-01 — info@immohorizon.com
  </p>
</div>
"""


async def run() -> None:
    mailer = get_mailer()
    if not mailer.ready:
        log.warning(
            "Graph mailer not configured — soumission reminders skipped."
        )
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=REMINDER_DAYS)

    async with AsyncSessionLocal() as db:
        try:
            rows = (
                await db.execute(
                    select(Soumission).where(
                        Soumission.status == SoumissionStatus.SENT.value,
                        Soumission.sent_at.is_not(None),
                        Soumission.sent_at <= cutoff,
                    )
                )
            ).scalars().all()
            sent = 0
            for sm in rows:
                # One reminder max, gated via `notes` trail (no dedicated
                # column on Soumission yet). We stamp the note once.
                trail_marker = "[relance auto]"
                if sm.notes and trail_marker in sm.notes:
                    continue
                to = await _recipient_for(sm, db)
                if not to:
                    continue
                try:
                    await mailer.send(
                        to=[to],
                        subject=f"Rappel — Soumission {sm.reference}",
                        html_body=_body_html(sm, sm.total),
                    )
                    ts = datetime.now(timezone.utc).isoformat(timespec="minutes")
                    note = f"{trail_marker} {ts} → {to}"
                    sm.notes = f"{sm.notes}\n{note}" if sm.notes else note
                    sent += 1
                except Exception as exc:
                    log.exception(
                        "Failed to send reminder for soumission %s: %s",
                        sm.reference,
                        exc,
                    )
            await db.commit()
            log.info("soumission reminders: %s sent", sent)
        except Exception:
            await db.rollback()
            raise


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
