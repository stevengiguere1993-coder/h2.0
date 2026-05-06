"""Pipeline des deals — CRUD pour les opportunités d'achat suivies
en mode Monday-like dans Prospection.

Endpoints :
  GET    /api/v1/prospection/deals      → liste triée par priorité
  POST   /api/v1/prospection/deals      → crée un deal (adresse + priorité)
  PATCH  /api/v1/prospection/deals/{id} → met à jour adresse / priorité
  DELETE /api/v1/prospection/deals/{id} → supprime
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, select

from app.api.deps import CurrentUser, DBSession
from app.models.prospection_deal import PRIORITY_ORDER, ProspectionDeal
from app.models.prospection_deal_task import (
    TASK_PRIORITIES,
    TASK_STATUSES,
    ProspectionDealTask,
)


router = APIRouter(prefix="/prospection/deals", tags=["prospection-deals"])


# Validation : on accepte uniquement les valeurs canoniques côté API
# pour ne pas se retrouver avec des typos en DB.
PRIORITY_PATTERN = r"^(urgent|eleve|moyenne|en_attente|a_venir|termine)$"


class DealCreate(BaseModel):
    address: str = Field(..., min_length=1, max_length=500)
    priority: str = Field(default="moyenne", pattern=PRIORITY_PATTERN)


class DealUpdate(BaseModel):
    address: Optional[str] = Field(default=None, min_length=1, max_length=500)
    priority: Optional[str] = Field(default=None, pattern=PRIORITY_PATTERN)


class DealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    address: str
    priority: str
    created_at: datetime
    updated_at: datetime


def _priority_rank_expr():
    """SQL CASE qui mappe priority → rang numérique (0 = plus urgent)
    pour qu'ORDER BY trie correctement urgent → a_venir."""
    whens = {p: i for i, p in enumerate(PRIORITY_ORDER)}
    return case(whens, value=ProspectionDeal.priority, else_=99)


@router.get("", response_model=List[DealRead])
async def list_deals(
    db: DBSession,
    _: CurrentUser,
) -> List[DealRead]:
    rows = (
        await db.execute(
            select(ProspectionDeal).order_by(
                _priority_rank_expr(),
                ProspectionDeal.created_at.desc(),
            )
        )
    ).scalars().all()
    return [DealRead.model_validate(r) for r in rows]


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
async def create_deal(
    data: DealCreate,
    db: DBSession,
    _: CurrentUser,
) -> DealRead:
    deal = ProspectionDeal(
        address=data.address.strip(),
        priority=data.priority,
    )
    db.add(deal)
    await db.flush()
    await db.refresh(deal)
    return DealRead.model_validate(deal)


@router.patch("/{deal_id}", response_model=DealRead)
async def update_deal(
    deal_id: int,
    data: DealUpdate,
    db: DBSession,
    _: CurrentUser,
) -> DealRead:
    deal = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal introuvable.")
    if data.address is not None:
        deal.address = data.address.strip()
    if data.priority is not None:
        deal.priority = data.priority
    await db.flush()
    await db.refresh(deal)
    return DealRead.model_validate(deal)


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal(
    deal_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    deal = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal introuvable.")
    await db.delete(deal)
    await db.flush()


# ============================================================
# Tâches d'un deal
# ============================================================

TASK_STATUS_PATTERN = r"^(a_venir|a_faire|en_traitement|termine)$"
TASK_PRIORITY_PATTERN = r"^(urgent|eleve|moyenne|faible)$"


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=10_000)
    assignee_user_id: Optional[int] = Field(default=None, gt=0)
    status: str = Field(default="a_venir", pattern=TASK_STATUS_PATTERN)
    priority: str = Field(default="moyenne", pattern=TASK_PRIORITY_PATTERN)
    due_date: Optional[date] = None


class TaskUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=10_000)
    assignee_user_id: Optional[int] = None  # None autorisé pour désassigner
    status: Optional[str] = Field(default=None, pattern=TASK_STATUS_PATTERN)
    priority: Optional[str] = Field(
        default=None, pattern=TASK_PRIORITY_PATTERN
    )
    due_date: Optional[date] = None
    position: Optional[int] = Field(default=None, ge=0)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    deal_id: int
    name: str
    notes: Optional[str]
    assignee_user_id: Optional[int]
    status: str
    priority: str
    due_date: Optional[date]
    position: int
    created_at: datetime
    updated_at: datetime


def _task_status_rank_expr():
    whens = {s: i for i, s in enumerate(TASK_STATUSES)}
    return case(whens, value=ProspectionDealTask.status, else_=99)


async def _ensure_deal_exists(db, deal_id: int) -> ProspectionDeal:
    deal = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal introuvable.")
    return deal


@router.get("/{deal_id}/tasks", response_model=List[TaskRead])
async def list_tasks(
    deal_id: int,
    db: DBSession,
    _: CurrentUser,
) -> List[TaskRead]:
    await _ensure_deal_exists(db, deal_id)
    rows = (
        await db.execute(
            select(ProspectionDealTask)
            .where(ProspectionDealTask.deal_id == deal_id)
            .order_by(
                _task_status_rank_expr(),
                ProspectionDealTask.position.asc(),
                ProspectionDealTask.created_at.asc(),
            )
        )
    ).scalars().all()
    return [TaskRead.model_validate(r) for r in rows]


@router.post(
    "/{deal_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    deal_id: int,
    data: TaskCreate,
    db: DBSession,
    _: CurrentUser,
) -> TaskRead:
    await _ensure_deal_exists(db, deal_id)

    # Position : par défaut, après la dernière tâche du même statut.
    last_pos = (
        await db.execute(
            select(ProspectionDealTask.position)
            .where(
                ProspectionDealTask.deal_id == deal_id,
                ProspectionDealTask.status == data.status,
            )
            .order_by(ProspectionDealTask.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    next_pos = (int(last_pos) + 1000) if last_pos is not None else 1000

    task = ProspectionDealTask(
        deal_id=deal_id,
        name=data.name.strip(),
        notes=data.notes,
        assignee_user_id=data.assignee_user_id,
        status=data.status,
        priority=data.priority,
        due_date=data.due_date,
        position=next_pos,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return TaskRead.model_validate(task)


@router.patch("/{deal_id}/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    deal_id: int,
    task_id: int,
    data: TaskUpdate,
    db: DBSession,
    _: CurrentUser,
) -> TaskRead:
    task = (
        await db.execute(
            select(ProspectionDealTask).where(
                ProspectionDealTask.id == task_id,
                ProspectionDealTask.deal_id == deal_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tâche introuvable.")

    fields = data.model_dump(exclude_unset=True)
    for field, value in fields.items():
        if field == "name" and value is not None:
            value = value.strip()
        setattr(task, field, value)
    await db.flush()
    await db.refresh(task)
    return TaskRead.model_validate(task)


@router.delete(
    "/{deal_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_task(
    deal_id: int,
    task_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    task = (
        await db.execute(
            select(ProspectionDealTask).where(
                ProspectionDealTask.id == task_id,
                ProspectionDealTask.deal_id == deal_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tâche introuvable.")
    await db.delete(task)
    await db.flush()
