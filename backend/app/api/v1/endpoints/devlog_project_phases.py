"""Endpoints des phases d'un projet Dev Logiciel.

    GET    /api/v1/devlog/projects/{project_id}/phases
    POST   /api/v1/devlog/projects/{project_id}/phases
    PATCH  /api/v1/devlog/projects/{project_id}/phases/{phase_id}
    DELETE /api/v1/devlog/projects/{project_id}/phases/{phase_id}
    POST   /api/v1/devlog/projects/{project_id}/phases/reorder

Tous ces endpoints sont proteges par le guard admin/owner du pole
(applique au niveau du router parent dans api/v1/router.py) et
loguent les mutations dans audit_logs.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_phase import PHASE_STATUSES, DevlogProjectPhase
from app.schemas.devlog import (
    DevlogProjectPhaseCreate,
    DevlogProjectPhaseRead,
    DevlogProjectPhaseReorder,
    DevlogProjectPhaseUpdate,
)
from app.services.audit import log_action


router = APIRouter(prefix="/devlog/projects", tags=["devlog-project-phases"])


async def _get_project_or_404(db, project_id: int) -> DevlogProject:
    obj = (
        await db.execute(
            select(DevlogProject).where(DevlogProject.id == project_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable")
    return obj


@router.get(
    "/{project_id}/phases",
    response_model=List[DevlogProjectPhaseRead],
)
async def list_phases(
    project_id: int, db: DBSession, _: CurrentUser
) -> List[DevlogProjectPhaseRead]:
    await _get_project_or_404(db, project_id)
    rows = (
        await db.execute(
            select(DevlogProjectPhase)
            .where(DevlogProjectPhase.project_id == project_id)
            .order_by(
                DevlogProjectPhase.position.asc(),
                DevlogProjectPhase.id.asc(),
            )
        )
    ).scalars().all()
    return [DevlogProjectPhaseRead.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/phases",
    response_model=DevlogProjectPhaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_phase(
    project_id: int,
    data: DevlogProjectPhaseCreate,
    db: DBSession,
    user: CurrentUser,
) -> DevlogProjectPhaseRead:
    await _get_project_or_404(db, project_id)
    if data.status not in PHASE_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Statut de phase invalide",
        )
    # Position par defaut : append a la fin.
    if data.position == 0:
        last = (
            await db.execute(
                select(DevlogProjectPhase.position)
                .where(DevlogProjectPhase.project_id == project_id)
                .order_by(DevlogProjectPhase.position.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        pos = (int(last) + 1) if last is not None else 0
    else:
        pos = data.position
    obj = DevlogProjectPhase(
        project_id=project_id,
        name=data.name.strip(),
        description=(data.description.strip() if data.description else None),
        position=pos,
        start_date=data.start_date,
        end_date=data.end_date,
        status=data.status,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_project_phase.created",
        entity_type="devlog_project_phase",
        entity_id=obj.id,
        details={"project_id": project_id, "name": obj.name},
    )
    return DevlogProjectPhaseRead.model_validate(obj)


@router.patch(
    "/{project_id}/phases/{phase_id}",
    response_model=DevlogProjectPhaseRead,
)
async def update_phase(
    project_id: int,
    phase_id: int,
    data: DevlogProjectPhaseUpdate,
    db: DBSession,
    user: CurrentUser,
) -> DevlogProjectPhaseRead:
    await _get_project_or_404(db, project_id)
    obj = (
        await db.execute(
            select(DevlogProjectPhase).where(
                DevlogProjectPhase.id == phase_id,
                DevlogProjectPhase.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase introuvable")
    fields = data.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] not in PHASE_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Statut de phase invalide",
        )
    if "name" in fields and isinstance(fields["name"], str):
        fields["name"] = fields["name"].strip()
    if "description" in fields and isinstance(fields["description"], str):
        fields["description"] = (
            fields["description"].strip() or None
        )
    for field, value in fields.items():
        setattr(obj, field, value)
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_project_phase.updated",
        entity_type="devlog_project_phase",
        entity_id=obj.id,
        details={"project_id": project_id, **fields},
    )
    return DevlogProjectPhaseRead.model_validate(obj)


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
    await _get_project_or_404(db, project_id)
    obj = (
        await db.execute(
            select(DevlogProjectPhase).where(
                DevlogProjectPhase.id == phase_id,
                DevlogProjectPhase.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase introuvable")
    await db.delete(obj)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="devlog_project_phase.deleted",
        entity_type="devlog_project_phase",
        entity_id=phase_id,
        details={"project_id": project_id},
    )


@router.post(
    "/{project_id}/phases/reorder",
    response_model=List[DevlogProjectPhaseRead],
)
async def reorder_phases(
    project_id: int,
    data: DevlogProjectPhaseReorder,
    db: DBSession,
    user: CurrentUser,
) -> List[DevlogProjectPhaseRead]:
    """Reordonne les phases d'un projet : on accepte une liste d'IDs
    dans l'ordre souhaite et on reecrit ``position`` en un passage.
    Les phases non mentionnees passent a la fin."""
    await _get_project_or_404(db, project_id)
    rows = (
        await db.execute(
            select(DevlogProjectPhase).where(
                DevlogProjectPhase.project_id == project_id
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
    mentioned = set(data.phase_ids)
    for r in rows:
        if r.id not in mentioned:
            r.position = pos
            pos += 1
    await db.flush()
    rows_sorted = sorted(rows, key=lambda r: (r.position, r.id))
    await log_action(
        db,
        user=user,
        action="devlog_project_phase.reordered",
        entity_type="devlog_project",
        entity_id=project_id,
        details={"phase_ids": list(data.phase_ids)},
    )
    return [DevlogProjectPhaseRead.model_validate(r) for r in rows_sorted]
