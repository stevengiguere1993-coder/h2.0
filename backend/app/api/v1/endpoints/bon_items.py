"""Nested CRUD for line items on a Bon de travail."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.bon_item import BonItem
from app.models.bon_travail import BonTravail


router = APIRouter(prefix="/bons-travail", tags=["bon-items"])


class BonItemCreate(BaseModel):
    position: int = Field(default=0, ge=0)
    description: str = Field(..., min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: float = Field(default=1, ge=0)
    unit_price: float = Field(default=0, ge=0)


class BonItemUpdate(BaseModel):
    position: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[float] = Field(default=None, ge=0)
    unit_price: Optional[float] = Field(default=None, ge=0)


class BonItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    bon_id: int
    position: int
    description: str
    unit: Optional[str]
    quantity: float
    unit_price: float
    total: float


async def _ensure_bon(db, bon_id: int) -> BonTravail:
    record = (
        await db.execute(select(BonTravail).where(BonTravail.id == bon_id))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bon de travail not found")
    return record


@router.get("/{bon_id}/items", response_model=List[BonItemRead])
async def list_items(bon_id: int, db: DBSession, _: CurrentUser) -> List[BonItemRead]:
    await _ensure_bon(db, bon_id)
    rows = (
        await db.execute(
            select(BonItem)
            .where(BonItem.bon_id == bon_id)
            .order_by(BonItem.position.asc(), BonItem.id.asc())
        )
    ).scalars().all()
    return [BonItemRead.model_validate(r) for r in rows]


@router.post(
    "/{bon_id}/items",
    response_model=BonItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_item(
    bon_id: int, data: BonItemCreate, db: DBSession, _: CurrentUser
) -> BonItemRead:
    await _ensure_bon(db, bon_id)
    total = round(data.quantity * data.unit_price, 2)
    item = BonItem(
        bon_id=bon_id,
        position=data.position,
        description=data.description.strip(),
        unit=(data.unit or None),
        quantity=data.quantity,
        unit_price=data.unit_price,
        total=total,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return BonItemRead.model_validate(item)


@router.patch("/{bon_id}/items/{item_id}", response_model=BonItemRead)
async def update_item(
    bon_id: int,
    item_id: int,
    data: BonItemUpdate,
    db: DBSession,
    _: CurrentUser,
) -> BonItemRead:
    item = (
        await db.execute(
            select(BonItem).where(
                BonItem.id == item_id, BonItem.bon_id == bon_id
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    update = data.model_dump(exclude_unset=True)
    for field, value in update.items():
        setattr(item, field, value)
    if "quantity" in update or "unit_price" in update:
        item.total = round(float(item.quantity) * float(item.unit_price), 2)
    await db.flush()
    await db.refresh(item)
    return BonItemRead.model_validate(item)


@router.delete(
    "/{bon_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_item(
    bon_id: int, item_id: int, db: DBSession, _: CurrentUser
) -> None:
    item = (
        await db.execute(
            select(BonItem).where(
                BonItem.id == item_id, BonItem.bon_id == bon_id
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    await db.delete(item)
    await db.flush()
