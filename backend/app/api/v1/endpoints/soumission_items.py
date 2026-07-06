"""
Nested endpoints for soumission line items:
    GET    /api/v1/soumissions/{soumission_id}/items
    POST   /api/v1/soumissions/{soumission_id}/items
    PATCH  /api/v1/soumissions/{soumission_id}/items/{item_id}
    DELETE /api/v1/soumissions/{soumission_id}/items/{item_id}

All routes are staff-only (CurrentUser). Le backend recalcule
automatiquement les totaux de la soumission parente (subtotal / TPS
/ TVQ / total) après chaque mutation d'item, puis propage à
`Project.budget` si un projet est lié. Comme ça la kanban des
soumissions ET la fiche projet restent toujours synchros sans
dépendre d'un PATCH manuel côté frontend.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DBSession
from app.models.project import Project
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem


router = APIRouter(prefix="/soumissions", tags=["soumission-items"])


# Taux taxes québécoises — source unique de vérité (app.core.taxes).
from app.core.taxes import TPS_RATE, TVQ_RATE  # noqa: E402,F401


async def _recompute_soumission_totals(db, soumission_id: int) -> None:
    """Recalcule subtotal / tps / tvq / total à partir des items de la
    soumission + propage au budget des projets liés.

    Appelé après chaque create / update / delete d'un SoumissionItem.
    Garantit que la kanban et la fiche projet reflètent toujours la
    réalité, sans dépendre d'un PATCH frontend séparé.
    """
    items = (
        await db.execute(
            select(SoumissionItem).where(
                SoumissionItem.soumission_id == soumission_id
            )
        )
    ).scalars().all()

    subtotal = round(sum(float(it.total or 0) for it in items), 2)
    tps_base = round(
        sum(float(it.total or 0) for it in items if it.tps_applicable), 2
    )
    tvq_base = round(
        sum(float(it.total or 0) for it in items if it.tvq_applicable), 2
    )
    tps = round(tps_base * TPS_RATE, 2)
    tvq = round(tvq_base * TVQ_RATE, 2)
    total = round(subtotal + tps + tvq, 2)

    sm = (
        await db.execute(select(Soumission).where(Soumission.id == soumission_id))
    ).scalar_one_or_none()
    if sm is None:
        return
    sm.subtotal = subtotal
    sm.tps = tps
    sm.tvq = tvq
    sm.total = total

    # Sync : budget des projets liés (même hook que business.update_item).
    await db.execute(
        update(Project)
        .where(Project.soumission_id == soumission_id)
        .values(budget=total)
    )
    await db.flush()


class SoumissionItemCreate(BaseModel):
    position: int = Field(default=0, ge=0)
    description: str = Field(..., min_length=1, max_length=4000)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: float = Field(default=1)
    unit_price: float = Field(default=0)
    cost_per_unit: float = Field(default=0)
    tps_applicable: bool = Field(default=True)
    tvq_applicable: bool = Field(default=True)
    kind: str = Field(default="service", pattern="^(service|frais|rabais)$")


class SoumissionItemUpdate(BaseModel):
    position: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[float] = Field(default=None)
    unit_price: Optional[float] = Field(default=None)
    cost_per_unit: Optional[float] = Field(default=None)
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
    cost_per_unit: float = 0
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
    # Garde-fou anti-perte : pour une ligne « service », si aucun prix
    # unitaire n'est saisi (laissé vide => 0) mais qu'un coûtant l'est,
    # on facture AU MOINS le coûtant. Évite de vendre à 0 un item oublié.
    if data.kind == "service" and unit_price <= 0 and data.cost_per_unit > 0:
        unit_price = data.cost_per_unit
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
        cost_per_unit=data.cost_per_unit,
        total=total,
        tps_applicable=(False if data.kind == "frais" else data.tps_applicable),
        tvq_applicable=(False if data.kind == "frais" else data.tvq_applicable),
        kind=data.kind,
    )
    db.add(item)
    await db.flush()
    await _recompute_soumission_totals(db, soumission_id)
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
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    # Garde-fou anti-perte (cf. create_item) : ligne « service » sans prix
    # unitaire mais avec un coûtant => on facture au moins le coûtant.
    if (
        item.kind == "service"
        and float(item.unit_price or 0) <= 0
        and float(item.cost_per_unit or 0) > 0
    ):
        item.unit_price = item.cost_per_unit
    # Re-derive total whenever qty / prix / coûtant change (le coûtant
    # peut relever le prix via le garde-fou ci-dessus).
    if (
        "quantity" in update_data
        or "unit_price" in update_data
        or "cost_per_unit" in update_data
    ):
        item.total = round(float(item.quantity) * float(item.unit_price), 2)
    await db.flush()
    await _recompute_soumission_totals(db, soumission_id)
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
    await _recompute_soumission_totals(db, soumission_id)


# Backfill : endpoint admin pour resynchroniser TOUTES les soumissions
# existantes dont les totaux ne reflètent pas leurs items.
@router.post(
    "/recompute-all",
    summary="Backfill : recalcule subtotal/total de toutes les soumissions",
)
async def recompute_all_soumissions(
    db: DBSession, _: CurrentUser
) -> dict:
    ids = (
        await db.execute(select(Soumission.id))
    ).scalars().all()
    for sid in ids:
        await _recompute_soumission_totals(db, int(sid))
    return {"recomputed": len(ids)}
