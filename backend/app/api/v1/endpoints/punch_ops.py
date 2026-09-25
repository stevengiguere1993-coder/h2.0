"""Mobile clock-in / clock-out operations for the Punch / Temps module.

These endpoints are designed for the /app/punch mobile page:
- GET  /api/v1/punch/me        -> current employe + active punch
- POST /api/v1/punch/clock-in  -> opens a new punch with geolocation
- POST /api/v1/punch/clock-out -> closes the active punch, computes hours
- GET  /api/v1/punch/weekly    -> weekly hours summary

The current user is matched to an Employe record by email.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession, RequireAdminRole, RequireManager
from app.models.employe import Employe
from app.models.punch import Punch
from app.services.audit import log_action
from app.services.employe_rates import (
    REGIMES,
    REGIME_CCQ,
    load_rate_periods,
    regime_effectif,
    resolve_base_rate,
)
from app.services.project_auto_status import bump_to_in_progress_if_needed


router = APIRouter(prefix="/punch", tags=["punch"])


# ---------- Schemas ----------
class EmployeMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    email: Optional[str]


class PunchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employe_id: int
    project_id: Optional[int]
    contact_request_id: Optional[int]
    bon_travail_id: Optional[int] = None
    client_id: Optional[int] = None
    started_at: datetime
    ended_at: Optional[datetime]
    hours: Optional[float]
    task: Optional[str]
    geolocation: Optional[str]
    approved: bool
    notes: Optional[str]
    #: ccq | hors_decret | None (avant la règle : suit la fiche employé).
    regime: Optional[str] = None


class PunchMe(BaseModel):
    employe: Optional[EmployeMini]
    active: Optional[PunchRead]


class ClockInRequest(BaseModel):
    project_id: Optional[int] = None
    contact_request_id: Optional[int] = None
    # Pointer le punch sur un bon de travail interne (entretien d'immeuble).
    bon_travail_id: Optional[int] = None
    task: Optional[str] = Field(default=None, max_length=255)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notes: Optional[str] = None


class ClockOutRequest(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notes: Optional[str] = None


class WeeklyEntry(BaseModel):
    day: date
    hours: float


class WeeklyReport(BaseModel):
    employe_id: int
    week_start: date
    week_end: date
    total_hours: float
    days: list[WeeklyEntry]


# ---------- Helpers ----------
async def _find_employe_for_user(db, email: str) -> Optional[Employe]:
    """Find the Employe row matching the user's login email.

    Match is tolerant to case and stray whitespace on either side of
    the stored email. Only active fiches are eligible.
    """
    if not email:
        return None
    target = email.strip().lower()
    if not target:
        return None
    row = (
        await db.execute(
            select(Employe).where(
                func.lower(func.trim(Employe.email)) == target,
                Employe.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    return row


async def _active_punch(db, employe_id: int) -> Optional[Punch]:
    return (
        await db.execute(
            select(Punch)
            .where(Punch.employe_id == employe_id, Punch.ended_at.is_(None))
            .order_by(Punch.started_at.desc())
        )
    ).scalars().first()


def _geo_str(lat: Optional[float], lng: Optional[float]) -> Optional[str]:
    if lat is None or lng is None:
        return None
    return f"{lat:.6f},{lng:.6f}"


# ---------- Endpoints ----------
@router.get("/me", response_model=PunchMe, summary="Current employe + active punch")
async def punch_me(db: DBSession, user: CurrentUser) -> PunchMe:
    emp = await _find_employe_for_user(db, user.email)
    active = await _active_punch(db, emp.id) if emp else None
    return PunchMe(
        employe=EmployeMini.model_validate(emp) if emp else None,
        active=PunchRead.model_validate(active) if active else None,
    )


@router.get(
    "/debug",
    summary="Diagnose why /me can't find the employe fiche (admin only)",
)
async def punch_debug(db: DBSession, admin: RequireAdminRole):
    """Returns the exact values the backend compares so staff can spot
    the mismatch (e.g. invisible characters, wrong casing, inactive).

    Réservé aux admins : ce diagnostic expose les courriels (PII) des 50
    premières fiches employé — ne doit pas être accessible à un employé
    standard."""
    candidates = (
        await db.execute(select(Employe).limit(50))
    ).scalars().all()
    rows = [
        {
            "id": e.id,
            "full_name": e.full_name,
            "email_raw": e.email,
            "email_len": len(e.email) if e.email else 0,
            "email_repr": repr(e.email),
            "active": e.active,
        }
        for e in candidates
    ]
    return {
        "login_email_raw": admin.email,
        "login_email_repr": repr(admin.email),
        "login_email_normalized": (admin.email or "").strip().lower(),
        "employes": rows,
    }


@router.post(
    "/clock-in",
    response_model=PunchRead,
    status_code=status.HTTP_201_CREATED,
    summary="Start a punch (clock-in)",
)
async def clock_in(
    data: ClockInRequest, db: DBSession, user: CurrentUser
) -> PunchRead:
    emp = await _find_employe_for_user(db, user.email)
    if emp is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Aucun employé actif avec ce courriel. "
                "Ajoute d'abord une fiche employé avec le même courriel "
                "que ton compte utilisateur."
            ),
        )
    open_punch = await _active_punch(db, emp.id)
    if open_punch is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un punch est déjà ouvert — termine-le avant d'en démarrer un nouveau.",
        )
    p = Punch(
        employe_id=emp.id,
        project_id=data.project_id,
        contact_request_id=data.contact_request_id,
        bon_travail_id=data.bon_travail_id,
        started_at=datetime.now(timezone.utc),
        task=(data.task.strip() if data.task else None),
        geolocation=_geo_str(data.latitude, data.longitude),
        notes=(data.notes.strip() if data.notes else None),
        # Hors décret par défaut : le régime CCQ est posé par un admin+
        # à l'approbation (retour Phil 2026-09-26).
        regime="hors_decret",
    )
    db.add(p)
    await db.flush()
    # Auto-bump : tout punch ouvert sur un projet le bascule en
    # « En cours » s'il ne l'est pas déjà (et qu'il n'est pas
    # « Livré »).
    await bump_to_in_progress_if_needed(db, p.project_id)
    await db.flush()
    await db.refresh(p)
    await log_action(
        db,
        user=user,
        action="punch.clock_in",
        entity_type="punch",
        entity_id=p.id,
        details={
            "employe_id": emp.id,
            "project_id": p.project_id,
            "started_at": p.started_at.isoformat(),
        },
    )
    return PunchRead.model_validate(p)


@router.post(
    "/clock-out",
    response_model=PunchRead,
    summary="Close the active punch (clock-out)",
)
async def clock_out(
    data: ClockOutRequest, db: DBSession, user: CurrentUser
) -> PunchRead:
    emp = await _find_employe_for_user(db, user.email)
    if emp is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun employé actif avec ce courriel.",
        )
    open_punch = await _active_punch(db, emp.id)
    if open_punch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucun punch en cours à terminer.",
        )
    now = datetime.now(timezone.utc)
    open_punch.ended_at = now
    # Compute hours = elapsed time rounded to 2 decimals.
    started = open_punch.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = (now - started).total_seconds() / 3600.0
    h = round(max(elapsed, 0), 2)
    # Tout punch réel (même très court) reste valide : on garantit au moins
    # 0,01 h (~36 s) pour ne JAMAIS enregistrer 0 h. Aucun minimum d'1 h.
    if elapsed > 0 and h <= 0:
        h = 0.01
    open_punch.hours = h
    if data.notes:
        extra = data.notes.strip()
        if extra:
            open_punch.notes = (
                f"{open_punch.notes}\n{extra}" if open_punch.notes else extra
            )
    # End-location can be appended to geolocation for audit.
    end_geo = _geo_str(data.latitude, data.longitude)
    if end_geo:
        if open_punch.geolocation:
            open_punch.geolocation = f"{open_punch.geolocation}|{end_geo}"
        else:
            open_punch.geolocation = end_geo
    await db.flush()
    await db.refresh(open_punch)
    await log_action(
        db,
        user=user,
        action="punch.clock_out",
        entity_type="punch",
        entity_id=open_punch.id,
        details={
            "employe_id": emp.id,
            "hours": float(open_punch.hours or 0),
            "ended_at": open_punch.ended_at.isoformat(),
        },
    )
    return PunchRead.model_validate(open_punch)


@router.get(
    "/diagnose",
    summary="Liste TOUS les punches sur N jours (incl. ouverts) — manager+",
)
async def punch_diagnose(
    db: DBSession,
    _: RequireManager,
    days: int = Query(default=7, ge=1, le=90),
    employe_id: Optional[int] = Query(default=None, gt=0),
    only_open: bool = Query(
        default=False,
        description="Si True, retourne uniquement les punches sans clock-out",
    ),
) -> list[dict]:
    """Vue d'audit pour retrouver les punches « invisibles » des vues
    standards (Semaine/Mois/Paie) qui filtrent `ended_at IS NOT NULL`.

    Tout punch ouvert (clock-out oublié) apparaît ici, peu importe
    l'employé. Utile quand un manager dit « j'avais un punch hier
    mais je ne le vois plus » — il s'agit presque toujours d'un
    oubli de clock-out."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(Punch, Employe.full_name)
        .join(Employe, Employe.id == Punch.employe_id)
        .where(Punch.started_at >= cutoff)
        .order_by(Punch.started_at.desc())
    )
    if employe_id is not None:
        stmt = stmt.where(Punch.employe_id == employe_id)
    if only_open:
        stmt = stmt.where(Punch.ended_at.is_(None))
    rows = (await db.execute(stmt)).all()
    out: list[dict] = []
    for p, full_name in rows:
        out.append(
            {
                "id": p.id,
                "employe_id": p.employe_id,
                "employe_name": full_name,
                "project_id": p.project_id,
                "started_at": p.started_at.isoformat(),
                "ended_at": p.ended_at.isoformat() if p.ended_at else None,
                "hours": float(p.hours) if p.hours is not None else None,
                "approved": p.approved,
                "task": p.task,
                "notes": p.notes,
                "is_open": p.ended_at is None,
            }
        )
    return out


@router.get(
    "/weekly",
    response_model=WeeklyReport,
    summary="Weekly hours summary for an employe",
)
async def weekly_report(
    db: DBSession,
    user: CurrentUser,
    week_start: Optional[date] = Query(default=None),
    employe_id: Optional[int] = Query(default=None, gt=0),
) -> WeeklyReport:
    # Determine the employe: explicit id wins (staff can inspect each
    # other); otherwise fallback to the caller's employe record.
    target_emp: Optional[Employe] = None
    if employe_id is not None:
        target_emp = (
            await db.execute(select(Employe).where(Employe.id == employe_id))
        ).scalar_one_or_none()
    else:
        target_emp = await _find_employe_for_user(db, user.email)
    if target_emp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucun employé trouvé.",
        )

    # Default to the current ISO week (Monday..Sunday).
    today = date.today()
    if week_start is None:
        week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    start_dt = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=7)

    rows = (
        await db.execute(
            select(Punch)
            .where(
                Punch.employe_id == target_emp.id,
                Punch.started_at >= start_dt,
                Punch.started_at < end_dt,
                Punch.ended_at.is_not(None),
            )
            .order_by(Punch.started_at.asc())
        )
    ).scalars().all()

    by_day: dict[date, float] = {
        week_start + timedelta(days=i): 0.0 for i in range(7)
    }
    total = 0.0
    for p in rows:
        if p.hours is None:
            continue
        key = p.started_at.astimezone(timezone.utc).date()
        if key in by_day:
            by_day[key] += float(p.hours)
            total += float(p.hours)

    return WeeklyReport(
        employe_id=target_emp.id,
        week_start=week_start,
        week_end=week_end,
        total_hours=round(total, 2),
        days=[WeeklyEntry(day=d, hours=round(h, 2)) for d, h in sorted(by_day.items())],
    )


# ---------- Approval (manager+) ----------

class PunchPending(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employe_id: int
    employe_name: Optional[str] = None
    project_id: Optional[int]
    contact_request_id: Optional[int]
    started_at: datetime
    ended_at: Optional[datetime]
    hours: Optional[float]
    task: Optional[str]
    notes: Optional[str]
    regime: Optional[str] = None


def _exiger_admin_pour_regime(user, regime: Optional[str]) -> None:
    """Le régime d'un punch (CCQ / hors décret) ne se pose que par un
    admin+ (retour Phil 2026-09-26)."""
    if regime is None:
        return
    if regime not in REGIMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Régime inconnu (ccq | hors_decret).")
    if not user.has_min_role("admin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Seul un administrateur peut poser le régime CCQ / hors décret d'un punch.",
        )


class ApproveBody(BaseModel):
    #: Régime posé à l'approbation (admin+) : ccq | hors_decret.
    regime: Optional[str] = None


@router.get(
    "/pending",
    response_model=list[PunchPending],
    summary="Closed punches awaiting approval (manager+)",
)
async def list_pending(
    db: DBSession,
    _: RequireManager,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[PunchPending]:
    # Only finished (ended_at set) and not yet approved. Open punches
    # aren't "pending approval" — they're still in progress.
    rows = (
        await db.execute(
            select(Punch, Employe.full_name)
            .join(Employe, Employe.id == Punch.employe_id)
            .where(Punch.ended_at.is_not(None), Punch.approved.is_(False))
            .order_by(Punch.started_at.desc())
            .limit(limit)
        )
    ).all()
    out: list[PunchPending] = []
    for punch, full_name in rows:
        data = PunchPending.model_validate(punch)
        data.employe_name = full_name
        out.append(data)
    return out


@router.get(
    "/pending-count",
    response_model=int,
    summary="Number of punches awaiting approval (manager+)",
)
async def pending_count(db: DBSession, _: RequireManager) -> int:
    n = (
        await db.execute(
            select(func.count(Punch.id)).where(
                Punch.ended_at.is_not(None), Punch.approved.is_(False)
            )
        )
    ).scalar_one()
    return int(n or 0)


class LiveWorker(BaseModel):
    """Une ligne de la vue temps réel « qui est où » (page Assignations).

    La source PRIMAIRE est le punch actif (vérité terrain). La planif des
    chantiers (phase du jour assignée) complète : gars prévu mais pas
    pointé, ou écart entre le chantier pointé et le chantier prévu."""

    employe_id: int
    employe_name: str
    # Punch actif — null si le gars n'est pas pointé.
    punch_started_at: Optional[datetime] = None
    punch_project_id: Optional[int] = None
    punch_project_name: Optional[str] = None
    punch_bon_id: Optional[int] = None
    punch_bon_title: Optional[str] = None
    punch_task: Optional[str] = None
    # Planif du jour (phase de chantier assignée couvrant aujourd'hui).
    planned_project_id: Optional[int] = None
    planned_project_name: Optional[str] = None
    planned_phase_name: Optional[str] = None


@router.get(
    "/live",
    response_model=list[LiveWorker],
    summary="Vue temps réel : qui est sur quel chantier (manager+)",
)
async def punch_live(db: DBSession, _: RequireManager) -> list[LiveWorker]:
    import math

    from app.models.bon_travail import BonTravail
    from app.models.project import Project
    from app.models.project_assignees import ProjectPhaseAssignee
    from app.models.project_phase import ProjectPhase

    today = date.today()

    emps = (
        await db.execute(select(Employe).where(Employe.active.is_(True)))
    ).scalars().all()
    emp_names = {e.id: e.full_name for e in emps}

    # Punchs ouverts (vérité terrain).
    open_punches = (
        await db.execute(select(Punch).where(Punch.ended_at.is_(None)))
    ).scalars().all()
    punch_by_emp = {p.employe_id: p for p in open_punches if p.employe_id}

    # Planif du jour : phases dont la fenêtre couvre aujourd'hui.
    phases = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.start_date.is_not(None),
                ProjectPhase.start_date <= today,
            )
        )
    ).scalars().all()
    active_phases = []
    for ph in phases:
        days = max(math.ceil(float(ph.duration_days or 1)), 1)
        if ph.start_date + timedelta(days=days - 1) >= today:
            active_phases.append(ph)

    planned_by_emp: dict = {}
    ph_by_id = {ph.id: ph for ph in active_phases}
    if active_phases:
        links = (
            await db.execute(
                select(
                    ProjectPhaseAssignee.phase_id,
                    ProjectPhaseAssignee.employe_id,
                ).where(
                    ProjectPhaseAssignee.phase_id.in_(list(ph_by_id)),
                    ProjectPhaseAssignee.employe_id.is_not(None),
                )
            )
        ).all()
        for phid, emp_id in links:
            planned_by_emp.setdefault(emp_id, ph_by_id[phid])
    for ph in active_phases:
        if ph.assignee_employe_id:
            planned_by_emp.setdefault(ph.assignee_employe_id, ph)

    # Résolution des libellés en une passe.
    proj_ids = {p.project_id for p in open_punches if p.project_id}
    proj_ids |= {ph.project_id for ph in planned_by_emp.values()}
    proj_names: dict = {}
    if proj_ids:
        rows = (
            await db.execute(
                select(Project.id, Project.name).where(
                    Project.id.in_(proj_ids)
                )
            )
        ).all()
        proj_names = {r[0]: r[1] for r in rows}
    bon_ids = {p.bon_travail_id for p in open_punches if p.bon_travail_id}
    bon_titles: dict = {}
    if bon_ids:
        rows = (
            await db.execute(
                select(BonTravail.id, BonTravail.title).where(
                    BonTravail.id.in_(bon_ids)
                )
            )
        ).all()
        bon_titles = {r[0]: r[1] for r in rows}

    out: list[LiveWorker] = []
    for emp_id, name in emp_names.items():
        p = punch_by_emp.get(emp_id)
        planned = planned_by_emp.get(emp_id)
        if p is None and planned is None:
            continue
        out.append(
            LiveWorker(
                employe_id=emp_id,
                employe_name=name,
                punch_started_at=p.started_at if p else None,
                punch_project_id=p.project_id if p else None,
                punch_project_name=(
                    proj_names.get(p.project_id) if p and p.project_id else None
                ),
                punch_bon_id=p.bon_travail_id if p else None,
                punch_bon_title=(
                    bon_titles.get(p.bon_travail_id)
                    if p and p.bon_travail_id
                    else None
                ),
                punch_task=p.task if p else None,
                planned_project_id=planned.project_id if planned else None,
                planned_project_name=(
                    proj_names.get(planned.project_id) if planned else None
                ),
                planned_phase_name=planned.name if planned else None,
            )
        )
    # Pointés d'abord, puis prévus non pointés, alphabétique dans chaque
    # groupe.
    out.sort(
        key=lambda w: (w.punch_started_at is None, w.employe_name.lower())
    )
    return out


@router.post(
    "/{punch_id}/approve",
    response_model=PunchPending,
    summary="Approve a punch (manager+)",
)
async def approve_punch(
    punch_id: int,
    db: DBSession,
    user: RequireManager,
    data: Optional[ApproveBody] = None,
) -> PunchPending:
    p = (
        await db.execute(select(Punch).where(Punch.id == punch_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Punch introuvable.")
    if p.ended_at is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Impossible d'approuver un punch encore ouvert.",
        )
    if data is not None and data.regime is not None:
        _exiger_admin_pour_regime(user, data.regime)
        p.regime = data.regime
    p.approved = True
    await db.flush()
    await db.refresh(p)
    await log_action(
        db,
        user=user,
        action="punch.approved",
        entity_type="punch",
        entity_id=p.id,
        details={"employe_id": p.employe_id, "hours": float(p.hours or 0), "regime": p.regime},
    )
    # Heures approuvées + projet → feuille de temps QB (TimeActivity) en
    # arrière-plan : suivi de projet/rentabilité SANS écriture comptable
    # (la paie est déjà au grand livre). Best-effort ; le filet horaire
    # (qbo_nets) rattrape tout échec.
    if p.project_id:
        import asyncio as _asyncio

        from app.services.labour_time_qbo import push_punch_time_now

        _asyncio.create_task(push_punch_time_now(int(p.id)))
    emp = (
        await db.execute(select(Employe).where(Employe.id == p.employe_id))
    ).scalar_one_or_none()
    data = PunchPending.model_validate(p)
    if emp:
        data.employe_name = emp.full_name
    return data


@router.post(
    "/{punch_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a punch (reject) — manager+",
)
async def reject_punch(
    punch_id: int,
    db: DBSession,
    user: RequireManager,
) -> None:
    """Rejecting a punch simply deletes it. Le journal d'audit garde
    la trace de qui a rejeté quoi et quand."""
    p = (
        await db.execute(select(Punch).where(Punch.id == punch_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Punch introuvable.")
    await log_action(
        db,
        user=user,
        action="punch.rejected",
        entity_type="punch",
        entity_id=p.id,
        details={
            "employe_id": p.employe_id,
            "project_id": p.project_id,
            "started_at": p.started_at.isoformat() if p.started_at else None,
            "ended_at": p.ended_at.isoformat() if p.ended_at else None,
            "hours": float(p.hours) if p.hours is not None else None,
        },
    )
    # Capture l'id de la feuille de temps QB AVANT le delete pour retirer
    # aussi les heures du suivi de projet QuickBooks (miroir).
    _ta_id = (getattr(p, "qbo_time_activity_id", None) or "").strip()
    await db.delete(p)
    await db.flush()
    if _ta_id:
        import asyncio as _asyncio

        from app.services.labour_time_qbo import delete_time_activity_now

        _asyncio.create_task(delete_time_activity_now(_ta_id))


# ---------- Payroll monthly report (manager+) ----------

class PayrollRow(BaseModel):
    employe_id: int
    employe_name: str
    hourly_rate: Optional[float]
    approved_hours: float
    pending_hours: float
    total_hours: float
    approved_revenue: float
    total_revenue: float
    # Ventilation CCQ / hors décret (2026-09-26). Les montants sont au
    # taux de base du régime en vigueur à la date de chaque punch.
    hours_ccq: float = 0.0
    hours_hors_decret: float = 0.0
    montant_ccq: float = 0.0
    montant_hors_decret: float = 0.0


class PayrollReport(BaseModel):
    month: str  # "YYYY-MM"
    period_start: date
    period_end: date
    rows: list[PayrollRow]
    total_approved_hours: float
    total_approved_revenue: float


def _month_bounds(month: str) -> tuple[date, date]:
    """Return (first day, last day) for a YYYY-MM string."""
    y, m = month.split("-")
    year = int(y)
    month_num = int(m)
    start = date(year, month_num, 1)
    if month_num == 12:
        next_start = date(year + 1, 1, 1)
    else:
        next_start = date(year, month_num + 1, 1)
    end = next_start - timedelta(days=1)
    return start, end


# ---------------------------------------------------------------------------
# Bi-weekly payroll period helpers
# ---------------------------------------------------------------------------

# Date d'ancrage : un jeudi/mercredi de paie connu chez Horizon. Toutes
# les autres périodes se calculent en sautant +/- 14 jours à partir de
# cette ancre. Pour Horizon Services Immobiliers :
#   - Versement (PAY_DATE) : 7 mai 2026 (mercredi)
#   - Coupure (CUTOFF)     : 5 mai 2026 (lundi, J-2)
#   - Période              : 19 avril → 2 mai (samedi → vendredi)
PAYROLL_ANCHOR_PAY_DATE = date(2026, 5, 7)
PAYROLL_ANCHOR_PERIOD_END = date(2026, 5, 2)  # vendredi de fin de période
PAYROLL_PERIOD_DAYS = 14


def _bi_weekly_period_for(period_end: date) -> tuple[date, date, date, date]:
    """Pour une fin de période donnée (ou la plus proche), renvoie
    (period_start, period_end, cutoff_date, pay_date) en alignant sur
    l'ancre Horizon (cycle de 14 jours samedi→vendredi)."""
    delta = (period_end - PAYROLL_ANCHOR_PERIOD_END).days
    # Aligne sur la grille de 14 jours
    cycles = round(delta / PAYROLL_PERIOD_DAYS)
    aligned_end = PAYROLL_ANCHOR_PERIOD_END + timedelta(
        days=cycles * PAYROLL_PERIOD_DAYS
    )
    aligned_start = aligned_end - timedelta(days=PAYROLL_PERIOD_DAYS - 1)
    cutoff = aligned_end + timedelta(days=3)  # vendredi + 3 = lundi
    pay = aligned_end + timedelta(days=5)  # vendredi + 5 = mercredi
    return aligned_start, aligned_end, cutoff, pay


def _next_period_end(today: Optional[date] = None) -> date:
    """Renvoie la fin de la prochaine période de paie à venir (ou en
    cours si on est entre période_end et pay_date)."""
    today = today or date.today()
    delta = (today - PAYROLL_ANCHOR_PERIOD_END).days
    cycles = delta // PAYROLL_PERIOD_DAYS
    candidate = PAYROLL_ANCHOR_PERIOD_END + timedelta(
        days=cycles * PAYROLL_PERIOD_DAYS
    )
    # Si on a déjà passé la date de versement (period_end + 5j), on
    # affiche la prochaine période. Sinon on reste sur la courante.
    if today > candidate + timedelta(days=5):
        candidate = candidate + timedelta(days=PAYROLL_PERIOD_DAYS)
    return candidate


class BiWeeklyPayrollRow(BaseModel):
    employe_id: int
    employe_name: str
    hours_week_1: float  # samedi → vendredi (semaine 1 de la période)
    hours_week_2: float  # samedi → vendredi (semaine 2 de la période)
    total_hours: float
    pending_hours: float  # heures non encore approuvées (info utile)
    # Ventilation CCQ / hors décret (retour Phil 2026-09-26) : heures et
    # montants au taux de BASE du régime en vigueur à la date du punch
    # (sans primes CNESST/CCQ, qui sont des cotisations employeur).
    hours_ccq: float = 0.0
    hours_hors_decret: float = 0.0
    hours_ccq_week_1: float = 0.0
    hours_ccq_week_2: float = 0.0
    montant_ccq: float = 0.0
    montant_hors_decret: float = 0.0
    montant_total: float = 0.0


class BiWeeklyPayrollReport(BaseModel):
    period_start: date  # samedi
    week_1_end: date  # vendredi de fin de semaine 1
    week_2_start: date  # samedi de début de semaine 2
    period_end: date  # vendredi
    cutoff_date: date  # date limite pour ajustements (lundi)
    pay_date: date  # date du versement (mercredi)
    days_until_cutoff: int  # peut être négatif (coupure dépassée)
    days_until_pay: int
    rows: list[BiWeeklyPayrollRow]
    total_hours: float
    total_pending_hours: float
    total_hours_ccq: float = 0.0
    total_hours_hors_decret: float = 0.0
    total_montant_ccq: float = 0.0
    total_montant_hors_decret: float = 0.0
    total_montant: float = 0.0


@router.get(
    "/payroll/bi-weekly",
    response_model=BiWeeklyPayrollReport,
    summary="Bi-weekly payroll report (manager+)",
)
async def payroll_bi_weekly(
    db: DBSession,
    _: RequireManager,
    period_end: Optional[str] = Query(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description=(
            "Fin de période (vendredi). Si omis, période en cours / à venir."
        ),
    ),
) -> BiWeeklyPayrollReport:
    today = date.today()
    if period_end:
        try:
            target_end = date.fromisoformat(period_end)
        except ValueError:
            target_end = _next_period_end(today)
    else:
        target_end = _next_period_end(today)

    p_start, p_end, cutoff, pay = _bi_weekly_period_for(target_end)
    week_1_end = p_start + timedelta(days=6)  # premier vendredi
    week_2_start = p_start + timedelta(days=7)  # deuxième samedi

    start_dt = datetime(
        p_start.year, p_start.month, p_start.day, tzinfo=timezone.utc
    )
    week_1_end_dt = datetime(
        week_1_end.year,
        week_1_end.month,
        week_1_end.day,
        23, 59, 59,
        tzinfo=timezone.utc,
    )
    end_dt = datetime(
        p_end.year, p_end.month, p_end.day, 23, 59, 59, tzinfo=timezone.utc
    )

    # Une seule query qui ramène tous les punches ; on ventile en
    # mémoire entre semaine 1 et semaine 2 selon la date de début du
    # punch.
    stmt = (
        select(Employe, Punch)
        .join(Punch, Punch.employe_id == Employe.id)
        .where(
            Punch.started_at >= start_dt,
            Punch.started_at <= end_dt,
            Punch.ended_at.is_not(None),
        )
    )
    rows_raw = (await db.execute(stmt)).all()
    periods = await load_rate_periods(db, [r[0].id for r in rows_raw])

    agg: dict[int, BiWeeklyPayrollRow] = {}
    for r in rows_raw:
        emp: Employe = r[0]
        p: Punch = r[1]
        emp_id = int(emp.id)
        name = emp.full_name or f"#{emp_id}"
        started_at: datetime = p.started_at
        if started_at is not None and started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        h = float(p.hours or 0)
        approved = bool(p.approved)
        pdate = started_at.date() if started_at is not None else None
        reg = regime_effectif(periods.get(emp_id, []), pdate, emp, p.regime)
        taux = resolve_base_rate(periods.get(emp_id, []), pdate, emp, reg) or 0.0
        montant = round(h * taux, 2)

        if emp_id not in agg:
            agg[emp_id] = BiWeeklyPayrollRow(
                employe_id=emp_id,
                employe_name=name,
                hours_week_1=0.0,
                hours_week_2=0.0,
                total_hours=0.0,
                pending_hours=0.0,
            )
        # Note: les heures non-approuvées sont quand même comptées dans
        # week_1/week_2 (sinon elles disparaîtraient). pending_hours est
        # un total parallèle pour signaler à l'utilisateur ce qui reste
        # à approuver avant la coupure.
        sem1 = started_at <= week_1_end_dt
        if sem1:
            agg[emp_id].hours_week_1 += h
        else:
            agg[emp_id].hours_week_2 += h
        agg[emp_id].total_hours += h
        if not approved:
            agg[emp_id].pending_hours += h
        if reg == REGIME_CCQ:
            agg[emp_id].hours_ccq += h
            agg[emp_id].montant_ccq += montant
            if sem1:
                agg[emp_id].hours_ccq_week_1 += h
            else:
                agg[emp_id].hours_ccq_week_2 += h
        else:
            agg[emp_id].hours_hors_decret += h
            agg[emp_id].montant_hors_decret += montant
        agg[emp_id].montant_total += montant

    for row in agg.values():
        for champ in (
            "hours_week_1", "hours_week_2", "total_hours", "pending_hours",
            "hours_ccq", "hours_hors_decret", "hours_ccq_week_1", "hours_ccq_week_2",
            "montant_ccq", "montant_hors_decret", "montant_total",
        ):
            setattr(row, champ, round(getattr(row, champ), 2))

    sorted_rows = sorted(agg.values(), key=lambda x: x.employe_name.lower())

    return BiWeeklyPayrollReport(
        period_start=p_start,
        week_1_end=week_1_end,
        week_2_start=week_2_start,
        period_end=p_end,
        cutoff_date=cutoff,
        pay_date=pay,
        days_until_cutoff=(cutoff - today).days,
        days_until_pay=(pay - today).days,
        rows=sorted_rows,
        total_hours=round(sum(r.total_hours for r in sorted_rows), 2),
        total_pending_hours=round(
            sum(r.pending_hours for r in sorted_rows), 2
        ),
        total_hours_ccq=round(sum(r.hours_ccq for r in sorted_rows), 2),
        total_hours_hors_decret=round(sum(r.hours_hors_decret for r in sorted_rows), 2),
        total_montant_ccq=round(sum(r.montant_ccq for r in sorted_rows), 2),
        total_montant_hors_decret=round(sum(r.montant_hors_decret for r in sorted_rows), 2),
        total_montant=round(sum(r.montant_total for r in sorted_rows), 2),
    )


@router.get(
    "/payroll/bi-weekly.csv",
    summary="Bi-weekly payroll CSV export — format EmployeurD (manager+)",
)
async def payroll_bi_weekly_csv(
    db: DBSession,
    _: RequireManager,
    period_end: Optional[str] = Query(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
):
    """CSV pour EmployeurD : nom · semaine 1 · semaine 2, puis la
    ventilation CCQ / hors décret (heures et montants au taux de base)."""
    from fastapi.responses import Response
    report = await payroll_bi_weekly(db, _, period_end)  # type: ignore[arg-type]
    lines = [
        "nom_employe,heures_semaine_1,heures_semaine_2,"
        "heures_ccq,heures_hors_decret,heures_ccq_semaine_1,heures_ccq_semaine_2,"
        "montant_ccq,montant_hors_decret,montant_total"
    ]
    for r in report.rows:
        name = (r.employe_name or "").replace('"', "'")
        lines.append(
            f'"{name}",{r.hours_week_1},{r.hours_week_2},'
            f"{r.hours_ccq},{r.hours_hors_decret},{r.hours_ccq_week_1},{r.hours_ccq_week_2},"
            f"{r.montant_ccq},{r.montant_hors_decret},{r.montant_total}"
        )
    body = "\n".join(lines)
    filename = (
        f"paie-{report.period_start.isoformat()}_au_"
        f"{report.period_end.isoformat()}.csv"
    )
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.get(
    "/payroll",
    response_model=PayrollReport,
    summary="Monthly payroll report by employee (manager+)",
)
async def payroll_report(
    db: DBSession,
    _: RequireManager,
    month: Optional[str] = Query(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="YYYY-MM, defaults to current month",
    ),
) -> PayrollReport:
    today = date.today()
    if not month:
        month = f"{today.year:04d}-{today.month:02d}"
    start, end = _month_bounds(month)
    start_dt = datetime(
        start.year, start.month, start.day, tzinfo=timezone.utc
    )
    end_dt = datetime(
        end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc
    )

    # Punch par punch : le montant suit le taux de base du RÉGIME (CCQ /
    # hors décret) en vigueur à la date du punch (2026-09-26).
    stmt = (
        select(Employe, Punch)
        .join(Punch, Punch.employe_id == Employe.id)
        .where(
            Punch.started_at >= start_dt,
            Punch.started_at <= end_dt,
            Punch.ended_at.is_not(None),
        )
    )
    rows = (await db.execute(stmt)).all()
    periods = await load_rate_periods(db, [r[0].id for r in rows])

    # Fold into per-employee aggregates.
    agg: dict[int, PayrollRow] = {}
    for r in rows:
        emp: Employe = r[0]
        p: Punch = r[1]
        emp_id = int(emp.id)
        if emp_id not in agg:
            agg[emp_id] = PayrollRow(
                employe_id=emp_id,
                employe_name=emp.full_name or f"#{emp_id}",
                hourly_rate=float(emp.hourly_rate) if emp.hourly_rate is not None else None,
                approved_hours=0.0,
                pending_hours=0.0,
                total_hours=0.0,
                approved_revenue=0.0,
                total_revenue=0.0,
            )
        h = float(p.hours or 0)
        pdate = p.started_at.date() if p.started_at is not None else None
        reg = regime_effectif(periods.get(emp_id, []), pdate, emp, p.regime)
        taux = resolve_base_rate(periods.get(emp_id, []), pdate, emp, reg) or 0.0
        montant = round(h * taux, 2)
        if bool(p.approved):
            agg[emp_id].approved_hours += h
            agg[emp_id].approved_revenue += montant
        else:
            agg[emp_id].pending_hours += h
        agg[emp_id].total_hours += h
        agg[emp_id].total_revenue += montant
        if reg == REGIME_CCQ:
            agg[emp_id].hours_ccq += h
            agg[emp_id].montant_ccq += montant
        else:
            agg[emp_id].hours_hors_decret += h
            agg[emp_id].montant_hors_decret += montant

    for row in agg.values():
        row.approved_revenue = round(row.approved_revenue, 2)
        row.total_revenue = round(row.total_revenue, 2)
        row.hours_ccq = round(row.hours_ccq, 2)
        row.hours_hors_decret = round(row.hours_hors_decret, 2)
        row.montant_ccq = round(row.montant_ccq, 2)
        row.montant_hors_decret = round(row.montant_hors_decret, 2)
        # Round hours for display consistency.
        row.approved_hours = round(row.approved_hours, 2)
        row.pending_hours = round(row.pending_hours, 2)
        row.total_hours = round(row.total_hours, 2)

    sorted_rows = sorted(agg.values(), key=lambda x: x.employe_name.lower())

    return PayrollReport(
        month=month,
        period_start=start,
        period_end=end,
        rows=sorted_rows,
        total_approved_hours=round(
            sum(r.approved_hours for r in sorted_rows), 2
        ),
        total_approved_revenue=round(
            sum(r.approved_revenue for r in sorted_rows), 2
        ),
    )


@router.get(
    "/payroll.csv",
    summary="Monthly payroll report (CSV for accounting)",
)
async def payroll_csv(
    db: DBSession,
    _: RequireManager,
    month: Optional[str] = Query(
        default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"
    ),
):
    from fastapi.responses import Response
    report = await payroll_report(db, _, month)  # type: ignore[arg-type]
    lines = [
        "employe_id,employe_name,hourly_rate,approved_hours,pending_hours,"
        "total_hours,approved_revenue,total_revenue,"
        "hours_ccq,hours_hors_decret,montant_ccq,montant_hors_decret"
    ]
    for r in report.rows:
        name = (r.employe_name or "").replace('"', "'")
        lines.append(
            f'{r.employe_id},"{name}",{r.hourly_rate or 0},'
            f"{r.approved_hours},{r.pending_hours},{r.total_hours},"
            f"{r.approved_revenue},{r.total_revenue},"
            f"{r.hours_ccq},{r.hours_hors_decret},{r.montant_ccq},{r.montant_hors_decret}"
        )
    lines.append("")
    lines.append(
        f",,TOTAUX,{report.total_approved_hours},,,"
        f"{report.total_approved_revenue},"
    )
    body = "\n".join(lines)
    filename = f"paie-{report.month}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.get(
    "/employe/{employe_id}/punches.csv",
    summary="Per-employee monthly punch detail (manager+)",
)
async def employe_monthly_csv(
    employe_id: int,
    db: DBSession,
    _: RequireManager,
    month: Optional[str] = Query(
        default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"
    ),
):
    """Export every individual punch (not aggregated) for one employee
    over the given month — useful for a CNESST audit or a detailed
    timesheet to hand to the employee."""
    from fastapi.responses import Response

    today = date.today()
    if not month:
        month = f"{today.year:04d}-{today.month:02d}"
    start, end = _month_bounds(month)
    start_dt = datetime(
        start.year, start.month, start.day, tzinfo=timezone.utc
    )
    end_dt = datetime(
        end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc
    )

    emp = (
        await db.execute(select(Employe).where(Employe.id == employe_id))
    ).scalar_one_or_none()
    if emp is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Employé introuvable."
        )

    rows = (
        await db.execute(
            select(Punch)
            .where(
                Punch.employe_id == employe_id,
                Punch.started_at >= start_dt,
                Punch.started_at <= end_dt,
                Punch.ended_at.is_not(None),
            )
            .order_by(Punch.started_at.asc())
        )
    ).scalars().all()

    lines = [
        "date,started_at,ended_at,hours,approved,regime,project_id,location,notes"
    ]
    total = 0.0
    approved_total = 0.0
    for p in rows:
        started = p.started_at.astimezone(timezone.utc)
        ended = p.ended_at.astimezone(timezone.utc) if p.ended_at else None
        h = float(p.hours or 0)
        total += h
        if p.approved:
            approved_total += h
        notes = (p.notes or "").replace('"', "'").replace("\n", " ")[:200]
        loc = (p.geolocation or "").replace('"', "'")
        lines.append(
            f'{started.date().isoformat()},'
            f'{started.strftime("%Y-%m-%d %H:%M")},'
            f'{ended.strftime("%Y-%m-%d %H:%M") if ended else ""},'
            f'{h},{"oui" if p.approved else "non"},'
            f'{p.regime or "fiche"},'
            f'{p.project_id or ""},'
            f'"{loc}","{notes}"'
        )
    lines.append("")
    lines.append(f",,TOTAL,{round(total, 2)},,,,,")
    lines.append(f",,APPROUVÉES,{round(approved_total, 2)},,,,,")

    body = "\n".join(lines)
    safe_name = (emp.full_name or f"employe-{emp.id}").replace(
        " ", "-"
    ).lower()
    filename = f"punches-{safe_name}-{month}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


# ---------- Saisie manuelle (admin / gestion) ----------
class PunchManualCreate(BaseModel):
    employe_id: int
    project_id: Optional[int] = None
    contact_request_id: Optional[int] = None
    # Heures pointées sur un bon de travail / un client direct — mêmes
    # cibles que la gestion admin (sans ces champs, choisir un bon dans
    # le modal admin retombait en « Administration » en silence).
    bon_travail_id: Optional[int] = None
    client_id: Optional[int] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    hours: Optional[float] = None
    task: Optional[str] = None
    notes: Optional[str] = None
    approved: bool = False
    #: ccq | hors_decret (admin+) ; vide = hors décret.
    regime: Optional[str] = None


class PunchManualUpdate(BaseModel):
    employe_id: Optional[int] = None
    project_id: Optional[int] = None
    contact_request_id: Optional[int] = None
    bon_travail_id: Optional[int] = None
    client_id: Optional[int] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    hours: Optional[float] = None
    task: Optional[str] = None
    notes: Optional[str] = None
    approved: Optional[bool] = None
    #: ccq | hors_decret (admin+ seulement).
    regime: Optional[str] = None


def _hours_between(start, end):
    if not start or not end:
        return None
    delta = (end - start).total_seconds() / 3600.0
    return round(delta, 2) if delta > 0 else None


@router.post(
    "",
    response_model=PunchRead,
    status_code=status.HTTP_201_CREATED,
    summary="Creer un punch manuellement (gestion admin)",
)
async def create_manual_punch(
    data: PunchManualCreate, db: DBSession, user: RequireManager
) -> PunchRead:
    _exiger_admin_pour_regime(user, data.regime)
    hours = (
        data.hours
        if data.hours is not None
        else _hours_between(data.started_at, data.ended_at)
    )
    p = Punch(
        employe_id=data.employe_id,
        project_id=data.project_id,
        contact_request_id=data.contact_request_id,
        bon_travail_id=data.bon_travail_id,
        client_id=data.client_id,
        started_at=data.started_at,
        ended_at=data.ended_at,
        hours=hours,
        task=(data.task or None),
        notes=(data.notes or None),
        approved=bool(data.approved),
        regime=(data.regime or "hors_decret"),
    )
    db.add(p)
    await db.flush()
    await db.refresh(p)
    if p.project_id:
        try:
            await bump_to_in_progress_if_needed(db, p.project_id)
        except Exception:  # noqa: BLE001
            pass
    return PunchRead.model_validate(p)


@router.patch(
    "/{punch_id}",
    response_model=PunchRead,
    summary="Modifier un punch (gestion admin, incl. approuve)",
)
async def update_manual_punch(
    punch_id: int, data: PunchManualUpdate, db: DBSession, user: RequireManager
) -> PunchRead:
    p = (
        await db.execute(select(Punch).where(Punch.id == punch_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Punch introuvable.")
    fields = data.model_dump(exclude_unset=True)
    if "regime" in fields:
        if fields["regime"] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Régime requis (ccq | hors_decret).")
        _exiger_admin_pour_regime(user, fields["regime"])
    for k, v in fields.items():
        if k in ("task", "notes") and v == "":
            v = None
        setattr(p, k, v)
    if "hours" not in fields and p.started_at and p.ended_at:
        recomputed = _hours_between(p.started_at, p.ended_at)
        if recomputed is not None:
            p.hours = recomputed
    await db.flush()
    await db.refresh(p)
    return PunchRead.model_validate(p)
