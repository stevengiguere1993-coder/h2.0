"""Articles d'un bon de commande (PO).

    GET    /api/v1/purchase-orders/{po_id}/items
    POST   /api/v1/purchase-orders/{po_id}/items
    PATCH  /api/v1/purchase-orders/{po_id}/items/{item_id}
    DELETE /api/v1/purchase-orders/{po_id}/items/{item_id}

Pas de taxes (un PO est interne, pas une facture). Le total de chaque
ligne = quantity * unit_price ; la somme des lignes alimente le
`amount_max` du PO côté frontend.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem


router = APIRouter(prefix="/purchase-orders", tags=["purchase-order-items"])


class POItemCreate(BaseModel):
    position: int = Field(default=0, ge=0)
    description: str = Field(..., min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: float = Field(default=1)
    unit_price: float = Field(default=0)


class POItemUpdate(BaseModel):
    position: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[float] = Field(default=None)
    unit_price: Optional[float] = Field(default=None)


class POItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    purchase_order_id: int
    position: int
    description: str
    unit: Optional[str]
    quantity: float
    unit_price: float
    total: float


async def _ensure_po(db, po_id: int) -> PurchaseOrder:
    record = (
        await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="PO introuvable"
        )
    return record


@router.get(
    "/{po_id}/items",
    response_model=List[POItemRead],
    summary="Liste des articles d'un PO",
)
async def list_items(
    po_id: int, db: DBSession, _: CurrentUser
) -> List[POItemRead]:
    await _ensure_po(db, po_id)
    rows = (
        await db.execute(
            select(PurchaseOrderItem)
            .where(PurchaseOrderItem.purchase_order_id == po_id)
            .order_by(
                PurchaseOrderItem.position.asc(),
                PurchaseOrderItem.id.asc(),
            )
        )
    ).scalars().all()
    return [POItemRead.model_validate(r) for r in rows]


@router.post(
    "/{po_id}/items",
    response_model=POItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un article sur un PO",
)
async def create_item(
    po_id: int,
    data: POItemCreate,
    db: DBSession,
    _: CurrentUser,
) -> POItemRead:
    await _ensure_po(db, po_id)
    qty = data.quantity
    unit_price = data.unit_price
    total = round(qty * unit_price, 2)
    item = PurchaseOrderItem(
        purchase_order_id=po_id,
        position=data.position,
        description=data.description.strip(),
        unit=(data.unit or None),
        quantity=qty,
        unit_price=unit_price,
        total=total,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return POItemRead.model_validate(item)


@router.patch(
    "/{po_id}/items/{item_id}",
    response_model=POItemRead,
    summary="Modifier un article",
)
async def update_item(
    po_id: int,
    item_id: int,
    data: POItemUpdate,
    db: DBSession,
    _: CurrentUser,
) -> POItemRead:
    item = (
        await db.execute(
            select(PurchaseOrderItem).where(
                PurchaseOrderItem.id == item_id,
                PurchaseOrderItem.purchase_order_id == po_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article introuvable"
        )
    update = data.model_dump(exclude_unset=True)
    for field, value in update.items():
        setattr(item, field, value)
    if "quantity" in update or "unit_price" in update:
        item.total = round(float(item.quantity) * float(item.unit_price), 2)
    await db.flush()
    await db.refresh(item)
    return POItemRead.model_validate(item)


@router.delete(
    "/{po_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un article",
)
async def delete_item(
    po_id: int,
    item_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    item = (
        await db.execute(
            select(PurchaseOrderItem).where(
                PurchaseOrderItem.id == item_id,
                PurchaseOrderItem.purchase_order_id == po_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article introuvable"
        )
    await db.delete(item)
    await db.flush()
