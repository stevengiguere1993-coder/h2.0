"""Financial breakdown for a Project: projected (from soumission items
+ agenda-planned labour) vs actual (from achats + approved punches).

    GET /api/v1/projects/{project_id}/finances
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat
from app.models.employe import Employe
from app.models.facture import Facture, FactureStatus
from app.models.payment import Payment
from app.models.project import Project
from app.models.punch import Punch
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem


router = APIRouter(prefix="/projects", tags=["project-finances"])


class CostLine(BaseModel):
    label: str
    quantity: float
    unit_cost: float
    total: float


class FinancesResponse(BaseModel):
    projected_revenue: float
    projected_service_cost: float
    projected_labour_cost: float
    projected_labour_hours: float
    projected_total_cost: float
    projected_profit: float
    projected_margin_pct: float

    actual_material_cost: float
    actual_labour_cost: float
    actual_labour_hours: float
    actual_total_cost: float
    actual_profit: Optional[float]  # null while no facture is paid yet
    actual_margin_pct: Optional[float]

    service_lines: List[CostLine]   # from soumission items
    material_lines: List[CostLine]  # from achats
    invoiced_amount: float
    paid_amount: float
    balance_due: float


@router.get(
    "/{project_id}/finances",
    response_model=FinancesResponse,
    summary="Financial projection vs actuals for a project",
)
async def get_finances(
    project_id: int,
    db: DBSession,
    _: CurrentUser,
) -> FinancesResponse:
    proj = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    # --- Projected from the linked soumission's items ---
    service_lines: List[CostLine] = []
    projected_revenue = 0.0
    if proj.soumission_id:
        items = (
            await db.execute(
                select(SoumissionItem).where(
                    SoumissionItem.soumission_id == proj.soumission_id
                )
            )
        ).scalars().all()
        for it in items:
            service_lines.append(
                CostLine(
                    label=it.description,
                    quantity=float(it.quantity),
                    unit_cost=float(it.unit_price),
                    total=float(it.total),
                )
            )
        # projected revenue = facture client (soumission total if set else sum items)
        sm = (
            await db.execute(
                select(Soumission).where(Soumission.id == proj.soumission_id)
            )
        ).scalar_one_or_none()
        if sm and sm.total is not None:
            projected_revenue = float(sm.total)
        else:
            projected_revenue = sum(it.total for it in service_lines)

    projected_service_cost = sum(it.total for it in service_lines)

    # --- Projected labour ---
    # If project has a budget field, use it as the service-cost floor.
    # Otherwise derive from start_date/end_date * 40h/week and $35/h.
    projected_labour_hours = 0.0
    projected_labour_cost = 0.0
    if proj.start_date and proj.end_date:
        days = max(1, (proj.end_date - proj.start_date).days + 1)
        projected_labour_hours = days * 8  # 8h/day
    # Average rate — pragmatic fallback.
    avg_rate_stmt = select(func.coalesce(func.avg(Employe.hourly_rate), 35.0))
    avg_rate = float((await db.execute(avg_rate_stmt)).scalar_one() or 35.0)
    projected_labour_cost = round(projected_labour_hours * avg_rate, 2)

    projected_total_cost = round(
        projected_service_cost + projected_labour_cost, 2
    )
    projected_profit = round(projected_revenue - projected_total_cost, 2)
    projected_margin_pct = (
        round(projected_profit / projected_revenue * 100, 1)
        if projected_revenue > 0
        else 0.0
    )

    # --- Actuals ---
    achats_stmt = select(Achat).where(Achat.project_id == project_id)
    achats = (await db.execute(achats_stmt)).scalars().all()
    material_lines = [
        CostLine(
            label=a.description or a.reference,
            quantity=1,
            unit_cost=float(a.amount or 0),
            total=float(a.amount or 0),
        )
        for a in achats
    ]
    actual_material_cost = sum(m.total for m in material_lines)

    # Labour — sum of approved punches on this project
    punches = (
        await db.execute(
            select(Punch).where(
                Punch.project_id == project_id,
                Punch.ended_at.is_not(None),
            )
        )
    ).scalars().all()
    actual_labour_hours = sum(float(p.hours or 0) for p in punches)

    # Pull each punched employé's rate and total individually
    actual_labour_cost = 0.0
    for p in punches:
        rate_stmt = select(Employe.hourly_rate).where(
            Employe.id == p.employe_id
        )
        rate = (await db.execute(rate_stmt)).scalar_one_or_none()
        actual_labour_cost += float(p.hours or 0) * float(rate or avg_rate)
    actual_labour_cost = round(actual_labour_cost, 2)

    actual_total_cost = round(actual_material_cost + actual_labour_cost, 2)

    # Invoicing
    factures = (
        await db.execute(
            select(Facture).where(Facture.project_id == project_id)
        )
    ).scalars().all()
    invoiced = sum(float(f.total or 0) for f in factures)
    paid_sum = 0.0
    if factures:
        ids = [f.id for f in factures]
        paid_sum = float(
            (
                await db.execute(
                    select(func.coalesce(func.sum(Payment.amount), 0)).where(
                        Payment.facture_id.in_(ids)
                    )
                )
            ).scalar_one()
            or 0
        )
    # A facture with status=paid and no payments rows is counted too.
    for f in factures:
        if f.status == FactureStatus.PAID.value and f.paid_at is not None:
            # If there are no payment rows, fall back to counting the
            # total as paid to avoid double-counting.
            paid_for_this = float(
                (
                    await db.execute(
                        select(
                            func.coalesce(func.sum(Payment.amount), 0)
                        ).where(Payment.facture_id == f.id)
                    )
                ).scalar_one()
                or 0
            )
            if paid_for_this == 0:
                paid_sum += float(f.total or 0)

    balance = max(0.0, invoiced - paid_sum)

    # Actual profit = paid revenue - costs (only meaningful once paid)
    actual_profit: Optional[float] = None
    actual_margin_pct: Optional[float] = None
    if paid_sum > 0:
        actual_profit = round(paid_sum - actual_total_cost, 2)
        actual_margin_pct = (
            round(actual_profit / paid_sum * 100, 1) if paid_sum > 0 else 0.0
        )

    return FinancesResponse(
        projected_revenue=round(projected_revenue, 2),
        projected_service_cost=round(projected_service_cost, 2),
        projected_labour_cost=projected_labour_cost,
        projected_labour_hours=round(projected_labour_hours, 2),
        projected_total_cost=projected_total_cost,
        projected_profit=projected_profit,
        projected_margin_pct=projected_margin_pct,
        actual_material_cost=round(actual_material_cost, 2),
        actual_labour_cost=actual_labour_cost,
        actual_labour_hours=round(actual_labour_hours, 2),
        actual_total_cost=actual_total_cost,
        actual_profit=actual_profit,
        actual_margin_pct=actual_margin_pct,
        service_lines=service_lines,
        material_lines=material_lines,
        invoiced_amount=round(invoiced, 2),
        paid_amount=round(paid_sum, 2),
        balance_due=round(balance, 2),
    )
