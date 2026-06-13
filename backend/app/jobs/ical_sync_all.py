"""Cron: refresh every user's iCal feed. Runs every 30 minutes.

    python -m app.jobs.ical_sync_all
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.calendar_sync import UserCalendarFeed
from app.services.ical_sync import sync_user_feed


log = logging.getLogger(__name__)


async def run() -> None:
    from app.services.automation_state import is_automation_enabled
    if not await is_automation_enabled("ical_sync_all"):
        return
    async with AsyncSessionLocal() as db:
        feeds = (
            await db.execute(select(UserCalendarFeed))
        ).scalars().all()
        total_blocks = 0
        ok = 0
        for f in feeds:
            try:
                n = await sync_user_feed(db, f)
                total_blocks += n
                ok += 1
            except Exception:
                log.exception("Sync failed for user %s", f.user_id)
        await db.commit()
        log.info(
            "iCal sync: %s feeds synced (of %s), %s busy blocks",
            ok,
            len(feeds),
            total_blocks,
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
