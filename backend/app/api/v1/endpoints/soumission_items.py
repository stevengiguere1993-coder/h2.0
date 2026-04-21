"""
Nested endpoints for soumission line items:
    GET    /api/v1/soumissions/{soumission_id}/items
    POST   /api/v1/soumissions/{soumission_id}/items
    PATCH  /api/v1/soumissions/{soumission_id}/items/{item_id}
    DELETE /api/v1/soumissions/{soumission_id}/items/{item_id}

All routes are staff-only (CurrentUser). The endpoint never recomputes
the parent Soumission totals -- that responsibility lives on the
frontend which already computes subtotal/TPS/TVQ/total live.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem


router = APIRouter(prefix="/soumissions", tags=["soumission-items"])


class SoumissionItemCreate(BaseModel):
    position: int = Field(default=0, ge=0)
    description: str = Field(..., min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: float = Field(default=1)
    unit_price: float = Field(default=0)
    tps_applicable: bool = Field(default=True)
    tvq_applicable: bool = Field(default=True)
    kind: str = Field(default="service", pattern="^(service|frais|rabais)$")


class SoumissionItemUpdate(BaseModel):
    position: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[float] = Field(default=None)
    unit_price: Optional[float] = Field(default=None)
    tps_applicable: Optional[bool] = Field(default=None)
    tvq_applicable: Optional[bool] = Field(default=None)
    kind: Optional[str] = Field(default=None, pattern="^(service|frais|rabais)$")


class SoumissionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    soumission_id: int
    position: int
    description: str
    unit: Optional[str]
    quantity: float
    unit_price: float
    total: float
    tps_applicable: bool
    tvq_applicable: bool
    kind: str


async def _ensure_soumission(db, soumission_id: int) -> Soumission:
    record = (
        await db.execute(select(Soumission).where(Soumission.id == soumission_id))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Soumission not found")
    return record


@router.get(
    "/{soumission_id}/items",
    response_model=List[SoumissionItemRead],
    summary="List items of a soumission",
)
async def list_items(
    soumission_id: int, db: DBSession, _: CurrentUser
) -> List[SoumissionItemRead]:
    await _ensure_soumission(db, soumission_id)
    rows = (
        await db.execute(
            select(SoumissionItem)
            .where(SoumissionItem.soumission_id == soumission_id)
            .order_by(SoumissionItem.position.asc(), SoumissionItem.id.asc())
        )
    ).scalars().all()
    return [SoumissionItemRead.model_validate(r) for r in rows]


@router.post(
    "/{soumission_id}/items",
    response_model=SoumissionItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an item on a soumission",
)
async def create_item(
    soumission_id: int,
    data: SoumissionItemCreate,
    db: DBSession,
    _: CurrentUser,
) -> SoumissionItemRead:
    await _ensure_soumission(db, soumission_id)
    # Rabais = negative line, frais = positive no-tax line.
    qty = data.quantity
    unit_price = data.unit_price
    if data.kind == "rabais" and unit_price > 0:
        unit_price = -abs(unit_price)
    total = round(qty * unit_price, 2)
    item = SoumissionItem(
        soumission_id=soumission_id,
        position=data.position,
        description=data.description.strip(),
        unit=(data.unit or None),
        quantity=qty,
        unit_price=unit_price,
        total=total,
        tps_applicable=(False if data.kind == "frais" else data.tps_applicable),
        tvq_applicable=(False if data.kind == "frais" else data.tvq_applicable),
        kind=data.kind,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return SoumissionItemRead.model_validate(item)


@router.patch(
    "/{soumission_id}/items/{item_id}",
    response_model=SoumissionItemRead,
    summary="Update an item on a soumission",
)
async def update_item(
    soumission_id: int,
    item_id: int,
    data: SoumissionItemUpdate,
    db: DBSession,
    _: CurrentUser,
) -> SoumissionItemRead:
    item = (
        await db.execute(
            select(SoumissionItem).where(
                SoumissionItem.id == item_id,
                SoumissionItem.soumission_id == soumission_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    update = data.model_dump(exclude_unset=True)
    for field, value in update.items():
        setattr(item, field, value)
    # Re-derive total whenever qty or price changes
    if "quantity" in update or "unit_price" in update:
        item.total = round(float(item.quantity) * float(item.unit_price), 2)
    await db.flush()
    await db.refresh(item)
    return SoumissionItemRead.model_validate(item)


@router.delete(
    "/{soumission_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an item from a soumission",
)
async def delete_item(
    soumission_id: int,
    item_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    item = (
        await db.execute(
            select(SoumissionItem).where(
                SoumissionItem.id == item_id,
                SoumissionItem.soumission_id == soumission_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    await db.delete(item)
    await db.flush()
