"""Endpoints des défauts globaux pour les inputs d'analyse financière.

Phil veut pouvoir modifier les valeurs par défaut globales (taux d'intérêt
refi, % MDF prêteur B, taux d'intérêt prêteur B chantier) depuis l'UI de
la fiche d'analyse d'un lead — sans devoir éditer le code à chaque fois.

Quand un défaut change, les NOUVELLES analyses créées après le changement
utilisent la nouvelle valeur. Les analyses existantes ne sont PAS
écrasées (override par fiche conservé).

Restreint à admin/owner.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.prospection_analysis_default import ProspectionAnalysisDefault
from app.services.audit import log_action


router = APIRouter(
    prefix="/prospection/analysis-defaults",
    tags=["prospection-analysis-defaults"],
)


# ── Schémas Pydantic ──────────────────────────────────────────────


class AnalysisDefaultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    value_float: Optional[float] = None
    value_json: Optional[Any] = None
    label_fr: str
    description_fr: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: float
    group: Optional[str] = None
    updated_at: datetime
    updated_by_user_id: Optional[int] = None


class AnalysisDefaultUpdate(BaseModel):
    value_float: Optional[float] = Field(
        default=None,
        description="Nouvelle valeur scalaire (fraction, ex. 0.04 pour 4%).",
    )
    value_json: Optional[Any] = Field(
        default=None,
        description="Nouvelle valeur structurée (rarement utilisé).",
    )


# ── Endpoints ─────────────────────────────────────────────────────


@router.get("", response_model=List[AnalysisDefaultRead])
async def list_analysis_defaults(
    db: DBSession,
    user: RequireAdminOrOwner,
    group: Optional[str] = None,
) -> List[AnalysisDefaultRead]:
    """Liste tous les défauts. Filtrable par `group` (ex. ?group=refi)
    pour ne renvoyer que les défauts pertinents à un modal donné."""
    stmt = select(ProspectionAnalysisDefault).order_by(
        ProspectionAnalysisDefault.id.asc()
    )
    if group is not None:
        stmt = stmt.where(ProspectionAnalysisDefault.group == group)
    rows = (await db.execute(stmt)).scalars().all()
    return [AnalysisDefaultRead.model_validate(r) for r in rows]


@router.patch(
    "/{key}",
    response_model=AnalysisDefaultRead,
)
async def update_analysis_default(
    key: str,
    payload: AnalysisDefaultUpdate,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> AnalysisDefaultRead:
    """Modifie un défaut. Audit log obligatoire (Phil veut tracer qui
    a changé quoi). Validation des bornes min/max si présentes."""
    stmt = select(ProspectionAnalysisDefault).where(
        ProspectionAnalysisDefault.key == key
    )
    rec = (await db.execute(stmt)).scalar_one_or_none()
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Défaut introuvable : {key}",
        )

    old_value_float = rec.value_float
    old_value_json = rec.value_json

    if payload.value_float is not None:
        # Validation bornes (si définies).
        if rec.min_value is not None and payload.value_float < rec.min_value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Valeur < min ({rec.min_value}). "
                    f"Reçu : {payload.value_float}."
                ),
            )
        if rec.max_value is not None and payload.value_float > rec.max_value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Valeur > max ({rec.max_value}). "
                    f"Reçu : {payload.value_float}."
                ),
            )
        rec.value_float = payload.value_float

    if payload.value_json is not None:
        rec.value_json = payload.value_json

    rec.updated_by_user_id = getattr(user, "id", None)
    await db.flush()
    await db.refresh(rec)

    await log_action(
        db,
        user=user,
        action="prospection_analysis_default.updated",
        entity_type="prospection_analysis_default",
        entity_id=rec.id,
        details={
            "key": rec.key,
            "old_value_float": old_value_float,
            "new_value_float": rec.value_float,
            "old_value_json": old_value_json,
            "new_value_json": rec.value_json,
        },
    )

    return AnalysisDefaultRead.model_validate(rec)
