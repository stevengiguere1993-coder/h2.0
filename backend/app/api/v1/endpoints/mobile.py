"""Mobile-facing endpoints for the PWA employee app.

    GET  /api/v1/mobile/me           — profile + open punch + next event + week stats
    POST /api/v1/mobile/punch/start  — start a punch (project_id optional)
    POST /api/v1/mobile/punch/stop   — close the open punch
    POST /api/v1/mobile/leave        — request a leave (stored as agenda event type=conge)

The logged-in User is linked to an Employe by matching `email` (case
insensitive). The link is lazy — if no match is found, the call
returns a minimal profile so the UI can still render and the employee
can be created later by admin.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select

from app.api.deps import CurrentUser, DBSession
from app.models.agenda_event import AgendaEvent
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.employe import Employe
from app.models.project import Project, ProjectStatus
from app.models.punch import Punch


router = APIRouter(prefix="/mobile", tags=["mobile"])


class EmployeMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    email: Optional[str]
    role: Optional[str]
    hourly_rate: Optional[float]
    employeur_d_url: Optional[str] = None


class OpenPunch(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    started_at: datetime
    project_id: Optional[int]
    contact_request_id: Optional[int]
    task: Optional[str]


class PunchContextProject(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    address: Optional[str]


class PunchContextProspect(BaseModel):
    id: int
    name: str
    address: Optional[str]
    project_type: str


class PunchContextsResponse(BaseModel):
    projects: list[PunchContextProject]
    prospects: list[PunchContextProspect]


class AgendaEventMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: Optional[str]
    location: Optional[str]
    start_at: datetime
    end_at: Optional[datetime]
    all_day: bool
    project_id: Optional[int]
    event_type: str


class WeekStats(BaseModel):
    hours_worked: float
    hours_target: float
    revenue: float
    revenue_target: float
    shifts_approved: int
    shifts_pending: int


class MobileMe(BaseModel):
    user_email: str
    employe: Optional[EmployeMini]
    open_punch: Optional[OpenPunch]
    current_event: Optional[AgendaEventMini]
    next_event: Optional[AgendaEventMini]
    week: WeekStats


class PunchStartBody(BaseModel):
    # One of the three contexts; at least one must be non-null for the
    # punch to be useful downstream (finances, reporting).
    project_id: Optional[int] = None
    contact_request_id: Optional[int] = None
    # Free-form task label, e.g. "Admin", "Déplacement", "Formation".
    task: Optional[str] = Field(default=None, max_length=255)
    geolocation: Optional[str] = Field(default=None, max_length=128)


class LeaveRequestBody(BaseModel):
    start_at: datetime
    end_at: datetime
    reason: Optional[str] = Field(default=None, max_length=500)
    kind: str = Field(
        default="vacation", pattern="^(vacation|sick|personal)$"
    )


async def _resolve_employe(db, user_email: str) -> Optional[Employe]:
    if not user_email:
        return None
    stmt = select(Employe).where(
        func.lower(Employe.email) == user_email.lower(),
        Employe.active.is_(True),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


@router.get("/me", response_model=MobileMe)
async def me(db: DBSession, user: CurrentUser) -> MobileMe:
    emp = await _resolve_employe(db, user.email)

    open_punch: Optional[Punch] = None
    shifts_approved = 0
    shifts_pending = 0
    hours_worked = 0.0
    revenue = 0.0

    if emp is not None:
        # Still-open punch (no ended_at)
        open_punch = (
            await db.execute(
                select(Punch)
                .where(
                    Punch.employe_id == emp.id,
                    Punch.ended_at.is_(None),
                )
                .order_by(Punch.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        # Week window (Mon 00:00 → now)
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        week_start = datetime.combine(monday, time.min, tzinfo=timezone.utc)

        week_punches = (
            await db.execute(
                select(Punch).where(
                    Punch.employe_id == emp.id,
                    Punch.started_at >= week_start,
                    Punch.ended_at.is_not(None),
                )
            )
        ).scalars().all()
        for p in week_punches:
            h = float(p.hours or 0)
            hours_worked += h
            if p.approved:
                shifts_approved += 1
            else:
                shifts_pending += 1
        if emp.hourly_rate:
            revenue = round(hours_worked * float(emp.hourly_rate), 2)

    # Current + next event for this employee (or any unassigned if they
    # have no employe link)
    now = datetime.now(timezone.utc)
    filt = []
    if emp is not None:
        filt.append(
            or_(
                AgendaEvent.assignee_id == emp.id,
                AgendaEvent.assignee_id.is_(None),
            )
        )

    current_stmt = (
        select(AgendaEvent)
        .where(
            AgendaEvent.start_at <= now,
            or_(
                AgendaEvent.end_at.is_(None),
                AgendaEvent.end_at >= now,
            ),
            *filt,
        )
        .order_by(AgendaEvent.start_at.desc())
        .limit(1)
    )
    current_event = (await db.execute(current_stmt)).scalar_one_or_none()

    next_stmt = (
        select(AgendaEvent)
        .where(AgendaEvent.start_at > now, *filt)
        .order_by(AgendaEvent.start_at.asc())
        .limit(1)
    )
    next_event = (await db.execute(next_stmt)).scalar_one_or_none()

    return MobileMe(
        user_email=user.email,
        employe=EmployeMini.model_validate(emp) if emp else None,
        open_punch=OpenPunch.model_validate(open_punch) if open_punch else None,
        current_event=(
            AgendaEventMini.model_validate(current_event)
            if current_event
            else None
        ),
        next_event=(
            AgendaEventMini.model_validate(next_event) if next_event else None
        ),
        week=WeekStats(
            hours_worked=round(hours_worked, 2),
            hours_target=40.0,
            revenue=revenue,
            revenue_target=1200.0,
            shifts_approved=shifts_approved,
            shifts_pending=shifts_pending,
        ),
    )


@router.post("/punch/start", response_model=OpenPunch)
async def punch_start(
    body: PunchStartBody,
    db: DBSession,
    user: CurrentUser,
) -> OpenPunch:
    emp = await _resolve_employe(db, user.email)
    if emp is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Aucun employé n'est lié à ce compte (email).",
        )
    # Reject if one already open
    already = (
        await db.execute(
            select(Punch).where(
                Punch.employe_id == emp.id, Punch.ended_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Un punch est déjà en cours.",
        )
    # At least one context is required so reporting stays meaningful.
    if not any([body.project_id, body.contact_request_id, body.task]):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Un contexte est requis (projet, prospect ou tâche admin).",
        )
    now = datetime.now(timezone.utc)
    p = Punch(
        employe_id=emp.id,
        project_id=body.project_id,
        contact_request_id=body.contact_request_id,
        started_at=now,
        task=body.task,
        geolocation=body.geolocation,
    )
    db.add(p)
    await db.flush()
    await db.refresh(p)
    return OpenPunch.model_validate(p)


@router.post("/punch/stop", response_model=OpenPunch)
async def punch_stop(
    db: DBSession,
    user: CurrentUser,
) -> OpenPunch:
    emp = await _resolve_employe(db, user.email)
    if emp is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Aucun employé n'est lié à ce compte (email).",
        )
    p = (
        await db.execute(
            select(Punch).where(
                Punch.employe_id == emp.id, Punch.ended_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Aucun punch ouvert à arrêter."
        )
    now = datetime.now(timezone.utc)
    p.ended_at = now
    delta = (now - p.started_at).total_seconds() / 3600.0
    p.hours = round(delta, 2)
    await db.flush()
    await db.refresh(p)
    return OpenPunch.model_validate(p)


class LeaveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    start_at: datetime
    end_at: datetime
    status: str
    reason: Optional[str]


@router.post(
    "/leave",
    response_model=LeaveResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a leave request (pending approval by an admin)",
)
async def request_leave(
    body: LeaveRequestBody,
    db: DBSession,
    user: CurrentUser,
) -> LeaveResponse:
    """Legacy endpoint kept for the PWA conge form; now submits a
    LeaveRequest (pending) via the new workflow so admins can
    approve/reject. Agenda block is created on approval, not here."""
    from app.models.leave_request import LeaveRequest, LeaveStatus

    emp = await _resolve_employe(db, user.email)
    if emp is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Aucun employé n'est lié à ce compte (email).",
        )
    if body.end_at <= body.start_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Plage horaire invalide."
        )
    lr = LeaveRequest(
        employe_id=emp.id,
        kind=body.kind,
        start_at=body.start_at,
        end_at=body.end_at,
        reason=(body.reason.strip() if body.reason else None),
        status=LeaveStatus.PENDING.value,
    )
    db.add(lr)
    await db.flush()
    await db.refresh(lr)
    return LeaveResponse.model_validate(lr)


@router.get(
    "/agenda",
    response_model=List[AgendaEventMini],
    summary="Agenda for the logged-in employee (next 14 days)",
)
async def my_agenda(
    db: DBSession,
    user: CurrentUser,
    days: int = 14,
) -> List[AgendaEventMini]:
    emp = await _resolve_employe(db, user.email)
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=max(1, min(60, days)))
    stmt = (
        select(AgendaEvent)
        .where(
            AgendaEvent.start_at >= now - timedelta(days=1),
            AgendaEvent.start_at <= horizon,
        )
        .order_by(AgendaEvent.start_at.asc())
    )
    if emp is not None:
        stmt = stmt.where(
            or_(
                AgendaEvent.assignee_id == emp.id,
                AgendaEvent.assignee_id.is_(None),
            )
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [AgendaEventMini.model_validate(r) for r in rows]



@router.get(
    "/punch/contexts",
    response_model=PunchContextsResponse,
    summary="Active projects + open prospects for the punch picker",
)
async def punch_contexts(
    db: DBSession,
    _: CurrentUser,
) -> PunchContextsResponse:
    # Active projects — planned or in progress. Skip suspended/delivered.
    proj_stmt = (
        select(Project)
        .where(
            Project.status.in_(
                [ProjectStatus.PLANNED.value, ProjectStatus.IN_PROGRESS.value]
            )
        )
        .order_by(Project.name.asc())
    )
    projects = (await db.execute(proj_stmt)).scalars().all()

    # Open prospects — anything not won/lost/spam so the employee can
    # punch a visit or quote prep.
    prospect_stmt = (
        select(ContactRequest)
        .where(
            ContactRequest.status.in_(
                [
                    ContactRequestStatus.NEW.value,
                    ContactRequestStatus.CONTACTED.value,
                    ContactRequestStatus.QUALIFIED.value,
                    ContactRequestStatus.QUOTED.value,
                ]
            )
        )
        .order_by(ContactRequest.created_at.desc())
        .limit(50)
    )
    prospects = (await db.execute(prospect_stmt)).scalars().all()

    return PunchContextsResponse(
        projects=[
            PunchContextProject(
                id=p.id, name=p.name, address=p.address
            )
            for p in projects
        ],
        prospects=[
            PunchContextProspect(
                id=p.id,
                name=p.name,
                address=p.address,
                project_type=p.project_type,
            )
            for p in prospects
        ],
    )
