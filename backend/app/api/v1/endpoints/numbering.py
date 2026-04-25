"""Settings UI pour la numérotation séquentielle des factures et
soumissions. Permet à l'admin d'aligner les compteurs avec une suite
QuickBooks existante (ex. dernière facture QB = 96 → prochain = 97).

    GET    /api/v1/settings/numbering
    PATCH  /api/v1/settings/numbering
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, DBSession
from app.models.numbering_counter import NumberingCounter
from app.services.numbering import _ensure_row


router = APIRouter(prefix="/settings/numbering", tags=["numbering"])


class NumberingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    next_facture_number: int
    next_soumission_number: int


class NumberingUpdate(BaseModel):
    next_facture_number: Optional[int] = Field(default=None, ge=1, le=999_999_999)
    next_soumission_number: Optional[int] = Field(default=None, ge=1, le=999_999_999)


@router.get("", response_model=NumberingRead)
async def get_numbering(
    db: DBSession, _: CurrentAdmin
) -> NumberingRead:
    row = await _ensure_row(db)
    await db.commit()
    return NumberingRead.model_validate(row)


@router.patch("", response_model=NumberingRead, status_code=status.HTTP_200_OK)
async def update_numbering(
    data: NumberingUpdate, db: DBSession, _: CurrentAdmin
) -> NumberingRead:
    row = await _ensure_row(db)
    if data.next_facture_number is not None:
        row.next_facture_number = data.next_facture_number
    if data.next_soumission_number is not None:
        row.next_soumission_number = data.next_soumission_number
    await db.flush()
    await db.commit()
    fresh = (
        await db.execute(
            select(NumberingCounter).where(NumberingCounter.id == 1)
        )
    ).scalar_one()
    return NumberingRead.model_validate(fresh)
