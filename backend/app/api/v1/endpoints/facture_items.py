"""Nested CRUD for line items on a Facture.

    GET    /api/v1/factures/{facture_id}/items
    POST   /api/v1/factures/{facture_id}/items
    PATCH  /api/v1/factures/{facture_id}/items/{item_id}
    DELETE /api/v1/factures/{facture_id}/items/{item_id}

Le backend recalcule automatiquement les totaux de la facture
parente (subtotal / TPS / TVQ / total) après chaque mutation d'item.
Garantit que les totaux Facture sont toujours synchros pour les
KPIs projet (« Facturé », « Reste à facturer ») et pour QBO.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.facture import Facture
from app.models.facture_item import FactureItem


router = APIRouter(prefix="/factures", tags=["facture-items"])


# Taux taxes québécoises 2026.
TPS_RATE = 0.05
TVQ_RATE = 0.09975


async def _recompute_facture_totals(db, facture_id: int) -> None:
    """Recalcule subtotal/tps/tvq/total à partir des items.

    Les FactureItem n'ont pas de flags tps_applicable/tvq_applicable
    (contrairement aux SoumissionItem) — on applique les 2 taxes par
    défaut. Si un item « rabais » (montant négatif) est présent, il
    réduit la base taxable comme attendu.
    """
    items = (
        await db.execute(
            select(FactureItem).where(FactureItem.facture_id == facture_id)
        )
    ).scalars().all()
    subtotal = round(sum(float(it.total or 0) for it in items), 2)
    tps = round(subtotal * TPS_RATE, 2)
    tvq = round(subtotal * TVQ_RATE, 2)
    total = round(subtotal + tps + tvq, 2)

    fac = (
        await db.execute(select(Facture).where(Facture.id == facture_id))
    ).scalar_one_or_none()
    if fac is None:
        return
    fac.subtotal = subtotal
    fac.tps = tps
    fac.tvq = tvq
    fac.total = total
    await db.flush()


class FactureItemCreate(BaseModel):
    position: int = Field(default=0, ge=0)
    description: str = Field(..., min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: float = Field(default=1, ge=0)
    unit_price: float = Field(default=0, ge=0)


class FactureItemUpdate(BaseModel):
    position: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[float] = Field(default=None, ge=0)
    unit_price: Optional[float] = Field(default=None, ge=0)


class FactureItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    facture_id: int
    position: int
    description: str
    unit: Optional[str]
    quantity: float
    unit_price: float
    total: float


async def _ensure_facture(db, facture_id: int) -> Facture:
    record = (
        await db.execute(select(Facture).where(Facture.id == facture_id))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Facture not found"
        )
    return record


@router.get(
    "/{facture_id}/items",
    response_model=List[FactureItemRead],
    summary="List items of a facture",
)
async def list_items(
    facture_id: int, db: DBSession, _: CurrentUser
) -> List[FactureItemRead]:
    await _ensure_facture(db, facture_id)
    rows = (
        await db.execute(
            select(FactureItem)
            .where(FactureItem.facture_id == facture_id)
            .order_by(FactureItem.position.asc(), FactureItem.id.asc())
        )
    ).scalars().all()
    return [FactureItemRead.model_validate(r) for r in rows]


@router.post(
    "/{facture_id}/items",
    response_model=FactureItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a line item",
)
async def create_item(
    facture_id: int,
    data: FactureItemCreate,
    db: DBSession,
    _: CurrentUser,
) -> FactureItemRead:
    await _ensure_facture(db, facture_id)
    total = round(data.quantity * data.unit_price, 2)
    item = FactureItem(
        facture_id=facture_id,
        position=data.position,
        description=data.description.strip(),
        unit=(data.unit or None),
        quantity=data.quantity,
        unit_price=data.unit_price,
        total=total,
    )
    db.add(item)
    await db.flush()
    await _recompute_facture_totals(db, facture_id)
    await db.refresh(item)
    return FactureItemRead.model_validate(item)


@router.patch(
    "/{facture_id}/items/{item_id}",
    response_model=FactureItemRead,
    summary="Update a line item",
)
async def update_item(
    facture_id: int,
    item_id: int,
    data: FactureItemUpdate,
    db: DBSession,
    _: CurrentUser,
) -> FactureItemRead:
    item = (
        await db.execute(
            select(FactureItem).where(
                FactureItem.id == item_id,
                FactureItem.facture_id == facture_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    update = data.model_dump(exclude_unset=True)
    for field, value in update.items():
        setattr(item, field, value)
    if "quantity" in update or "unit_price" in update:
        item.total = round(float(item.quantity) * float(item.unit_price), 2)
    await db.flush()
    await _recompute_facture_totals(db, facture_id)
    await db.refresh(item)
    return FactureItemRead.model_validate(item)


@router.delete(
    "/{facture_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a line item",
)
async def delete_item(
    facture_id: int,
    item_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    item = (
        await db.execute(
            select(FactureItem).where(
                FactureItem.id == item_id,
                FactureItem.facture_id == facture_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    await db.delete(item)
    await db.flush()
    await _recompute_facture_totals(db, facture_id)


# Backfill : resynchronise les totaux de TOUTES les factures
# existantes depuis leurs items réels.
@router.post(
    "/recompute-all",
    summary="Backfill : recalcule subtotal/total de toutes les factures",
)
async def recompute_all_factures(db: DBSession, _: CurrentUser) -> dict:
    ids = (await db.execute(select(Facture.id))).scalars().all()
    for fid in ids:
        await _recompute_facture_totals(db, int(fid))
    return {"recomputed": len(ids)}
