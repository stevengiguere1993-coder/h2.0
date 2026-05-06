"""Pipeline des deals — CRUD pour les opportunités d'achat suivies
en mode Monday-like dans Prospection.

Endpoints :
  GET    /api/v1/prospection/deals      → liste triée par priorité
  POST   /api/v1/prospection/deals      → crée un deal (adresse + priorité)
  PATCH  /api/v1/prospection/deals/{id} → met à jour adresse / priorité
  DELETE /api/v1/prospection/deals/{id} → supprime
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, select

from app.api.deps import CurrentUser, DBSession
from app.models.prospection_deal import PRIORITY_ORDER, ProspectionDeal


router = APIRouter(prefix="/prospection/deals", tags=["prospection-deals"])


# Validation : on accepte uniquement les valeurs canoniques côté API
# pour ne pas se retrouver avec des typos en DB.
PRIORITY_PATTERN = r"^(urgent|eleve|moyenne|en_attente|a_venir)$"


class DealCreate(BaseModel):
    address: str = Field(..., min_length=1, max_length=500)
    priority: str = Field(default="moyenne", pattern=PRIORITY_PATTERN)


class DealUpdate(BaseModel):
    address: Optional[str] = Field(default=None, min_length=1, max_length=500)
    priority: Optional[str] = Field(default=None, pattern=PRIORITY_PATTERN)


class DealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    address: str
    priority: str
    created_at: datetime
    updated_at: datetime


def _priority_rank_expr():
    """SQL CASE qui mappe priority → rang numérique (0 = plus urgent)
    pour qu'ORDER BY trie correctement urgent → a_venir."""
    whens = {p: i for i, p in enumerate(PRIORITY_ORDER)}
    return case(whens, value=ProspectionDeal.priority, else_=99)


@router.get("", response_model=List[DealRead])
async def list_deals(
    db: DBSession,
    _: CurrentUser,
) -> List[DealRead]:
    rows = (
        await db.execute(
            select(ProspectionDeal).order_by(
                _priority_rank_expr(),
                ProspectionDeal.created_at.desc(),
            )
        )
    ).scalars().all()
    return [DealRead.model_validate(r) for r in rows]


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
async def create_deal(
    data: DealCreate,
    db: DBSession,
    _: CurrentUser,
) -> DealRead:
    deal = ProspectionDeal(
        address=data.address.strip(),
        priority=data.priority,
    )
    db.add(deal)
    await db.flush()
    await db.refresh(deal)
    return DealRead.model_validate(deal)


@router.patch("/{deal_id}", response_model=DealRead)
async def update_deal(
    deal_id: int,
    data: DealUpdate,
    db: DBSession,
    _: CurrentUser,
) -> DealRead:
    deal = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal introuvable.")
    if data.address is not None:
        deal.address = data.address.strip()
    if data.priority is not None:
        deal.priority = data.priority
    await db.flush()
    await db.refresh(deal)
    return DealRead.model_validate(deal)


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal(
    deal_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    deal = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal introuvable.")
    await db.delete(deal)
    await db.flush()
