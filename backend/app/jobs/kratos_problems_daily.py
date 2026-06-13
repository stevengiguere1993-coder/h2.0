"""Cron Kratos — détection proactive de problèmes (1×/jour).

Pour chaque entreprise active, demande à Claude 3 à 5 problèmes
concrets avec action suggérée, et persiste dans `kratos_problems`.

Schedule typique : 06:00 Montréal (= 10:00 UTC). On veut que le
dirigeant trouve son tableau de bord rempli au matin.

Usage local :
    python -m app.jobs.kratos_problems_daily
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.entreprise import Entreprise
from app.services.kratos_problem_detector import detect_for_entreprise


log = logging.getLogger(__name__)


async def _run() -> None:
    from app.services.automation_state import is_automation_enabled
    if not await is_automation_enabled("kratos_problems_daily"):
        return
    async with AsyncSessionLocal() as db:
        ents = (
            await db.execute(
                select(Entreprise).where(Entreprise.is_active.is_(True))
            )
        ).scalars().all()
        total = 0
        for ent in ents:
            try:
                created = await detect_for_entreprise(
                    db, ent.id, force=False
                )
                if created:
                    log.info(
                        "Kratos: %d problème(s) détecté(s) pour %s",
                        len(created),
                        ent.name,
                    )
                    total += len(created)
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                log.exception(
                    "Kratos detect_for_entreprise failed for %s: %s",
                    ent.id,
                    exc,
                )
                await db.rollback()
        log.info(
            "Kratos daily scan terminé — %d problème(s) sur %d entreprise(s)",
            total,
            len(ents),
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
