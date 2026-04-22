"""Follow-up CRUD + listing.

    GET    /api/v1/follow-ups?subject_type=prospect&subject_id=42
    POST   /api/v1/follow-ups
    PATCH  /api/v1/follow-ups/{id}
    DELETE /api/v1/follow-ups/{id}
    GET    /api/v1/follow-ups/overdue          → suivis dépassés
    GET    /api/v1/follow-ups/upcoming         → suivis à faire (today + tomorrow)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.follow_up import FollowUp
from app.services.follow_up import compute_next_after_log


router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])


class FollowUpRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject_type: str
    subject_id: int
    kind: str
    direction: str
    outcome: str
    notes: Optional[str]
    performed_by_user_id: Optional[int]
    performed_at: datetime
    next_action_at: Optional[datetime]
    next_action_label: Optional[str]
    created_at: datetime


class FollowUpCreate(BaseModel):
    subject_type: str = Field(..., pattern="^(prospect|soumission)$")
    subject_id: int = Field(..., gt=0)
    kind: str = Field(
        default="call",
        pattern="^(call|email|sms|visite|note|auto)$",
    )
    direction: str = Field(default="outbound", pattern="^(outbound|inbound)$")
    outcome: str = Field(
        default="reached",
        pattern=(
            "^(reached|voicemail|no_answer|interested|not_interested|"
            "won|lost|pending|scheduled)$"
        ),
    )
    notes: Optional[str] = None
    # Si non fourni, on calcule via compute_next_after_log
    next_action_at: Optional[datetime] = None
    next_action_label: Optional[str] = None
    # Label de l'étape qu'on vient de compléter, sert au calcul du
    # next step quand next_action_at n'est pas fourni manuellement.
    completed_step: Optional[str] = None


class FollowUpUpdate(BaseModel):
    outcome: Optional[str] = Field(
        default=None,
        pattern=(
            "^(reached|voicemail|no_answer|interested|not_interested|"
            "won|lost|pending|scheduled)$"
        ),
    )
    notes: Optional[str] = None
    next_action_at: Optional[datetime] = None
    next_action_label: Optional[str] = None


@router.get("", response_model=List[FollowUpRead])
async def list_follow_ups(
    db: DBSession,
    _: CurrentUser,
    subject_type: Optional[str] = Query(default=None),
    subject_id: Optional[int] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> List[FollowUpRead]:
    stmt = select(FollowUp)
    if subject_type:
        stmt = stmt.where(FollowUp.subject_type == subject_type)
    if subject_id is not None:
        stmt = stmt.where(FollowUp.subject_id == subject_id)
    stmt = stmt.order_by(FollowUp.performed_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [FollowUpRead.model_validate(r) for r in rows]


@router.get("/overdue", response_model=List[FollowUpRead])
async def list_overdue(
    db: DBSession, _: RequireManager
) -> List[FollowUpRead]:
    """Suivis dont next_action_at est dans le passé et qui sont
    encore en attente (kind=auto + outcome=scheduled, ou outcome ∉
    STOP_OUTCOMES)."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(FollowUp)
        .where(
            FollowUp.next_action_at.is_not(None),
            FollowUp.next_action_at <= now,
            FollowUp.outcome.notin_(["won", "lost", "not_interested"]),
        )
        .order_by(FollowUp.next_action_at.asc())
        .limit(500)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [FollowUpRead.model_validate(r) for r in rows]


@router.get("/upcoming", response_model=List[FollowUpRead])
async def list_upcoming(
    db: DBSession,
    _: RequireManager,
    days: int = Query(default=7, ge=1, le=30),
) -> List[FollowUpRead]:
    """Suivis à faire dans les `days` prochains jours."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    stmt = (
        select(FollowUp)
        .where(
            FollowUp.next_action_at.is_not(None),
            FollowUp.next_action_at >= now,
            FollowUp.next_action_at <= end,
            FollowUp.outcome.notin_(["won", "lost", "not_interested"]),
        )
        .order_by(FollowUp.next_action_at.asc())
        .limit(500)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [FollowUpRead.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=FollowUpRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_follow_up(
    data: FollowUpCreate,
    db: DBSession,
    user: CurrentUser,
) -> FollowUpRead:
    next_at = data.next_action_at
    next_label = data.next_action_label
    if next_at is None and data.outcome not in ("won", "lost", "not_interested"):
        # Auto-calcul
        step = compute_next_after_log(
            subject_type=data.subject_type,
            last_label=data.completed_step,
            outcome=data.outcome,
        )
        if step:
            next_label, next_at = step

    fu = FollowUp(
        subject_type=data.subject_type,
        subject_id=data.subject_id,
        kind=data.kind,
        direction=data.direction,
        outcome=data.outcome,
        notes=(data.notes.strip() if data.notes else None),
        performed_by_user_id=user.id,
        next_action_at=next_at,
        next_action_label=next_label,
    )
    db.add(fu)
    await db.flush()
    await db.refresh(fu)
    return FollowUpRead.model_validate(fu)


@router.patch("/{fu_id}", response_model=FollowUpRead)
async def update_follow_up(
    fu_id: int,
    data: FollowUpUpdate,
    db: DBSession,
    _: CurrentUser,
) -> FollowUpRead:
    fu = (
        await db.execute(select(FollowUp).where(FollowUp.id == fu_id))
    ).scalar_one_or_none()
    if fu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suivi introuvable.")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(fu, field, value)
    await db.flush()
    await db.refresh(fu)
    return FollowUpRead.model_validate(fu)


@router.delete("/{fu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_follow_up(
    fu_id: int, db: DBSession, _: RequireManager
) -> None:
    fu = (
        await db.execute(select(FollowUp).where(FollowUp.id == fu_id))
    ).scalar_one_or_none()
    if fu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suivi introuvable.")
    await db.delete(fu)
    await db.flush()
