"""Cron: rappels (au moins ~24 h à l'avance) pour les événements
d'agenda liés à un prospect.

⚠ Ce job est lancé **une fois par jour** par le mega-cron
(`cron_runner` / cron-job.org). Avec une exécution quotidienne, une
fenêtre « +24 h » est insuffisante : un RDV en matinée plus tard que
l'heure du cron n'entre dans la fenêtre que le matin même → préavis de
quelques heures (bug observé : ~8 h au lieu de 24 h).

On utilise donc une fenêtre de **48 h** : combinée au run quotidien et à
la déduplication (`reminder_sent_at`), chaque RDV est rappelé une seule
fois, **entre 24 h et 48 h avant — jamais moins de 24 h**. (Si le job
repassait à un cadencement horaire, réduire la fenêtre à ~25 h pour
viser ~24 h pile.)

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
    # Fenêtre de 48 h (cf. docstring) : avec un cron quotidien, ça garantit
    # un préavis ≥ 24 h pour tout RDV, peu importe l'heure de la journée.
    # La déduplication via reminder_sent_at évite tout doublon.
    window_end = now + timedelta(hours=48)

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
