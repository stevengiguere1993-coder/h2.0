"""Lightweight aggregate endpoint for the soumissions kanban.

The generic CRUD list at GET /api/v1/soumissions returns the raw
soumission rows. When a soumission has line items but its persisted
``subtotal`` / ``total`` columns are null/0 (older records or items
added without re-saving the totals), the kanban shows « — » for
the amount.

This endpoint exposes a complement: for each soumission id passed
in the body, the sum of its line items' totals (or qty × unit_price
if `total` is itself null on items). Frontend then uses this as a
fallback when the soumission's stored total is null.

A single batch SQL query — O(1) round-trip regardless of the number
of soumissions in the kanban.
"""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from app.api.deps import CurrentUser, DBSession
from app.models.soumission_item import SoumissionItem


router = APIRouter(prefix="/soumissions", tags=["soumissions-aggregates"])


class ItemsTotalRequest(BaseModel):
    soumission_ids: List[int] = Field(default_factory=list, max_length=500)


class ItemsTotalResponse(BaseModel):
    """Map soumission_id → somme des items (avant taxes)."""

    totals: Dict[int, float]


@router.post(
    "/items-totals",
    response_model=ItemsTotalResponse,
    summary="Calcule la somme des items pour une liste de soumissions",
)
async def items_totals(
    body: ItemsTotalRequest,
    db: DBSession,
    _: CurrentUser,
) -> ItemsTotalResponse:
    if not body.soumission_ids:
        return ItemsTotalResponse(totals={})

    # COALESCE(total, qty * unit_price) pour gérer les vieilles lignes
    # où `total` n'est pas encore persisté.
    line_amount = case(
        (
            SoumissionItem.total > 0,
            SoumissionItem.total,
        ),
        else_=SoumissionItem.quantity * SoumissionItem.unit_price,
    )

    rows = (
        await db.execute(
            select(
                SoumissionItem.soumission_id,
                func.sum(line_amount),
            )
            .where(SoumissionItem.soumission_id.in_(set(body.soumission_ids)))
            .group_by(SoumissionItem.soumission_id)
        )
    ).all()
    totals = {sid: float(amount or 0) for sid, amount in rows}
    return ItemsTotalResponse(totals=totals)
