"""Endpoints des valeurs par defaut cout / refacturation / marge des bons.

Phil regle depuis Parametres -> Bons de travail les defauts appliques a chaque
nouvelle ligne d'un bon interne (cout horaire 35, refac horaire 55, marge 10).
Quand un defaut change, les NOUVELLES lignes creees apres le changement
l'utilisent. Les lignes existantes ne sont PAS reecrites.

Restreint a admin/owner. Audit log sur modification.

    GET /api/v1/construction/bon-defaults
    PUT /api/v1/construction/bon-defaults
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, DBSession, RequireAdminOrOwner
from app.services.audit import log_action
from app.services.bon_defaults import get_or_create_bon_defaults

router = APIRouter(
    prefix="/construction/bon-defaults",
    tags=["construction-bon-defaults"],
)


class BonDefaultsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    default_cost_rate: Optional[float] = None
    default_bill_rate: Optional[float] = None
    default_marge_pct: Optional[float] = None
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[int] = None


class BonDefaultsUpdate(BaseModel):
    default_cost_rate: Optional[float] = Field(default=None, ge=0, le=100000)
    default_bill_rate: Optional[float] = Field(default=None, ge=0, le=100000)
    default_marge_pct: Optional[float] = Field(default=None, ge=0, le=500)


@router.get("", response_model=BonDefaultsRead)
async def get_bon_defaults_settings(
    db: DBSession,
    _user: CurrentUser,
) -> BonDefaultsRead:
    """Lit les defauts cout/refac/marge appliques aux nouvelles lignes de bon.

    Lisible par tout utilisateur authentifie : la fiche bon et le formulaire de
    creation s'en servent pour pre-remplir, et ces taux sont deja visibles sur
    chaque ligne. La modification (PUT) reste reservee a admin/owner."""
    rec = await get_or_create_bon_defaults(db)
    return BonDefaultsRead.model_validate(rec)


@router.put("", response_model=BonDefaultsRead)
async def update_bon_defaults_settings(
    payload: BonDefaultsUpdate,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> BonDefaultsRead:
    """Modifie les defauts. Audit log obligatoire. Seuls les champs fournis
    (``model_fields_set``) sont modifies ; un champ absent garde sa valeur."""
    rec = await get_or_create_bon_defaults(db)

    old = {
        "default_cost_rate": rec.default_cost_rate,
        "default_bill_rate": rec.default_bill_rate,
        "default_marge_pct": rec.default_marge_pct,
    }

    fields_set = payload.model_fields_set
    if "default_cost_rate" in fields_set:
        rec.default_cost_rate = payload.default_cost_rate
    if "default_bill_rate" in fields_set:
        rec.default_bill_rate = payload.default_bill_rate
    if "default_marge_pct" in fields_set:
        rec.default_marge_pct = payload.default_marge_pct

    rec.updated_by_user_id = getattr(user, "id", None)
    await db.flush()
    await db.refresh(rec)

    await log_action(
        db,
        user=user,
        action="construction_bon_default.updated",
        entity_type="construction_bon_default",
        entity_id=rec.id,
        details={
            "old": old,
            "new": {
                "default_cost_rate": rec.default_cost_rate,
                "default_bill_rate": rec.default_bill_rate,
                "default_marge_pct": rec.default_marge_pct,
            },
        },
    )

    return BonDefaultsRead.model_validate(rec)
