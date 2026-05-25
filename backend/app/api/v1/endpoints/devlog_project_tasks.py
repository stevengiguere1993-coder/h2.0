"""Endpoints des taches d'un projet Dev Logiciel.

    GET    /api/v1/devlog/projects/{project_id}/tasks
    POST   /api/v1/devlog/projects/{project_id}/tasks
    PATCH  /api/v1/devlog/projects/{project_id}/tasks/{task_id}
    DELETE /api/v1/devlog/projects/{project_id}/tasks/{task_id}

Tous proteges par le guard admin/owner du pole (applique au niveau
du router parent) et loguent les mutations dans audit_logs. Une
tache peut etre rattachee a une phase (phase_id) ou flottante
(phase_id NULL = tache directe sur le projet).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_phase import DevlogProjectPhase
from app.models.devlog_project_task import (
    TASK_PRIORITIES,
    TASK_STATUSES,
    DevlogProjectTask,
)
from app.schemas.devlog import (
    DevlogProjectTaskCreate,
    DevlogProjectTaskRead,
    DevlogProjectTaskUpdate,
)
from app.services.audit import log_action


router = APIRouter(prefix="/devlog/projects", tags=["devlog-project-tasks"])


async def _get_project_or_404(db, project_id: int) -> DevlogProject:
    obj = (
        await db.execute(
            select(DevlogProject).where(DevlogProject.id == project_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable")
    return obj


async def _ensure_phase_belongs_to_project(
    db, project_id: int, phase_id: Optional[int]
) -> None:
    if phase_id is None:
        return
    ok = (
        await db.execute(
            select(DevlogProjectPhase.id).where(
                DevlogProjectPhase.id == phase_id,
                DevlogProjectPhase.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if ok is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "La phase n'appartient pas a ce projet",
        )


@router.get(
    "/{project_id}/tasks",
    response_model=List[DevlogProjectTaskRead],
)
async def list_tasks(
    project_id: int,
    db: DBSession,
    _: CurrentUser,
    phase_id: Optional[int] = Query(default=None, ge=1),
) -> List[DevlogProjectTaskRead]:
    await _get_project_or_404(db, project_id)
    stmt = (
        select(DevlogProjectTask)
        .where(DevlogProjectTask.project_id == project_id)
        .order_by(DevlogProjectTask.id.asc())
    )
    if phase_id is not None:
        stmt = stmt.where(DevlogProjectTask.phase_id == phase_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [DevlogProjectTaskRead.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/tasks",
    response_model=DevlogProjectTaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    project_id: int,
    data: DevlogProjectTaskCreate,
    db: DBSession,
    user: CurrentUser,
) -> DevlogProjectTaskRead:
    await _get_project_or_404(db, project_id)
    if data.status not in TASK_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Statut de tache invalide",
        )
    if data.priority not in TASK_PRIORITIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Priorite de tache invalide",
        )
    await _ensure_phase_belongs_to_project(db, project_id, data.phase_id)
    obj = DevlogProjectTask(
        project_id=project_id,
        phase_id=data.phase_id,
        title=data.title.strip(),
        description=(data.description.strip() if data.description else None),
        assignee_user_id=data.assignee_user_id,
        status=data.status,
        priority=data.priority,
        due_date=data.due_date,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_project_task.created",
        entity_type="devlog_project_task",
        entity_id=obj.id,
        details={
            "project_id": project_id,
            "phase_id": data.phase_id,
            "title": obj.title,
        },
    )
    return DevlogProjectTaskRead.model_validate(obj)


@router.patch(
    "/{project_id}/tasks/{task_id}",
    response_model=DevlogProjectTaskRead,
)
async def update_task(
    project_id: int,
    task_id: int,
    data: DevlogProjectTaskUpdate,
    db: DBSession,
    user: CurrentUser,
) -> DevlogProjectTaskRead:
    await _get_project_or_404(db, project_id)
    obj = (
        await db.execute(
            select(DevlogProjectTask).where(
                DevlogProjectTask.id == task_id,
                DevlogProjectTask.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tache introuvable")
    fields = data.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] not in TASK_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Statut de tache invalide",
        )
    if "priority" in fields and fields["priority"] not in TASK_PRIORITIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Priorite de tache invalide",
        )
    if "phase_id" in fields:
        await _ensure_phase_belongs_to_project(
            db, project_id, fields["phase_id"]
        )
    if "title" in fields and isinstance(fields["title"], str):
        fields["title"] = fields["title"].strip()
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
        action="devlog_project_task.updated",
        entity_type="devlog_project_task",
        entity_id=obj.id,
        details={"project_id": project_id, **fields},
    )
    return DevlogProjectTaskRead.model_validate(obj)


@router.delete(
    "/{project_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_task(
    project_id: int,
    task_id: int,
    db: DBSession,
    user: CurrentUser,
) -> None:
    await _get_project_or_404(db, project_id)
    obj = (
        await db.execute(
            select(DevlogProjectTask).where(
                DevlogProjectTask.id == task_id,
                DevlogProjectTask.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tache introuvable")
    await db.delete(obj)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="devlog_project_task.deleted",
        entity_type="devlog_project_task",
        entity_id=task_id,
        details={"project_id": project_id},
    )
