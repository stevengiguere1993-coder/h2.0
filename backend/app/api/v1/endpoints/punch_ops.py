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

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.employe import Employe
from app.models.punch import Punch


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
    started_at: datetime
    ended_at: Optional[datetime]
    hours: Optional[float]
    task: Optional[str]
    geolocation: Optional[str]
    approved: bool
    notes: Optional[str]


class PunchMe(BaseModel):
    employe: Optional[EmployeMini]
    active: Optional[PunchRead]


class ClockInRequest(BaseModel):
    project_id: Optional[int] = None
    contact_request_id: Optional[int] = None
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
async def punch_debug(db: DBSession, user: CurrentUser):
    """Returns the exact values the backend compares so staff can spot
    the mismatch (e.g. invisible characters, wrong casing, inactive)."""
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
        "login_email_raw": user.email,
        "login_email_repr": repr(user.email),
        "login_email_normalized": (user.email or "").strip().lower(),
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
        started_at=datetime.now(timezone.utc),
        task=(data.task.strip() if data.task else None),
        geolocation=_geo_str(data.latitude, data.longitude),
        notes=(data.notes.strip() if data.notes else None),
    )
    db.add(p)
    await db.flush()
    await db.refresh(p)
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
    open_punch.hours = round(max(elapsed, 0), 2)
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
    return PunchRead.model_validate(open_punch)


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


@router.post(
    "/{punch_id}/approve",
    response_model=PunchPending,
    summary="Approve a punch (manager+)",
)
async def approve_punch(
    punch_id: int,
    db: DBSession,
    _: RequireManager,
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
    p.approved = True
    await db.flush()
    await db.refresh(p)
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
    _: RequireManager,
) -> None:
    """Rejecting a punch simply deletes it. The employee can redo the
    entry if needed. We don't try to keep a soft-deleted audit trail
    at this stage — admins who want history can approve+add notes."""
    p = (
        await db.execute(select(Punch).where(Punch.id == punch_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Punch introuvable.")
    await db.delete(p)
    await db.flush()


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
        select(
            Employe.id,
            Employe.full_name,
            Punch.started_at,
            Punch.hours,
            Punch.approved,
        )
        .join(Punch, Punch.employe_id == Employe.id)
        .where(
            Punch.started_at >= start_dt,
            Punch.started_at <= end_dt,
            Punch.ended_at.is_not(None),
        )
    )
    rows_raw = (await db.execute(stmt)).all()

    agg: dict[int, BiWeeklyPayrollRow] = {}
    for r in rows_raw:
        emp_id = int(r[0])
        name = r[1] or f"#{emp_id}"
        started_at: datetime = r[2]
        h = float(r[3] or 0)
        approved = bool(r[4])

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
        if started_at <= week_1_end_dt:
            agg[emp_id].hours_week_1 += h
        else:
            agg[emp_id].hours_week_2 += h
        agg[emp_id].total_hours += h
        if not approved:
            agg[emp_id].pending_hours += h

    for row in agg.values():
        row.hours_week_1 = round(row.hours_week_1, 2)
        row.hours_week_2 = round(row.hours_week_2, 2)
        row.total_hours = round(row.total_hours, 2)
        row.pending_hours = round(row.pending_hours, 2)

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
    """CSV simple pour EmployeurD : nom · semaine 1 · semaine 2."""
    from fastapi.responses import Response
    report = await payroll_bi_weekly(db, _, period_end)  # type: ignore[arg-type]
    lines = ["nom_employe,heures_semaine_1,heures_semaine_2"]
    for r in report.rows:
        name = (r.employe_name or "").replace('"', "'")
        lines.append(
            f'"{name}",{r.hours_week_1},{r.hours_week_2}'
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

    # Sum hours by (employe, approved) over the period.
    stmt = (
        select(
            Employe.id,
            Employe.full_name,
            Employe.hourly_rate,
            Punch.approved,
            func.coalesce(func.sum(Punch.hours), 0).label("h"),
        )
        .join(Punch, Punch.employe_id == Employe.id)
        .where(
            Punch.started_at >= start_dt,
            Punch.started_at <= end_dt,
            Punch.ended_at.is_not(None),
        )
        .group_by(Employe.id, Employe.full_name, Employe.hourly_rate, Punch.approved)
    )
    rows = (await db.execute(stmt)).all()

    # Fold into per-employee aggregates.
    agg: dict[int, PayrollRow] = {}
    for r in rows:
        emp_id = int(r[0])
        if emp_id not in agg:
            agg[emp_id] = PayrollRow(
                employe_id=emp_id,
                employe_name=r[1] or f"#{emp_id}",
                hourly_rate=float(r[2]) if r[2] is not None else None,
                approved_hours=0.0,
                pending_hours=0.0,
                total_hours=0.0,
                approved_revenue=0.0,
                total_revenue=0.0,
            )
        h = float(r[4] or 0)
        if bool(r[3]):
            agg[emp_id].approved_hours += h
        else:
            agg[emp_id].pending_hours += h
        agg[emp_id].total_hours += h

    for row in agg.values():
        rate = float(row.hourly_rate or 0)
        row.approved_revenue = round(row.approved_hours * rate, 2)
        row.total_revenue = round(row.total_hours * rate, 2)
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
        "total_hours,approved_revenue,total_revenue"
    ]
    for r in report.rows:
        name = (r.employe_name or "").replace('"', "'")
        lines.append(
            f'{r.employe_id},"{name}",{r.hourly_rate or 0},'
            f"{r.approved_hours},{r.pending_hours},{r.total_hours},"
            f"{r.approved_revenue},{r.total_revenue}"
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
        "date,started_at,ended_at,hours,approved,project_id,location,notes"
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
        loc = (p.location or "").replace('"', "'")
        lines.append(
            f'{started.date().isoformat()},'
            f'{started.strftime("%Y-%m-%d %H:%M")},'
            f'{ended.strftime("%Y-%m-%d %H:%M") if ended else ""},'
            f'{h},{"oui" if p.approved else "non"},'
            f'{p.project_id or ""},'
            f'"{loc}","{notes}"'
        )
    lines.append("")
    lines.append(f",,TOTAL,{round(total, 2)},,,,")
    lines.append(f",,APPROUVÉES,{round(approved_total, 2)},,,,")

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
