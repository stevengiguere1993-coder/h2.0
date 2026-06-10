"""Job cron — synchro des rencontres Teams → fiches Rencontres.

Déclenché par GitHub Actions (workflow ``teams-meeting-sync.yml``,
plusieurs fois par jour) via ``POST /api/v1/cron/run/teams-meeting-sync``.
No-op silencieux si la synchro n'est pas configurée
(TEAMS_MEETING_USER_EMAILS vide).
"""

from __future__ import annotations

import logging

from app.db.session import AsyncSessionLocal
from app.services.rencontre_teams_sync import sync_teams_meetings

log = logging.getLogger(__name__)


async def _run() -> None:
    async with AsyncSessionLocal() as db:
        result = await sync_teams_meetings(db)
        await db.commit()
    if not result.get("configured"):
        log.info("teams-meeting-sync : non configuré — no-op")
        return
    log.info(
        "teams-meeting-sync : %d importée(s), %d sans transcription, "
        "%d en attente, %d déjà connue(s), erreurs=%s",
        len(result.get("imported") or []),
        result.get("no_transcript", 0),
        result.get("pending", 0),
        result.get("skipped_known", 0),
        result.get("errors") or "aucune",
    )
