"""Project phases — ordered stages of a project with a start date
and a duration in days. Tasks can be nested inside a phase via
ProjectTask.phase_id.

    GET    /api/v1/projects/{project_id}/phases
    POST   /api/v1/projects/{project_id}/phases
    PATCH  /api/v1/projects/{project_id}/phases/{phase_id}
    DELETE /api/v1/projects/{project_id}/phases/{phase_id}
    PUT    /api/v1/projects/{project_id}/phases/reorder  (bulk reorder)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_project_ids
from app.models.project import Project
from app.models.project_phase import ProjectPhase


router = APIRouter(prefix="/projects", tags=["project-phases"])


class PhaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    position: int = Field(default=0, ge=0)
    start_date: Optional[date] = None
    duration_days: Optional[int] = Field(default=None, ge=0, le=3650)
    notes: Optional[str] = None
    assignee_employe_id: Optional[int] = Field(default=None, gt=0)
    assignee_sous_traitant_id: Optional[int] = Field(default=None, gt=0)


class PhaseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    position: Optional[int] = Field(default=None, ge=0)
    start_date: Optional[date] = None
    duration_days: Optional[int] = Field(default=None, ge=0, le=3650)
    notes: Optional[str] = None
    assignee_employe_id: Optional[int] = None
    assignee_sous_traitant_id: Optional[int] = None


class PhaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    name: str
    position: int
    start_date: Optional[date]
    duration_days: Optional[int]
    notes: Optional[str]
    assignee_employe_id: Optional[int] = None
    assignee_sous_traitant_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class ReorderBody(BaseModel):
    phase_ids: List[int]


async def _ensure_project_visible(
    db, project_id: int, user
) -> Project:
    visible = await visible_project_ids(db, user)
    if visible is not None and project_id not in visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    p = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


@router.get(
    "/{project_id}/phases",
    response_model=List[PhaseRead],
)
async def list_phases(
    project_id: int, db: DBSession, user: CurrentUser
) -> List[PhaseRead]:
    await _ensure_project_visible(db, project_id, user)
    rows = (
        await db.execute(
            select(ProjectPhase)
            .where(ProjectPhase.project_id == project_id)
            .order_by(ProjectPhase.position.asc(), ProjectPhase.id.asc())
        )
    ).scalars().all()
    return [PhaseRead.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/phases",
    response_model=PhaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_phase(
    project_id: int,
    data: PhaseCreate,
    db: DBSession,
    user: CurrentUser,
) -> PhaseRead:
    await _ensure_project_visible(db, project_id, user)
    # Default position: append at the end.
    if data.position == 0:
        last = (
            await db.execute(
                select(ProjectPhase.position)
                .where(ProjectPhase.project_id == project_id)
                .order_by(ProjectPhase.position.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        pos = (int(last) + 1) if last is not None else 0
    else:
        pos = data.position
    ph = ProjectPhase(
        project_id=project_id,
        name=data.name.strip(),
        position=pos,
        start_date=data.start_date,
        duration_days=data.duration_days,
        notes=(data.notes.strip() if data.notes else None),
        assignee_employe_id=data.assignee_employe_id,
        assignee_sous_traitant_id=data.assignee_sous_traitant_id,
    )
    db.add(ph)
    await db.flush()
    await db.refresh(ph)
    return PhaseRead.model_validate(ph)


@router.patch(
    "/{project_id}/phases/{phase_id}",
    response_model=PhaseRead,
)
async def update_phase(
    project_id: int,
    phase_id: int,
    data: PhaseUpdate,
    db: DBSession,
    user: CurrentUser,
) -> PhaseRead:
    await _ensure_project_visible(db, project_id, user)
    ph = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.id == phase_id,
                ProjectPhase.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if ph is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ph, field, value)
    await db.flush()
    await db.refresh(ph)
    return PhaseRead.model_validate(ph)


@router.delete(
    "/{project_id}/phases/{phase_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_phase(
    project_id: int,
    phase_id: int,
    db: DBSession,
    user: CurrentUser,
) -> None:
    await _ensure_project_visible(db, project_id, user)
    ph = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.id == phase_id,
                ProjectPhase.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if ph is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase not found")
    await db.delete(ph)
    await db.flush()


@router.put(
    "/{project_id}/phases/reorder",
    response_model=List[PhaseRead],
)
async def reorder_phases(
    project_id: int,
    data: ReorderBody,
    db: DBSession,
    user: CurrentUser,
) -> List[PhaseRead]:
    """Bulk reorder: accepts an ordered list of phase IDs and writes
    their new `position` in one pass. Phases not mentioned keep their
    existing position (bumped to the end)."""
    await _ensure_project_visible(db, project_id, user)
    rows = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.project_id == project_id
            )
        )
    ).scalars().all()
    by_id = {r.id: r for r in rows}
    pos = 0
    for pid in data.phase_ids:
        ph = by_id.get(pid)
        if ph is None:
            continue
        ph.position = pos
        pos += 1
    # Orphans go after the explicit order to preserve them.
    for ph in rows:
        if ph.id not in set(data.phase_ids):
            ph.position = pos
            pos += 1
    await db.flush()
    rows_sorted = sorted(
        rows, key=lambda r: (r.position, r.id)
    )
    return [PhaseRead.model_validate(r) for r in rows_sorted]


# ---------------------------------------------------------------------------
# Bulk listing — used by the agenda timeline (Par chantier / Par personne).
# Returns every phase the current user can see, across all visible projects.
# Kept on a separate router prefix so the URL is /api/v1/phases (flat).
# ---------------------------------------------------------------------------

phases_router = APIRouter(prefix="/phases", tags=["project-phases"])


@phases_router.get("", response_model=List[PhaseRead])
async def list_all_phases(
    db: DBSession, user: CurrentUser
) -> List[PhaseRead]:
    visible = await visible_project_ids(db, user)
    stmt = select(ProjectPhase).order_by(
        ProjectPhase.project_id.asc(),
        ProjectPhase.position.asc(),
        ProjectPhase.id.asc(),
    )
    if visible is not None:
        if not visible:
            return []
        stmt = stmt.where(ProjectPhase.project_id.in_(visible))
    rows = (await db.execute(stmt)).scalars().all()
    return [PhaseRead.model_validate(r) for r in rows]
