"""Assignable checklist tasks on a Project.

    GET    /api/v1/projects/{id}/tasks
    POST   /api/v1/projects/{id}/tasks
    PATCH  /api/v1/projects/{id}/tasks/{task_id}
    DELETE /api/v1/projects/{id}/tasks/{task_id}
"""

from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.project import Project
from app.models.project_task import ProjectTask


router = APIRouter(prefix="/projects", tags=["project-tasks"])


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    assignee_id: Optional[int] = Field(default=None, gt=0)
    due_date: Optional[date] = None
    position: int = Field(default=0, ge=0)


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    assignee_id: Optional[int] = Field(default=None, gt=0)
    due_date: Optional[date] = None
    done: Optional[bool] = None
    position: Optional[int] = Field(default=None, ge=0)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    title: str
    description: Optional[str]
    assignee_id: Optional[int]
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
    return [TaskRead.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    project_id: int, data: TaskCreate, db: DBSession, _: CurrentUser
) -> TaskRead:
    await _ensure_project(db, project_id)
    task = ProjectTask(
        project_id=project_id,
        title=data.title.strip(),
        description=data.description,
        assignee_id=data.assignee_id,
        due_date=data.due_date,
        position=data.position,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return TaskRead.model_validate(task)


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
    was_done = task.done
    for field, value in update.items():
        setattr(task, field, value)
    # Stamp done_at when the task just got ticked; clear when unticked.
    if "done" in update:
        if task.done and not was_done:
            task.done_at = datetime.now(timezone.utc)
        elif not task.done:
            task.done_at = None

    await db.flush()
    await db.refresh(task)
    return TaskRead.model_validate(task)


@router.delete(
    "/{project_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_task(
    project_id: int, task_id: int, db: DBSession, _: CurrentUser
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
