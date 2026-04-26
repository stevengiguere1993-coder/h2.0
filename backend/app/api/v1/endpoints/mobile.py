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


class PunchStopBody(BaseModel):
    geolocation: Optional[str] = Field(default=None, max_length=128)


@router.post("/punch/stop", response_model=OpenPunch)
async def punch_stop(
    db: DBSession,
    user: CurrentUser,
    body: Optional[PunchStopBody] = None,
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
    # Concatène le geolocation de fin si fourni — séparateur '|' pour
    # qu'on puisse distinguer début et fin dans l'historique admin.
    if body and body.geolocation:
        end_geo = body.geolocation.strip()
        if p.geolocation:
            p.geolocation = f"{p.geolocation}|{end_geo}"[:128]
        else:
            p.geolocation = end_geo[:128]
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

    # Notif cloche aux managers+ pour qu'ils voient la demande sans
    # avoir à regarder le badge du menu Administration à chaque fois.
    try:
        from app.services.notifications import notify_role

        kind_label = {
            "vacation": "🌴 Vacances",
            "sick": "🤒 Maladie",
            "personal": "📋 Absence personnelle",
        }.get(body.kind, "Congé")
        from datetime import datetime as _dt

        def _fmt(d: _dt) -> str:
            return d.strftime("%Y-%m-%d")

        period = (
            _fmt(body.start_at)
            if body.start_at.date() == body.end_at.date()
            else f"{_fmt(body.start_at)} → {_fmt(body.end_at)}"
        )
        await notify_role(
            db,
            min_role="manager",
            kind="leave.requested",
            title=f"Demande de congé : {emp.full_name}",
            body=f"{kind_label} · {period}"
            + (f" — {lr.reason}" if lr.reason else ""),
            href="/app/conges",
        )
    except Exception:
        pass

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


# ---------- Tâches assignées à l'employé ----------

class TaskMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    project_name: Optional[str] = None
    phase_id: Optional[int]
    phase_name: Optional[str] = None
    title: str
    description: Optional[str]
    due_date: Optional[date] = None
    done: bool
    done_at: Optional[datetime]


@router.get("/tasks", response_model=List[TaskMini])
async def my_tasks(
    db: DBSession,
    user: CurrentUser,
    include_done: bool = False,
) -> List[TaskMini]:
    """Liste les ProjectTask dont assignee_id = id de l'employé courant.
    Par défaut on exclut les tâches cochées. Trie par due_date asc
    (null à la fin) puis par created_at."""
    from app.models.project_task import ProjectTask
    from app.models.project_phase import ProjectPhase
    from app.models.project_assignees import ProjectTaskAssignee

    emp = await _resolve_employe(db, user.email)
    if emp is None:
        return []
    # Multi-assignation : on considère tâches où l'employé est dans la
    # table de jointure OU (legacy) où assignee_id == emp.id. Un UNION
    # implicite via ProjectTask.id IN (... join ... OR legacy).
    joined_ids_stmt = select(ProjectTaskAssignee.task_id).where(
        ProjectTaskAssignee.employe_id == emp.id
    )
    stmt = select(ProjectTask).where(
        (ProjectTask.assignee_id == emp.id)
        | (ProjectTask.id.in_(joined_ids_stmt))
    )
    if not include_done:
        stmt = stmt.where(ProjectTask.done.is_(False))
    stmt = stmt.order_by(
        ProjectTask.due_date.asc().nullslast(),
        ProjectTask.created_at.asc(),
    )
    tasks = (await db.execute(stmt)).scalars().all()

    # Enrichit avec le nom du projet + phase.
    proj_ids = list({t.project_id for t in tasks})
    phase_ids = list({t.phase_id for t in tasks if t.phase_id})
    proj_names = {}
    if proj_ids:
        rows = (
            await db.execute(
                select(Project.id, Project.name).where(
                    Project.id.in_(proj_ids)
                )
            )
        ).all()
        proj_names = {r[0]: r[1] for r in rows}
    phase_names = {}
    if phase_ids:
        rows = (
            await db.execute(
                select(ProjectPhase.id, ProjectPhase.name).where(
                    ProjectPhase.id.in_(phase_ids)
                )
            )
        ).all()
        phase_names = {r[0]: r[1] for r in rows}

    out: List[TaskMini] = []
    for t in tasks:
        out.append(
            TaskMini(
                id=t.id,
                project_id=t.project_id,
                project_name=proj_names.get(t.project_id),
                phase_id=t.phase_id,
                phase_name=(
                    phase_names.get(t.phase_id) if t.phase_id else None
                ),
                title=t.title,
                description=t.description,
                due_date=t.due_date,
                done=t.done,
                done_at=t.done_at,
            )
        )
    return out


@router.post("/tasks/{task_id}/toggle", response_model=TaskMini)
async def toggle_task(
    task_id: int, db: DBSession, user: CurrentUser
) -> TaskMini:
    """Marque la tâche faite / à faire. Limité aux tâches assignées à
    l'employé (on ne veut pas qu'un ouvrier coche la tâche d'un autre)."""
    from app.models.project_task import ProjectTask
    from app.models.project_assignees import ProjectTaskAssignee

    emp = await _resolve_employe(db, user.email)
    if emp is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Aucun employé n'est lié à ce compte.",
        )
    t = (
        await db.execute(
            select(ProjectTask).where(ProjectTask.id == task_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Tâche introuvable."
        )
    # Autorise tout assigné (legacy primaire OU table de jointure).
    is_primary = t.assignee_id == emp.id
    is_coassignee = False
    if not is_primary:
        is_coassignee = (
            await db.execute(
                select(ProjectTaskAssignee.id).where(
                    ProjectTaskAssignee.task_id == task_id,
                    ProjectTaskAssignee.employe_id == emp.id,
                )
            )
        ).scalar_one_or_none() is not None
    if not is_primary and not is_coassignee:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Tâche introuvable."
        )
    from datetime import datetime as _dt, timezone as _tz

    if t.done:
        t.done = False
        t.done_at = None
    else:
        t.done = True
        t.done_at = _dt.now(_tz.utc)
    await db.flush()
    await db.refresh(t)
    return TaskMini(
        id=t.id,
        project_id=t.project_id,
        phase_id=t.phase_id,
        title=t.title,
        description=t.description,
        due_date=t.due_date,
        done=t.done,
        done_at=t.done_at,
    )


# ---------- Projets assignés à l'employé ----------

class ProjectMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    address: Optional[str]
    status: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None


@router.get("/projects", response_model=List[ProjectMini])
async def my_projects(
    db: DBSession, user: CurrentUser
) -> List[ProjectMini]:
    """Projets où l'employé est impliqué : membre formel
    (ProjectMember via User.email ↔ Employe.email) OU assigné sur au
    moins une phase du projet OU sur au moins un AgendaEvent du projet."""
    from app.models.project_member import ProjectMember
    from app.models.project_phase import ProjectPhase
    from app.models.project_task import ProjectTask

    emp = await _resolve_employe(db, user.email)
    project_ids: set[int] = set()

    # Membres du projet (via User → ProjectMember)
    if user.email:
        from app.models.user import User as UserModel

        u = (
            await db.execute(
                select(UserModel).where(
                    func.lower(UserModel.email) == user.email.lower()
                )
            )
        ).scalar_one_or_none()
        if u:
            rows = (
                await db.execute(
                    select(ProjectMember.project_id).where(
                        ProjectMember.user_id == u.id
                    )
                )
            ).all()
            project_ids.update(int(r[0]) for r in rows)

    if emp:
        from app.models.project_assignees import (
            ProjectPhaseAssignee,
            ProjectTaskAssignee,
        )

        # Phases dont l'employé fait partie des assignés (legacy +
        # table de jointure multi-personnes).
        rows = (
            await db.execute(
                select(ProjectPhase.project_id).where(
                    ProjectPhase.assignee_employe_id == emp.id
                )
            )
        ).all()
        project_ids.update(int(r[0]) for r in rows)
        rows = (
            await db.execute(
                select(ProjectPhase.project_id)
                .join(
                    ProjectPhaseAssignee,
                    ProjectPhaseAssignee.phase_id == ProjectPhase.id,
                )
                .where(ProjectPhaseAssignee.employe_id == emp.id)
            )
        ).all()
        project_ids.update(int(r[0]) for r in rows)

        # Tâches assignées via la table de jointure — on capte leur
        # projet pour qu'une tâche seule fasse aussi remonter le
        # chantier dans la liste mobile.
        rows = (
            await db.execute(
                select(ProjectTask.project_id)
                .join(
                    ProjectTaskAssignee,
                    ProjectTaskAssignee.task_id == ProjectTask.id,
                )
                .where(ProjectTaskAssignee.employe_id == emp.id)
            )
        ).all()
        project_ids.update(int(r[0]) for r in rows)

        # AgendaEvents dont l'assignee est cet employé → on capte le projet
        rows = (
            await db.execute(
                select(AgendaEvent.project_id).where(
                    AgendaEvent.assignee_id == emp.id,
                    AgendaEvent.project_id.is_not(None),
                )
            )
        ).all()
        project_ids.update(int(r[0]) for r in rows if r[0] is not None)

    if not project_ids:
        return []
    rows = (
        await db.execute(
            select(Project)
            .where(Project.id.in_(project_ids))
            .order_by(Project.created_at.desc())
        )
    ).scalars().all()
    return [ProjectMini.model_validate(p) for p in rows]
