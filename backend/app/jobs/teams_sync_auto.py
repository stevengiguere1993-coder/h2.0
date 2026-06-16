"""Cron : synchro AUTOMATIQUE des rencontres Teams.

Récupère les transcriptions Teams publiées et crée/complète les fiches
Rencontre, sans aucune intervention. À planifier toutes les heures sur
Render — c'est ce qui rend la capture « tout automatique » côté Kratos
(à condition que la config Microsoft soit en place : application access
policy + permissions Graph + transcription activée).

Idempotent : ``sync_teams_meetings`` dédoublonne via TeamsMeetingImport,
donc relancer souvent ne crée pas de doublons.

Usage (Render cron) :
    python -m app.jobs.teams_sync_auto
"""

from __future__ import annotations

import asyncio
import logging

from app.db.session import AsyncSessionLocal
from app.services.rencontre_teams_sync import sync_teams_meetings


log = logging.getLogger(__name__)


async def _run() -> None:
    async with AsyncSessionLocal() as db:
        try:
            result = await sync_teams_meetings(db)
        except Exception as exc:  # noqa: BLE001
            log.warning("teams auto-sync failed: %s", exc)
            return
        imported = result.get("imported") or []
        log.info(
            "teams auto-sync: %d importée(s), %d en attente, %d armée(s)",
            len(imported),
            result.get("pending", 0),
            result.get("auto_transcription_enabled", 0),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())
