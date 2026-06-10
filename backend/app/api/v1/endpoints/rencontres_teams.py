"""Endpoints REST — synchro Teams des Rencontres.

- ``GET  /rencontres/teams-sync/status``  → configuré ? derniers imports,
  ids des fiches importées (badges frontend).
- ``GET  /rencontres/teams-sync/probe``   → diagnostic détaillé (token,
  calendrier, permission onlineMeetings) pour guider la configuration.
- ``POST /rencontres/teams-sync/run``     → lance une passe maintenant.

Le pôle Gestion d'entreprise est déjà réservé owner/admin côté frontend ;
ici on exige un utilisateur connecté, comme le reste des rencontres.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.integrations import ms_graph_meetings as graph
from app.models.teams_meeting_import import TeamsMeetingImport
from app.services.rencontre_teams_sync import sync_teams_meetings

router = APIRouter(prefix="/rencontres/teams-sync", tags=["rencontres"])


class ImportRow(BaseModel):
    subject: Optional[str] = None
    organizer_email: Optional[str] = None
    meeting_start: Optional[str] = None
    status: str
    rencontre_id: Optional[int] = None


class SyncStatus(BaseModel):
    configured: bool
    user_emails: List[str]
    imported_rencontre_ids: List[int]
    recent: List[ImportRow]


@router.get("/status", response_model=SyncStatus)
async def teams_sync_status(db: DBSession, _: CurrentUser) -> SyncStatus:
    rows = (
        await db.execute(
            select(TeamsMeetingImport)
            .order_by(TeamsMeetingImport.id.desc())
            .limit(15)
        )
    ).scalars().all()
    ids = [
        row[0]
        for row in (
            await db.execute(
                select(TeamsMeetingImport.rencontre_id).where(
                    TeamsMeetingImport.rencontre_id.is_not(None)
                )
            )
        ).all()
    ]
    return SyncStatus(
        configured=graph.graph_meetings_configured(),
        user_emails=graph.meeting_user_emails(),
        imported_rencontre_ids=[int(i) for i in ids],
        recent=[
            ImportRow(
                subject=r.subject,
                organizer_email=r.organizer_email,
                meeting_start=r.meeting_start,
                status=r.status,
                rencontre_id=r.rencontre_id,
            )
            for r in rows
        ],
    )


@router.get("/probe")
async def teams_sync_probe(_: CurrentUser) -> dict:
    """Diagnostic maillon par maillon (token / calendrier / meetings)."""
    return await graph.probe()


@router.post("/run")
async def teams_sync_run(db: DBSession, _: CurrentUser) -> dict:
    """Lance une passe de synchro immédiatement (bouton frontend)."""
    result = await sync_teams_meetings(db)
    await db.commit()
    return result
