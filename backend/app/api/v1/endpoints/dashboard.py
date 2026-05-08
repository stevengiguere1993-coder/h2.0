"""Dashboard KPIs shown on the /app home page.

Lightweight aggregate queries that roll up the current state of the
business in a single response. Accepts optional `start_date` / `end_date`
(ISO yyyy-mm-dd) to scope the period; defaults to the current month.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import cast, Date, func, select

from app.api.deps import CurrentUser, DBSession
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.facture import Facture, FactureStatus
from app.models.project import Project, ProjectStatus
from app.models.punch import Punch
from app.models.soumission import Soumission, SoumissionStatus


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class TimeseriesPoint(BaseModel):
    date: date
    soumissions: float  # $ envoyées ce jour
    ventes: float       # $ facturé (ou payé) ce jour


class KpiResponse(BaseModel):
    # Period (echoed back so the UI can render the range used)
    start_date: date
    end_date: date

    # Money / cash flow
    unpaid_total: float
    unpaid_count: int
    overdue_total: float
    overdue_count: int
    revenue_this_month: float
    revenue_this_month_mode: str  # "paid" | "issued"

    # New KPIs (PlanOps parity)
    prospects_count: int
    soumissions_sent_total: float
    soumissions_sent_count: int
    ventes_total: float
    ventes_count: int
    conversion_rate: float     # % (accepted / sent)
    avg_transaction: float     # $ moyen par vente
    time_to_sale_days: float   # jours entre contact_request et soumission.accepted_at

    # Ops
    active_projects: int
    hours_this_week: float
    new_prospects_7d: int

    # Pipeline (legacy, still used on /app home)
    open_soumissions_count: int
    open_soumissions_total: float

    # Chart
    timeseries: list[TimeseriesPoint]


def _parse_date(value: Optional[str], default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default


def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _week_start_utc() -> datetime:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


@router.get(
    "/kpis",
    response_model=KpiResponse,
    summary="Aggregate KPIs for the /app home dashboard",
)
async def get_kpis(
    db: DBSession,
    _: CurrentUser,
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
) -> KpiResponse:
    today = date.today()
    month_start = date(today.year, today.month, 1)
    p_start = _parse_date(start_date, month_start)
    p_end = _parse_date(end_date, today)
    if p_end < p_start:
        p_start, p_end = p_end, p_start

    p_start_dt = datetime.combine(p_start, datetime.min.time(), tzinfo=timezone.utc)
    p_end_dt = datetime.combine(p_end, datetime.max.time(), tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    month_start_dt = _month_start_utc()
    week_start = _week_start_utc()
    seven_days_ago = now - timedelta(days=7)

    # Factures: unpaid = sent+overdue. Sum total of those; count rows.
    unpaid_sum_stmt = select(
        func.coalesce(func.sum(Facture.total), 0),
        func.count(Facture.id),
    ).where(
        Facture.status.in_(
            [FactureStatus.SENT.value, FactureStatus.OVERDUE.value]
        )
    )
    unpaid_total, unpaid_count = (
        await db.execute(unpaid_sum_stmt)
    ).one()

    overdue_sum_stmt = select(
        func.coalesce(func.sum(Facture.total), 0),
        func.count(Facture.id),
    ).where(
        Facture.status == FactureStatus.OVERDUE.value,
    )
    overdue_total, overdue_count = (
        await db.execute(overdue_sum_stmt)
    ).one()

    # Revenue this month: paid factures with paid_at >= start of month.
    # If nothing's been marked paid yet (common in dev/test), fall back
    # to "issued this month" so the tile isn't stuck at $0.
    revenue_stmt = select(func.coalesce(func.sum(Facture.total), 0)).where(
        Facture.status == FactureStatus.PAID.value,
        Facture.paid_at.is_not(None),
        Facture.paid_at >= month_start_dt,
    )
    revenue = (await db.execute(revenue_stmt)).scalar_one()
    revenue_mode = "paid"
    if float(revenue or 0) == 0:
        issued_stmt = select(func.coalesce(func.sum(Facture.total), 0)).where(
            Facture.status.in_(
                [
                    FactureStatus.SENT.value,
                    FactureStatus.PAID.value,
                    FactureStatus.OVERDUE.value,
                ]
            ),
            Facture.issued_at.is_not(None),
            Facture.issued_at >= month_start_dt,
        )
        issued_sum = (await db.execute(issued_stmt)).scalar_one()
        if float(issued_sum or 0) > 0:
            revenue = issued_sum
            revenue_mode = "issued"

    # --- Period-scoped KPIs ---
    prospects_count = (
        await db.execute(
            select(func.count(ContactRequest.id)).where(
                ContactRequest.created_at >= p_start_dt,
                ContactRequest.created_at <= p_end_dt,
            )
        )
    ).scalar_one()

    # Soumissions sent in period
    sent_sum_stmt = select(
        func.coalesce(func.sum(Soumission.total), 0),
        func.count(Soumission.id),
    ).where(
        Soumission.sent_at.is_not(None),
        Soumission.sent_at >= p_start_dt,
        Soumission.sent_at <= p_end_dt,
    )
    soum_sent_total, soum_sent_count = (
        await db.execute(sent_sum_stmt)
    ).one()

    # Ventes = soumissions accepted in period.
    # `accepted_at` peut être null pour les anciens rows (imports
    # externes, statut posé via PATCH générique, etc.) — dans ce
    # cas on retombe sur `updated_at` puis `created_at` pour ne
    # PAS perdre la vente. Sinon Beaudoin & co disparaissent du
    # KPI alors qu'ils sont bien dans la colonne « Acceptées ».
    accepted_ts = func.coalesce(
        Soumission.accepted_at,
        Soumission.updated_at,
        Soumission.created_at,
    )
    ventes_sum_stmt = select(
        func.coalesce(func.sum(Soumission.total), 0),
        func.count(Soumission.id),
    ).where(
        Soumission.status == SoumissionStatus.ACCEPTED.value,
        accepted_ts >= p_start_dt,
        accepted_ts <= p_end_dt,
    )
    ventes_total, ventes_count = (await db.execute(ventes_sum_stmt)).one()

    conversion = (
        (float(ventes_count) / float(soum_sent_count) * 100.0)
        if soum_sent_count
        else 0.0
    )
    avg_tx = (
        float(ventes_total) / float(ventes_count) if ventes_count else 0.0
    )

    # Avg time to sale (days) for accepted in period — ContactRequest
    # created_at → Soumission accepted_at.
    tts_stmt = (
        select(
            func.avg(
                func.extract(
                    "epoch",
                    accepted_ts - ContactRequest.created_at,
                )
                / 86400.0
            )
        )
        .select_from(Soumission)
        .join(
            ContactRequest,
            ContactRequest.id == Soumission.contact_request_id,
            isouter=False,
        )
        .where(
            Soumission.status == SoumissionStatus.ACCEPTED.value,
            accepted_ts >= p_start_dt,
            accepted_ts <= p_end_dt,
        )
    )
    time_to_sale = (await db.execute(tts_stmt)).scalar_one()

    # Active projects (in_progress)
    active_projects = (
        await db.execute(
            select(func.count(Project.id)).where(
                Project.status == ProjectStatus.IN_PROGRESS.value
            )
        )
    ).scalar_one()

    # Hours punched this week (any employé, counted regardless of approval).
    hours_stmt = select(func.coalesce(func.sum(Punch.hours), 0)).where(
        Punch.started_at >= week_start,
        Punch.ended_at.is_not(None),
    )
    hours_week = (await db.execute(hours_stmt)).scalar_one()

    # New prospects last 7 days (any status, helps spot influx)
    new_prospects = (
        await db.execute(
            select(func.count(ContactRequest.id)).where(
                ContactRequest.created_at >= seven_days_ago
            )
        )
    ).scalar_one()

    # Soumissions in the pipeline (sent but not yet accepted/rejected)
    open_soumissions_stmt = select(
        func.coalesce(func.sum(Soumission.total), 0),
        func.count(Soumission.id),
    ).where(Soumission.status == SoumissionStatus.SENT.value)
    open_total, open_count = (await db.execute(open_soumissions_stmt)).one()

    # --- Timeseries: soumissions envoyées $ / jour + ventes acceptées $ / jour ---
    ts_soum_stmt = (
        select(
            cast(Soumission.sent_at, Date).label("d"),
            func.coalesce(func.sum(Soumission.total), 0).label("s"),
        )
        .where(
            Soumission.sent_at.is_not(None),
            Soumission.sent_at >= p_start_dt,
            Soumission.sent_at <= p_end_dt,
        )
        .group_by(cast(Soumission.sent_at, Date))
    )
    ts_ventes_stmt = (
        select(
            cast(accepted_ts, Date).label("d"),
            func.coalesce(func.sum(Soumission.total), 0).label("v"),
        )
        .where(
            Soumission.status == SoumissionStatus.ACCEPTED.value,
            accepted_ts >= p_start_dt,
            accepted_ts <= p_end_dt,
        )
        .group_by(cast(accepted_ts, Date))
    )
    soum_rows = {r.d: float(r.s or 0) for r in (await db.execute(ts_soum_stmt)).all()}
    ventes_rows = {r.d: float(r.v or 0) for r in (await db.execute(ts_ventes_stmt)).all()}

    # Fill every day in the range so the chart is continuous.
    days: list[TimeseriesPoint] = []
    cur = p_start
    while cur <= p_end:
        days.append(
            TimeseriesPoint(
                date=cur,
                soumissions=soum_rows.get(cur, 0.0),
                ventes=ventes_rows.get(cur, 0.0),
            )
        )
        cur = cur + timedelta(days=1)

    return KpiResponse(
        start_date=p_start,
        end_date=p_end,
        unpaid_total=float(unpaid_total or 0),
        unpaid_count=int(unpaid_count or 0),
        overdue_total=float(overdue_total or 0),
        overdue_count=int(overdue_count or 0),
        revenue_this_month=float(revenue or 0),
        revenue_this_month_mode=revenue_mode,
        prospects_count=int(prospects_count or 0),
        soumissions_sent_total=float(soum_sent_total or 0),
        soumissions_sent_count=int(soum_sent_count or 0),
        ventes_total=float(ventes_total or 0),
        ventes_count=int(ventes_count or 0),
        conversion_rate=round(conversion, 1),
        avg_transaction=round(avg_tx, 2),
        time_to_sale_days=round(float(time_to_sale or 0), 1),
        active_projects=int(active_projects or 0),
        hours_this_week=float(hours_week or 0),
        new_prospects_7d=int(new_prospects or 0),
        open_soumissions_count=int(open_count or 0),
        open_soumissions_total=float(open_total or 0),
        timeseries=days,
    )
