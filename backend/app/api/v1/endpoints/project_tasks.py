"""Assignable checklist tasks on a Project.

    GET    /api/v1/projects/{id}/tasks
    POST   /api/v1/projects/{id}/tasks
    PATCH  /api/v1/projects/{id}/tasks/{task_id}
    DELETE /api/v1/projects/{id}/tasks/{task_id}

Multi-assignation:
Une tâche peut être assignée à plusieurs employés et/ou sous-traitants
via la table `project_task_assignees`. Les payloads acceptent
`assignee_employe_ids` + `assignee_sous_traitant_ids`. Le champ legacy
`assignee_id` reste supporté (= 1er employé) pour compatibilité.
"""

from datetime import date, datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DBSession
from app.models.user import User
from app.services.permissions_service import require_capability
from app.models.project import Project
from app.models.project_assignees import ProjectTaskAssignee
from app.models.project_task import ProjectTask


router = APIRouter(prefix="/projects", tags=["project-tasks"])


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    assignee_id: Optional[int] = Field(default=None, gt=0)  # legacy
    assignee_employe_ids: Optional[List[int]] = None
    assignee_sous_traitant_ids: Optional[List[int]] = None
    phase_id: Optional[int] = Field(default=None, gt=0)
    due_date: Optional[date] = None
    position: int = Field(default=0, ge=0)


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    assignee_id: Optional[int] = Field(default=None, gt=0)  # legacy
    assignee_employe_ids: Optional[List[int]] = None
    assignee_sous_traitant_ids: Optional[List[int]] = None
    phase_id: Optional[int] = None  # allow null to detach from phase
    due_date: Optional[date] = None
    done: Optional[bool] = None
    position: Optional[int] = Field(default=None, ge=0)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    title: str
    description: Optional[str]
    # Legacy = premier employé assigné.
    assignee_id: Optional[int]
    assignee_employe_ids: List[int] = Field(default_factory=list)
    assignee_sous_traitant_ids: List[int] = Field(default_factory=list)
    phase_id: Optional[int] = None
    due_date: Optional[date]
    done: bool
    done_at: Optional[datetime]
    position: int
    created_at: datetime


async def _ensure_project(db, project_id: int) -> Project:
    p = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


async def _load_task_assignees(
    db, task_ids: List[int]
) -> dict[int, tuple[List[int], List[int]]]:
    if not task_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ProjectTaskAssignee.task_id,
                ProjectTaskAssignee.employe_id,
                ProjectTaskAssignee.sous_traitant_id,
            ).where(ProjectTaskAssignee.task_id.in_(task_ids))
        )
    ).all()
    out: dict[int, tuple[List[int], List[int]]] = {
        tid: ([], []) for tid in task_ids
    }
    for task_id, emp_id, st_id in rows:
        emps, sts = out[int(task_id)]
        if emp_id is not None:
            emps.append(int(emp_id))
        if st_id is not None:
            sts.append(int(st_id))
    for tid in out:
        out[tid][0].sort()
        out[tid][1].sort()
    return out


def _task_read(
    task: ProjectTask,
    employe_ids: List[int],
    sous_traitant_ids: List[int],
) -> TaskRead:
    # Legacy assignee_id = premier employé pour préserver les
    # consumers (notifications, mobile, etc.) qui ne lisent pas encore
    # la liste.
    primary = employe_ids[0] if employe_ids else task.assignee_id
    return TaskRead(
        id=task.id,
        project_id=task.project_id,
        title=task.title,
        description=task.description,
        assignee_id=primary,
        assignee_employe_ids=employe_ids,
        assignee_sous_traitant_ids=sous_traitant_ids,
        phase_id=task.phase_id,
        due_date=task.due_date,
        done=task.done,
        done_at=task.done_at,
        position=task.position,
        created_at=task.created_at,
    )


async def _replace_task_assignees(
    db,
    task: ProjectTask,
    employe_ids: Optional[List[int]],
    sous_traitant_ids: Optional[List[int]],
) -> None:
    if employe_ids is not None:
        await db.execute(
            delete(ProjectTaskAssignee).where(
                ProjectTaskAssignee.task_id == task.id,
                ProjectTaskAssignee.employe_id.is_not(None),
            )
        )
        for emp_id in dict.fromkeys(employe_ids):
            db.add(
                ProjectTaskAssignee(
                    task_id=task.id, employe_id=int(emp_id)
                )
            )
        task.assignee_id = int(employe_ids[0]) if employe_ids else None
    if sous_traitant_ids is not None:
        await db.execute(
            delete(ProjectTaskAssignee).where(
                ProjectTaskAssignee.task_id == task.id,
                ProjectTaskAssignee.sous_traitant_id.is_not(None),
            )
        )
        for st_id in dict.fromkeys(sous_traitant_ids):
            db.add(
                ProjectTaskAssignee(
                    task_id=task.id, sous_traitant_id=int(st_id)
                )
            )
    await db.flush()


@router.get("/{project_id}/tasks", response_model=List[TaskRead])
async def list_tasks(
    project_id: int, db: DBSession, _: CurrentUser
) -> List[TaskRead]:
    await _ensure_project(db, project_id)
    rows = (
        await db.execute(
            select(ProjectTask)
            .where(ProjectTask.project_id == project_id)
            .order_by(
                ProjectTask.done.asc(),
                ProjectTask.position.asc(),
                ProjectTask.id.asc(),
            )
        )
    ).scalars().all()
    assignees = await _load_task_assignees(db, [r.id for r in rows])
    return [
        _task_read(r, *assignees.get(r.id, ([], [])))
        for r in rows
    ]


@router.post(
    "/{project_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    project_id: int, data: TaskCreate, db: DBSession, _: CurrentUser
) -> TaskRead:
    await _ensure_project(db, project_id)
    # Résout la liste d'employés (nouvelle liste > legacy assignee_id).
    if data.assignee_employe_ids is not None:
        emp_list: Optional[List[int]] = [
            int(x) for x in data.assignee_employe_ids
        ]
    elif data.assignee_id is not None:
        emp_list = [int(data.assignee_id)]
    else:
        emp_list = None
    st_list = (
        [int(x) for x in data.assignee_sous_traitant_ids]
        if data.assignee_sous_traitant_ids is not None
        else None
    )
    task = ProjectTask(
        project_id=project_id,
        title=data.title.strip(),
        description=data.description,
        assignee_id=(emp_list[0] if emp_list else None),
        phase_id=data.phase_id,
        due_date=data.due_date,
        position=data.position,
    )
    db.add(task)
    await db.flush()
    await _replace_task_assignees(db, task, emp_list, st_list)
    await db.refresh(task)
    assignees = await _load_task_assignees(db, [task.id])
    return _task_read(task, *assignees.get(task.id, ([], [])))


@router.patch("/{project_id}/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    project_id: int,
    task_id: int,
    data: TaskUpdate,
    db: DBSession,
    _: CurrentUser,
) -> TaskRead:
    task = (
        await db.execute(
            select(ProjectTask).where(
                ProjectTask.id == task_id,
                ProjectTask.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")

    update = data.model_dump(exclude_unset=True)
    # On traite les assignations séparément via _replace_task_assignees.
    emp_ids_in_body = update.pop("assignee_employe_ids", None)
    st_ids_in_body = update.pop("assignee_sous_traitant_ids", None)
    legacy_assignee = update.pop("assignee_id", None)

    was_done = task.done
    for field, value in update.items():
        setattr(task, field, value)
    if "done" in update:
        if task.done and not was_done:
            task.done_at = datetime.now(timezone.utc)
        elif not task.done:
            task.done_at = None

    await db.flush()

    has_list_update = (
        "assignee_employe_ids" in data.model_fields_set
        or "assignee_sous_traitant_ids" in data.model_fields_set
    )
    has_legacy_update = "assignee_id" in data.model_fields_set
    if has_list_update or has_legacy_update:
        if emp_ids_in_body is not None:
            resolved_emp: Optional[List[int]] = [
                int(x) for x in emp_ids_in_body
            ]
        elif has_legacy_update:
            resolved_emp = (
                [int(legacy_assignee)] if legacy_assignee else []
            )
        else:
            resolved_emp = None
        resolved_st: Optional[List[int]] = (
            [int(x) for x in st_ids_in_body]
            if st_ids_in_body is not None
            else None
        )
        await _replace_task_assignees(
            db, task, resolved_emp, resolved_st
        )

    await db.refresh(task)
    assignees = await _load_task_assignees(db, [task.id])
    return _task_read(task, *assignees.get(task.id, ([], [])))


@router.delete(
    "/{project_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_task(
    project_id: int,
    task_id: int,
    db: DBSession,
    _: Annotated[User, Depends(require_capability("project.task.delete"))],
) -> None:
    task = (
        await db.execute(
            select(ProjectTask).where(
                ProjectTask.id == task_id,
                ProjectTask.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    await db.delete(task)
    await db.flush()
