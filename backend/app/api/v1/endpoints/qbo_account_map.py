"""Settings UI pour le mapping mode_paiement → compte QBO.

    GET    /api/v1/settings/qbo-accounts
    PATCH  /api/v1/settings/qbo-accounts

L'admin saisit les noms exacts (tels qu'ils apparaissent dans son
QB Plan comptable) pour chaque mode de paiement. Au moment du push,
le service achat_qbo résout ces noms en Account.Id via une query
QBO live.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, DBSession
from app.models.qbo_account_map import QboAccountMap


router = APIRouter(prefix="/settings/qbo-accounts", tags=["qbo-account-map"])


class QboAccountMapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    default_expense_account: Optional[str] = None
    cheque_horizon_account: Optional[str] = None
    cc_steven_account: Optional[str] = None
    cc_michael_account: Optional[str] = None
    cc_olivier_account: Optional[str] = None
    cc_christian_account: Optional[str] = None
    labour_expense_account: Optional[str] = None
    labour_clearing_account: Optional[str] = None


class QboAccountMapUpdate(BaseModel):
    default_expense_account: Optional[str] = Field(default=None, max_length=255)
    cheque_horizon_account: Optional[str] = Field(default=None, max_length=255)
    cc_steven_account: Optional[str] = Field(default=None, max_length=255)
    cc_michael_account: Optional[str] = Field(default=None, max_length=255)
    cc_olivier_account: Optional[str] = Field(default=None, max_length=255)
    cc_christian_account: Optional[str] = Field(default=None, max_length=255)
    labour_expense_account: Optional[str] = Field(default=None, max_length=255)
    labour_clearing_account: Optional[str] = Field(default=None, max_length=255)


async def _ensure_row(db) -> QboAccountMap:
    row = (
        await db.execute(select(QboAccountMap).where(QboAccountMap.id == 1))
    ).scalar_one_or_none()
    if row is None:
        row = QboAccountMap(id=1)
        db.add(row)
        await db.flush()
    return row


@router.get("", response_model=QboAccountMapRead)
async def get_account_map(
    db: DBSession, _: CurrentAdmin
) -> QboAccountMapRead:
    row = await _ensure_row(db)
    await db.commit()
    return QboAccountMapRead.model_validate(row)


@router.patch("", response_model=QboAccountMapRead)
async def update_account_map(
    data: QboAccountMapUpdate, db: DBSession, _: CurrentAdmin
) -> QboAccountMapRead:
    row = await _ensure_row(db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value or None)
    await db.flush()
    await db.commit()
    fresh = (
        await db.execute(select(QboAccountMap).where(QboAccountMap.id == 1))
    ).scalar_one()
    return QboAccountMapRead.model_validate(fresh)
