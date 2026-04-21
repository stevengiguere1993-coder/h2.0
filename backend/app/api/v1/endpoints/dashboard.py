"""Dashboard KPIs shown on the /app home page.

Lightweight aggregate queries that roll up the current state of the
business in a single response.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.models.contact_request import ContactRequest
from app.models.facture import Facture, FactureStatus
from app.models.project import Project, ProjectStatus
from app.models.punch import Punch
from app.models.soumission import Soumission, SoumissionStatus


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class KpiResponse(BaseModel):
    # Money / cash flow
    unpaid_total: float
    unpaid_count: int
    overdue_total: float
    overdue_count: int
    draft_total: float
    draft_count: int
    revenue_this_month: float
    revenue_this_month_mode: str  # "paid" | "issued"

    # Ops
    active_projects: int
    hours_this_week: float
    new_prospects_7d: int

    # Pipeline
    open_soumissions_count: int
    open_soumissions_total: float


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
async def get_kpis(db: DBSession, _: CurrentUser) -> KpiResponse:
    now = datetime.now(timezone.utc)
    month_start = _month_start_utc()
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

    # Drafts — not yet sent, but surfaced so the user sees test/pending
    # factures on the dashboard rather than them disappearing.
    draft_sum_stmt = select(
        func.coalesce(func.sum(Facture.total), 0),
        func.count(Facture.id),
    ).where(Facture.status == FactureStatus.DRAFT.value)
    draft_total, draft_count = (await db.execute(draft_sum_stmt)).one()

    # Revenue this month: paid factures with paid_at >= start of month.
    # If nothing's been marked paid yet (common in dev/test), fall back
    # to "issued this month" so the tile isn't stuck at $0.
    revenue_stmt = select(func.coalesce(func.sum(Facture.total), 0)).where(
        Facture.status == FactureStatus.PAID.value,
        Facture.paid_at.is_not(None),
        Facture.paid_at >= month_start,
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
            Facture.issued_at >= month_start,
        )
        issued_sum = (await db.execute(issued_stmt)).scalar_one()
        if float(issued_sum or 0) > 0:
            revenue = issued_sum
            revenue_mode = "issued"

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

    return KpiResponse(
        unpaid_total=float(unpaid_total or 0),
        unpaid_count=int(unpaid_count or 0),
        overdue_total=float(overdue_total or 0),
        overdue_count=int(overdue_count or 0),
        draft_total=float(draft_total or 0),
        draft_count=int(draft_count or 0),
        revenue_this_month=float(revenue or 0),
        revenue_this_month_mode=revenue_mode,
        active_projects=int(active_projects or 0),
        hours_this_week=float(hours_week or 0),
        new_prospects_7d=int(new_prospects or 0),
        open_soumissions_count=int(open_count or 0),
        open_soumissions_total=float(open_total or 0),
    )
