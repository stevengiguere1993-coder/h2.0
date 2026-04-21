"""Sales tasks (CRM tasks): follow-up, order material, meeting
reminders, etc. Can be attached to a prospect (contact_request) or a
client, with multiple employee assignees.

    GET    /api/v1/sales-tasks?client_id=...&contact_request_id=...&upcoming=true
    POST   /api/v1/sales-tasks
    PATCH  /api/v1/sales-tasks/{id}
    DELETE /api/v1/sales-tasks/{id}
"""

from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, insert, select

from app.api.deps import CurrentUser, DBSession
from app.models.sales_task import SalesTask, sales_task_assignees


router = APIRouter(prefix="/sales-tasks", tags=["sales-tasks"])


class SalesTaskCreate(BaseModel):
    kind: str = Field(default="suivi", max_length=32)
    title: str = Field(..., min_length=1, max_length=255)
    notes: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=16)
    contact_request_id: Optional[int] = None
    client_id: Optional[int] = None
    due_date: date
    all_day: bool = True
    due_time: Optional[str] = Field(default=None, max_length=8)
    recurrence: str = Field(default="none", pattern="^(none|daily|weekly|monthly)$")
    assignee_ids: List[int] = Field(default_factory=list)


class SalesTaskUpdate(BaseModel):
    kind: Optional[str] = Field(default=None, max_length=32)
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    notes: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=16)
    contact_request_id: Optional[int] = None
    client_id: Optional[int] = None
    due_date: Optional[date] = None
    all_day: Optional[bool] = None
    due_time: Optional[str] = Field(default=None, max_length=8)
    recurrence: Optional[str] = Field(
        default=None, pattern="^(none|daily|weekly|monthly)$"
    )
    done: Optional[bool] = None
    assignee_ids: Optional[List[int]] = None


class SalesTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    title: str
    notes: Optional[str]
    color: Optional[str]
    contact_request_id: Optional[int]
    client_id: Optional[int]
    due_date: date
    all_day: bool
    due_time: Optional[str]
    recurrence: str
    done: bool
    done_at: Optional[datetime]
    created_at: datetime
    assignee_ids: List[int] = Field(default_factory=list)


async def _assignees(db, task_id: int) -> List[int]:
    rows = (
        await db.execute(
            select(sales_task_assignees.c.employe_id).where(
                sales_task_assignees.c.task_id == task_id
            )
        )
    ).all()
    return [int(r.employe_id) for r in rows]


def _to_read(task: SalesTask, assignee_ids: List[int]) -> SalesTaskRead:
    data = SalesTaskRead.model_validate(task)
    data.assignee_ids = assignee_ids
    return data


@router.get("", response_model=List[SalesTaskRead])
async def list_tasks(
    db: DBSession,
    _: CurrentUser,
    client_id: Optional[int] = Query(default=None),
    contact_request_id: Optional[int] = Query(default=None),
    upcoming: bool = Query(default=False),
    include_done: bool = Query(default=True),
) -> List[SalesTaskRead]:
    stmt = select(SalesTask)
    if client_id is not None:
        stmt = stmt.where(SalesTask.client_id == client_id)
    if contact_request_id is not None:
        stmt = stmt.where(SalesTask.contact_request_id == contact_request_id)
    if upcoming:
        stmt = stmt.where(SalesTask.due_date >= date.today())
    if not include_done:
        stmt = stmt.where(SalesTask.done.is_(False))
    stmt = stmt.order_by(SalesTask.due_date.asc(), SalesTask.id.asc())
    rows = (await db.execute(stmt)).scalars().all()
    out: List[SalesTaskRead] = []
    for r in rows:
        out.append(_to_read(r, await _assignees(db, r.id)))
    return out


@router.post(
    "",
    response_model=SalesTaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    data: SalesTaskCreate,
    db: DBSession,
    _: CurrentUser,
) -> SalesTaskRead:
    task = SalesTask(
        kind=data.kind,
        title=data.title.strip(),
        notes=(data.notes.strip() if data.notes else None),
        color=(data.color or None),
        contact_request_id=data.contact_request_id,
        client_id=data.client_id,
        due_date=data.due_date,
        all_day=data.all_day,
        due_time=data.due_time,
        recurrence=data.recurrence,
    )
    db.add(task)
    await db.flush()
    if data.assignee_ids:
        await db.execute(
            insert(sales_task_assignees),
            [
                {"task_id": task.id, "employe_id": eid}
                for eid in set(data.assignee_ids)
            ],
        )
    await db.flush()
    await db.refresh(task)
    return _to_read(task, await _assignees(db, task.id))


@router.patch("/{task_id}", response_model=SalesTaskRead)
async def update_task(
    task_id: int,
    data: SalesTaskUpdate,
    db: DBSession,
    _: CurrentUser,
) -> SalesTaskRead:
    task = (
        await db.execute(select(SalesTask).where(SalesTask.id == task_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    upd = data.model_dump(exclude_unset=True)
    assignee_ids = upd.pop("assignee_ids", None)
    for field, value in upd.items():
        setattr(task, field, value)
    # Done toggle → timestamp
    if "done" in upd:
        task.done_at = (
            datetime.now(timezone.utc) if upd["done"] else None
        )
    await db.flush()
    if assignee_ids is not None:
        await db.execute(
            delete(sales_task_assignees).where(
                sales_task_assignees.c.task_id == task_id
            )
        )
        if assignee_ids:
            await db.execute(
                insert(sales_task_assignees),
                [
                    {"task_id": task_id, "employe_id": eid}
                    for eid in set(assignee_ids)
                ],
            )
    await db.flush()
    await db.refresh(task)
    return _to_read(task, await _assignees(db, task.id))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    task = (
        await db.execute(select(SalesTask).where(SalesTask.id == task_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    await db.delete(task)
    await db.flush()
