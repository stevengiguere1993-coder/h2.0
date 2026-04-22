"""Cron: send 24h-before reminders for agenda events tied to a
prospect. Runs hourly so the "24h window" is roughly honored.

    python -m app.jobs.appointment_reminders
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.agenda_event import AgendaEvent
from app.models.contact_request import ContactRequest
from app.services.appointment_mail import send_appointment_reminder


log = logging.getLogger(__name__)


async def run() -> None:
    now = datetime.now(timezone.utc)
    # Send reminders for events starting in the next ~25 hours, that
    # haven't been reminded yet. The hourly cadence gives us a natural
    # ~1h imprecision which is fine for a "day-before" reminder.
    window_end = now + timedelta(hours=25)

    async with AsyncSessionLocal() as db:
        stmt = (
            select(AgendaEvent)
            .where(
                AgendaEvent.contact_request_id.is_not(None),
                AgendaEvent.start_at >= now,
                AgendaEvent.start_at <= window_end,
                AgendaEvent.reminder_sent_at.is_(None),
            )
            .limit(200)
        )
        events = (await db.execute(stmt)).scalars().all()
        sent = 0
        for ev in events:
            pr = (
                await db.execute(
                    select(ContactRequest).where(
                        ContactRequest.id == ev.contact_request_id
                    )
                )
            ).scalar_one_or_none()
            if pr is None:
                continue
            ok = await send_appointment_reminder(pr, ev)
            if ok:
                ev.reminder_sent_at = datetime.now(timezone.utc)
                sent += 1
        await db.commit()
        log.info("appointment reminders: %s sent", sent)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
