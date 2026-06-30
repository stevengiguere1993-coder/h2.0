"""Nested CRUD for line items on a Bon de travail.

Moteur de refacturation du bon INTERNE :
  - ``heure``         → main-d'œuvre (nos gars). quantity = nb d'heures,
                         cost_rate = taux coûtant (ex. 35 $), bill_rate =
                         taux facturé (ex. 55 $). Facturé = heures ×
                         bill_rate × (1 + marge%). Coût = heures × cost_rate.
  - ``materiel``      → coût d'achat (cost_rate) × quantité, facturé
                         coût + marge%.
  - ``sous_traitant`` → coût du sous-traitant (cost_rate), facturé
                         coût + marge%.
Le montant du bon (``amount``) est recalculé = somme des lignes facturées
(profit = facturé − coût, exposé côté Construction uniquement).
"""

from typing import List, Optional, Tuple

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.bon_item import BonItem
from app.models.bon_travail import BonTravail
from app.models.employe import Employe
from app.models.punch import Punch


router = APIRouter(prefix="/bons-travail", tags=["bon-items"])


class BonItemCreate(BaseModel):
    position: int = Field(default=0, ge=0)
    description: str = Field(..., min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: float = Field(default=1, ge=0)
    unit_price: float = Field(default=0, ge=0)
    # ── Refacturation ──
    item_type: str = Field(default="materiel", max_length=16)
    cost_rate: Optional[float] = Field(default=None, ge=0)
    bill_rate: Optional[float] = Field(default=None, ge=0)
    marge_pct: Optional[float] = Field(default=None, ge=0)
    employe_id: Optional[int] = None
    sous_traitant_id: Optional[int] = None


class BonItemUpdate(BaseModel):
    position: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[float] = Field(default=None, ge=0)
    unit_price: Optional[float] = Field(default=None, ge=0)
    item_type: Optional[str] = Field(default=None, max_length=16)
    cost_rate: Optional[float] = Field(default=None, ge=0)
    bill_rate: Optional[float] = Field(default=None, ge=0)
    marge_pct: Optional[float] = Field(default=None, ge=0)
    employe_id: Optional[int] = None
    sous_traitant_id: Optional[int] = None


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
    item_type: str
    cost_rate: Optional[float]
    bill_rate: Optional[float]
    marge_pct: Optional[float]
    cost_total: float
    employe_id: Optional[int]
    sous_traitant_id: Optional[int]


def _compute_totals(
    item_type: Optional[str],
    quantity: Optional[float],
    cost_rate: Optional[float],
    bill_rate: Optional[float],
    unit_price: Optional[float],
    marge_pct: Optional[float],
) -> Tuple[float, float]:
    """Retourne (total_facturé, coût_total) d'une ligne."""
    q = float(quantity or 0)
    marge = 1 + float(marge_pct or 0) / 100.0
    cr = float(cost_rate) if cost_rate is not None else None
    if item_type == "heure":
        base = float(bill_rate or 0)
        total = round(q * base * marge, 2)
        cost_total = round(q * (cr or 0), 2)
    elif item_type in ("materiel", "sous_traitant"):
        if cr is not None:
            total = round(q * cr * marge, 2)
            cost_total = round(q * cr, 2)
        else:
            # Legacy : unit_price = prix facturé, coût inconnu.
            total = round(q * float(unit_price or 0), 2)
            cost_total = 0.0
    else:
        total = round(q * float(unit_price or 0), 2)
        cost_total = 0.0
    return total, cost_total


async def _ensure_bon(db, bon_id: int) -> BonTravail:
    record = (
        await db.execute(select(BonTravail).where(BonTravail.id == bon_id))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bon de travail not found")
    return record


async def _recompute_bon_amount(db, bon_id: int) -> None:
    """Roll-up : montant du bon = somme des lignes facturées (bon interne)."""
    bon = (
        await db.execute(select(BonTravail).where(BonTravail.id == bon_id))
    ).scalar_one_or_none()
    if bon is None or (bon.kind or "construction") != "interne":
        return
    rows = (
        await db.execute(
            select(BonItem.total).where(BonItem.bon_id == bon_id)
        )
    ).scalars().all()
    if (bon.bon_type or "") == "garantie":
        bon.amount = 0
    else:
        bon.amount = round(sum(float(t or 0) for t in rows), 2)
    await db.flush()


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


class BonPunchRead(BaseModel):
    id: int
    employe_id: int
    employe_name: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    hours: Optional[float]
    task: Optional[str]
    approved: bool


@router.get("/{bon_id}/punches", response_model=List[BonPunchRead])
async def list_bon_punches(
    bon_id: int, db: DBSession, _: CurrentUser
) -> List[BonPunchRead]:
    """Heures pointées directement sur ce bon (entretien interne)."""
    await _ensure_bon(db, bon_id)
    rows = (
        await db.execute(
            select(Punch, Employe.full_name)
            .outerjoin(Employe, Employe.id == Punch.employe_id)
            .where(Punch.bon_travail_id == bon_id)
            .order_by(Punch.started_at.desc())
        )
    ).all()
    out: List[BonPunchRead] = []
    for p, emp_name in rows:
        out.append(
            BonPunchRead(
                id=p.id,
                employe_id=p.employe_id,
                employe_name=emp_name,
                started_at=p.started_at.isoformat() if p.started_at else None,
                ended_at=p.ended_at.isoformat() if p.ended_at else None,
                hours=float(p.hours) if p.hours is not None else None,
                task=p.task,
                approved=bool(p.approved),
            )
        )
    return out


@router.post(
    "/{bon_id}/items",
    response_model=BonItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_item(
    bon_id: int, data: BonItemCreate, db: DBSession, _: CurrentUser
) -> BonItemRead:
    await _ensure_bon(db, bon_id)
    total, cost_total = _compute_totals(
        data.item_type,
        data.quantity,
        data.cost_rate,
        data.bill_rate,
        data.unit_price,
        data.marge_pct,
    )
    item = BonItem(
        bon_id=bon_id,
        position=data.position,
        description=data.description.strip(),
        unit=(data.unit or None),
        quantity=data.quantity,
        unit_price=data.unit_price,
        total=total,
        item_type=data.item_type or "materiel",
        cost_rate=data.cost_rate,
        bill_rate=data.bill_rate,
        marge_pct=data.marge_pct,
        cost_total=cost_total,
        employe_id=data.employe_id,
        sous_traitant_id=data.sous_traitant_id,
    )
    db.add(item)
    await db.flush()
    await _recompute_bon_amount(db, bon_id)
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
    # Recalcul systématique du total + coût (toute modif de taux/quantité/
    # marge/type le change).
    total, cost_total = _compute_totals(
        item.item_type,
        item.quantity,
        item.cost_rate,
        item.bill_rate,
        item.unit_price,
        item.marge_pct,
    )
    item.total = total
    item.cost_total = cost_total
    await db.flush()
    await _recompute_bon_amount(db, bon_id)
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
    await _recompute_bon_amount(db, bon_id)
