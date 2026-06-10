"""Reusable service templates. Each template has a name, optional
default unit + unit_price, and a list of sub-items (items). A staff
user can drop a template into a soumission: each sub-item is copied
as a SoumissionItem.

    GET    /api/v1/service-templates
    POST   /api/v1/service-templates
    GET    /api/v1/service-templates/{id}
    PATCH  /api/v1/service-templates/{id}
    DELETE /api/v1/service-templates/{id}
    POST   /api/v1/service-templates/{id}/items
    PATCH  /api/v1/service-templates/{id}/items/{item_id}
    DELETE /api/v1/service-templates/{id}/items/{item_id}
    POST   /api/v1/service-templates/{id}/apply
           { "soumission_id": int } -> inserts items into the soumission
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.service_template import ServiceTemplate, ServiceTemplateItem
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem


router = APIRouter(prefix="/service-templates", tags=["service-templates"])


class TemplateItemCreate(BaseModel):
    position: int = Field(default=0, ge=0)
    description: str = Field(..., min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    default_quantity: float = Field(default=1, ge=0)
    default_unit_price: float = Field(default=0, ge=0)
    default_cost_per_unit: float = Field(default=0, ge=0)


class TemplateItemUpdate(BaseModel):
    position: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    default_quantity: Optional[float] = Field(default=None, ge=0)
    default_unit_price: Optional[float] = Field(default=None, ge=0)
    default_cost_per_unit: Optional[float] = Field(default=None, ge=0)


class TemplateItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    template_id: int
    position: int
    description: str
    unit: Optional[str]
    default_quantity: float
    default_unit_price: float
    default_cost_per_unit: float = 0


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    default_unit: Optional[str] = Field(default=None, max_length=32)
    default_unit_price: Optional[float] = None
    default_cost_per_unit: Optional[float] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    default_unit: Optional[str] = Field(default=None, max_length=32)
    default_unit_price: Optional[float] = None
    default_cost_per_unit: Optional[float] = None
    is_active: Optional[bool] = None


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str]
    default_unit: Optional[str]
    default_unit_price: Optional[float]
    default_cost_per_unit: Optional[float] = None
    is_active: bool


class TemplateWithItems(TemplateRead):
    items: List[TemplateItemRead] = Field(default_factory=list)


class ApplyToSoumission(BaseModel):
    soumission_id: int


class ApplyToPurchaseOrder(BaseModel):
    purchase_order_id: int


async def _ensure_template(db, template_id: int) -> ServiceTemplate:
    t = (
        await db.execute(
            select(ServiceTemplate).where(ServiceTemplate.id == template_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return t


@router.get("", response_model=List[TemplateRead])
async def list_templates(
    db: DBSession,
    _: CurrentUser,
    active_only: bool = True,
) -> List[TemplateRead]:
    stmt = select(ServiceTemplate).order_by(ServiceTemplate.name.asc())
    if active_only:
        stmt = stmt.where(ServiceTemplate.is_active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [TemplateRead.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    data: TemplateCreate, db: DBSession, _: CurrentUser
) -> TemplateRead:
    t = ServiceTemplate(
        name=data.name.strip(),
        description=(data.description.strip() if data.description else None),
        default_unit=data.default_unit,
        default_unit_price=data.default_unit_price,
        default_cost_per_unit=data.default_cost_per_unit,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return TemplateRead.model_validate(t)


@router.get("/{template_id}", response_model=TemplateWithItems)
async def get_template(
    template_id: int, db: DBSession, _: CurrentUser
) -> TemplateWithItems:
    t = await _ensure_template(db, template_id)
    items = (
        await db.execute(
            select(ServiceTemplateItem)
            .where(ServiceTemplateItem.template_id == template_id)
            .order_by(
                ServiceTemplateItem.position.asc(),
                ServiceTemplateItem.id.asc(),
            )
        )
    ).scalars().all()
    out = TemplateWithItems.model_validate(t)
    out.items = [TemplateItemRead.model_validate(i) for i in items]
    return out


@router.patch("/{template_id}", response_model=TemplateRead)
async def update_template(
    template_id: int,
    data: TemplateUpdate,
    db: DBSession,
    _: CurrentUser,
) -> TemplateRead:
    t = await _ensure_template(db, template_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(t, field, value)
    await db.flush()
    await db.refresh(t)
    return TemplateRead.model_validate(t)


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_template(
    template_id: int, db: DBSession, _: CurrentUser
) -> None:
    t = await _ensure_template(db, template_id)
    await db.delete(t)
    await db.flush()


# ---- items ----

@router.post(
    "/{template_id}/items",
    response_model=TemplateItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_template_item(
    template_id: int,
    data: TemplateItemCreate,
    db: DBSession,
    _: CurrentUser,
) -> TemplateItemRead:
    await _ensure_template(db, template_id)
    it = ServiceTemplateItem(
        template_id=template_id,
        position=data.position,
        description=data.description.strip(),
        unit=data.unit,
        default_quantity=data.default_quantity,
        default_unit_price=data.default_unit_price,
        default_cost_per_unit=data.default_cost_per_unit,
    )
    db.add(it)
    await db.flush()
    await db.refresh(it)
    return TemplateItemRead.model_validate(it)


@router.patch(
    "/{template_id}/items/{item_id}",
    response_model=TemplateItemRead,
)
async def update_template_item(
    template_id: int,
    item_id: int,
    data: TemplateItemUpdate,
    db: DBSession,
    _: CurrentUser,
) -> TemplateItemRead:
    it = (
        await db.execute(
            select(ServiceTemplateItem).where(
                ServiceTemplateItem.id == item_id,
                ServiceTemplateItem.template_id == template_id,
            )
        )
    ).scalar_one_or_none()
    if it is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(it, field, value)
    await db.flush()
    await db.refresh(it)
    return TemplateItemRead.model_validate(it)


@router.delete(
    "/{template_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_template_item(
    template_id: int,
    item_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    it = (
        await db.execute(
            select(ServiceTemplateItem).where(
                ServiceTemplateItem.id == item_id,
                ServiceTemplateItem.template_id == template_id,
            )
        )
    ).scalar_one_or_none()
    if it is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    await db.delete(it)
    await db.flush()


# ---- apply to soumission ----

@router.post("/{template_id}/apply", response_model=List[int])
async def apply_to_soumission(
    template_id: int,
    data: ApplyToSoumission,
    db: DBSession,
    _: CurrentUser,
) -> List[int]:
    """Copy every template item as a new SoumissionItem at the end of
    the target soumission. Returns the IDs of the created items."""
    t = await _ensure_template(db, template_id)
    sm = (
        await db.execute(
            select(Soumission).where(Soumission.id == data.soumission_id)
        )
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Soumission not found")

    items = (
        await db.execute(
            select(ServiceTemplateItem)
            .where(ServiceTemplateItem.template_id == template_id)
            .order_by(ServiceTemplateItem.position.asc())
        )
    ).scalars().all()

    # Compute next position on the soumission.
    current_max = (
        await db.execute(
            select(SoumissionItem.position)
            .where(SoumissionItem.soumission_id == sm.id)
            .order_by(SoumissionItem.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or -1

    created_ids: List[int] = []
    pos = int(current_max) + 1
    if not items:
        # Template has no sub-items → create a single line using the
        # template's own defaults (name + default_unit + price).
        si = SoumissionItem(
            soumission_id=sm.id,
            position=pos,
            description=t.name,
            unit=t.default_unit,
            quantity=1,
            unit_price=float(t.default_unit_price or 0),
            cost_per_unit=float(t.default_cost_per_unit or 0),
            total=float(t.default_unit_price or 0),
        )
        db.add(si)
        await db.flush()
        await db.refresh(si)
        created_ids.append(si.id)
    else:
        for it in items:
            total = round(
                float(it.default_quantity) * float(it.default_unit_price), 2
            )
            si = SoumissionItem(
                soumission_id=sm.id,
                position=pos,
                description=it.description,
                unit=it.unit,
                quantity=float(it.default_quantity),
                unit_price=float(it.default_unit_price),
                cost_per_unit=float(it.default_cost_per_unit or 0),
                total=total,
            )
            db.add(si)
            await db.flush()
            await db.refresh(si)
            created_ids.append(si.id)
            pos += 1

    return created_ids


# ---- apply to purchase order (#13) ----

@router.post("/{template_id}/apply-to-po", response_model=List[int])
async def apply_to_purchase_order(
    template_id: int,
    data: ApplyToPurchaseOrder,
    db: DBSession,
    _: CurrentUser,
) -> List[int]:
    """Copie chaque item du catalogue comme nouvelle ligne du bon de
    commande cible. Un PO est interne (sans taxes) : on reprend le prix
    unitaire du catalogue. Renvoie les IDs des lignes créées."""
    t = await _ensure_template(db, template_id)
    po = (
        await db.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.id == data.purchase_order_id
            )
        )
    ).scalar_one_or_none()
    if po is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Purchase order not found"
        )

    items = (
        await db.execute(
            select(ServiceTemplateItem)
            .where(ServiceTemplateItem.template_id == template_id)
            .order_by(ServiceTemplateItem.position.asc())
        )
    ).scalars().all()

    current_max = (
        await db.execute(
            select(PurchaseOrderItem.position)
            .where(PurchaseOrderItem.purchase_order_id == po.id)
            .order_by(PurchaseOrderItem.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    pos = (int(current_max) + 1) if current_max is not None else 0

    created_ids: List[int] = []
    if not items:
        # Catalogue sans sous-items → une seule ligne à partir des
        # valeurs par défaut du modèle.
        line = PurchaseOrderItem(
            purchase_order_id=po.id,
            position=pos,
            description=t.name,
            unit=t.default_unit,
            quantity=1,
            unit_price=float(t.default_unit_price or 0),
            total=float(t.default_unit_price or 0),
        )
        db.add(line)
        await db.flush()
        await db.refresh(line)
        created_ids.append(line.id)
    else:
        for it in items:
            total = round(
                float(it.default_quantity) * float(it.default_unit_price), 2
            )
            line = PurchaseOrderItem(
                purchase_order_id=po.id,
                position=pos,
                description=it.description,
                unit=it.unit,
                quantity=float(it.default_quantity),
                unit_price=float(it.default_unit_price),
                total=total,
            )
            db.add(line)
            await db.flush()
            await db.refresh(line)
            created_ids.append(line.id)
            pos += 1

    return created_ids
