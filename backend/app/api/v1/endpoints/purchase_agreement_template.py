"""Singleton de valeurs par défaut pour les Promesses d'achat.

Routes :
    GET /prospection/pa-template     — lire les defaults (crée si absent)
    PUT /prospection/pa-template     — mettre à jour les defaults (admin)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.purchase_agreement_template import PurchaseAgreementTemplate


router = APIRouter(prefix="/prospection", tags=["pa-template"])


class PATemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    financing_kind: str
    financing_min_pct: Optional[float] = None
    financing_max_rate: Optional[float] = None
    financing_amortization_years: Optional[int] = None
    financing_min_term_years: Optional[int] = None
    inspection_enabled: bool
    inspection_days: int
    visit_units_enabled: bool
    water_septic_enabled: bool
    baux_text: Optional[str] = None
    inclusions_text: Optional[str] = None
    exclusions_text: Optional[str] = None
    other_conditions_text: Optional[str] = None
    default_buyer_1_name: Optional[str] = None
    default_buyer_1_address: Optional[str] = None
    default_buyer_1_email: Optional[str] = None
    default_buyer_1_phone_day: Optional[str] = None


class PATemplateUpdate(BaseModel):
    financing_kind: Optional[str] = None
    financing_min_pct: Optional[float] = None
    financing_max_rate: Optional[float] = None
    financing_amortization_years: Optional[int] = None
    financing_min_term_years: Optional[int] = None
    inspection_enabled: Optional[bool] = None
    inspection_days: Optional[int] = None
    visit_units_enabled: Optional[bool] = None
    water_septic_enabled: Optional[bool] = None
    baux_text: Optional[str] = None
    inclusions_text: Optional[str] = None
    exclusions_text: Optional[str] = None
    other_conditions_text: Optional[str] = None
    default_buyer_1_name: Optional[str] = None
    default_buyer_1_address: Optional[str] = None
    default_buyer_1_email: Optional[str] = None
    default_buyer_1_phone_day: Optional[str] = None


async def _get_or_create(db) -> PurchaseAgreementTemplate:
    row = (
        await db.execute(select(PurchaseAgreementTemplate).limit(1))
    ).scalar_one_or_none()
    if row is None:
        row = PurchaseAgreementTemplate(
            financing_kind="hypothecaire",
            inspection_enabled=True,
            inspection_days=10,
            visit_units_enabled=False,
            water_septic_enabled=False,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
    return row


@router.get(
    "/pa-template",
    response_model=PATemplateRead,
    summary="Valeurs par défaut PA",
)
async def get_template(db: DBSession, _: CurrentUser) -> PATemplateRead:
    row = await _get_or_create(db)
    return PATemplateRead.model_validate(row)


@router.put(
    "/pa-template",
    response_model=PATemplateRead,
    summary="Mettre à jour les valeurs par défaut (manager+)",
)
async def update_template(
    payload: PATemplateUpdate,
    db: DBSession,
    _: RequireManager,
) -> PATemplateRead:
    row = await _get_or_create(db)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    await db.flush()
    await db.refresh(row)
    return PATemplateRead.model_validate(row)
