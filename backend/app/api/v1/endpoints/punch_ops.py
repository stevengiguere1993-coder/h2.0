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

from app.api.deps import CurrentUser, DBSession
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
