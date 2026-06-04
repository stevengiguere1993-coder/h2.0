"""Endpoints des valeurs par defaut des soumissions devis_dev.

Phase 6 (juin 2026) - Phil regle depuis l'UI (bouton Valeurs par defaut sur
l'ecran des soumissions devis_dev) les valeurs appliquees a CHAQUE nouvelle
soumission : taux horaires (dev, charge de projet), commission closer, marges
(initiale, recurrente), et un template optionnel de modules/fonctionnalites de
base. Plus aucun hard-code cote application.

Quand un defaut change, les NOUVELLES soumissions creees apres le changement
utilisent la nouvelle valeur. Les soumissions existantes ne sont PAS ecrasees.

Restreint a admin/owner. Audit log sur modification.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.devlog_soumission_defaults import (
    DEVLOG_SOUMISSION_DEFAULT_VALUES,
    DEVLOG_SOUMISSION_DEFAULTS_ID,
    DevlogSoumissionDefaults,
)
from app.services.audit import log_action

router = APIRouter(
    prefix="/devlog/soumission-defaults",
    tags=["devlog-soumission-defaults"],
)


# -- Schemas Pydantic -------------------------------------------------------


class BaseModuleFeature(BaseModel):
    """Une fonctionnalite de base d'un module template."""

    description: str = Field(..., min_length=1, max_length=500)
    heures: float = Field(default=0, ge=0)


class BaseModuleTemplate(BaseModel):
    """Un module template (nom + fonctionnalites de base). [LEGACY]"""

    name: str = Field(..., min_length=1, max_length=255)
    features: List[BaseModuleFeature] = Field(default_factory=list)


class DefaultLineItem(BaseModel):
    """Une ligne par defaut (description + heures).

    Utilisee pour ``default_features_json`` (fonctionnalites pre-remplies a
    chaque nouveau module) et ``default_manager_tasks_json`` (taches du charge
    de projet pre-remplies a chaque nouvelle soumission)."""

    description: str = Field(..., min_length=1, max_length=500)
    heures: float = Field(default=0, ge=0)


class SoumissionDefaultsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    taux_dev_horaire: Optional[float] = None
    taux_manager_horaire: Optional[float] = None
    commission_closer_pct: Optional[float] = None
    marge_initiale_pct: Optional[float] = None
    marge_recurrente_pct: Optional[float] = None
    # [LEGACY] conserve en lecture pour retrocompat, plus expose dans l'UI.
    base_modules_json: Optional[List[BaseModuleTemplate]] = None
    # Fonctionnalites pre-remplies a chaque nouveau module.
    default_features_json: Optional[List[DefaultLineItem]] = None
    # Taches du charge de projet pre-remplies a chaque nouvelle soumission.
    default_manager_tasks_json: Optional[List[DefaultLineItem]] = None
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[int] = None


class SoumissionDefaultsUpdate(BaseModel):
    taux_dev_horaire: Optional[float] = Field(default=None, ge=0)
    taux_manager_horaire: Optional[float] = Field(default=None, ge=0)
    commission_closer_pct: Optional[float] = Field(default=None, ge=0, le=100)
    marge_initiale_pct: Optional[float] = Field(default=None, ge=0, le=500)
    marge_recurrente_pct: Optional[float] = Field(default=None, ge=0, le=500)
    # [LEGACY] template de modules de base : plus modifiable depuis l'UI mais
    # garde au cas ou un appelant l'envoie encore. ``[]`` vide, ``None`` ignore.
    base_modules_json: Optional[List[BaseModuleTemplate]] = None
    # Fonctionnalites par defaut (a chaque nouveau module). Passer ``[]`` pour
    # vider, ``None`` (absent) pour ne pas y toucher.
    default_features_json: Optional[List[DefaultLineItem]] = None
    # Taches du charge de projet par defaut. Passer ``[]`` pour vider, ``None``
    # (absent) pour ne pas y toucher.
    default_manager_tasks_json: Optional[List[DefaultLineItem]] = None


# -- Helpers ----------------------------------------------------------------


async def _get_or_create_row(db) -> DevlogSoumissionDefaults:
    """Recupere la ligne singleton (id=1), la cree avec les valeurs
    historiques si absente (idempotent - couvre un boot ou le seed n'a pas
    encore tourne)."""
    rec = (
        await db.execute(
            select(DevlogSoumissionDefaults).where(
                DevlogSoumissionDefaults.id == DEVLOG_SOUMISSION_DEFAULTS_ID
            )
        )
    ).scalar_one_or_none()
    if rec is None:
        rec = DevlogSoumissionDefaults(
            id=DEVLOG_SOUMISSION_DEFAULTS_ID,
            taux_dev_horaire=DEVLOG_SOUMISSION_DEFAULT_VALUES["taux_dev_horaire"],
            taux_manager_horaire=DEVLOG_SOUMISSION_DEFAULT_VALUES[
                "taux_manager_horaire"
            ],
            commission_closer_pct=DEVLOG_SOUMISSION_DEFAULT_VALUES[
                "commission_closer_pct"
            ],
            marge_initiale_pct=DEVLOG_SOUMISSION_DEFAULT_VALUES["marge_initiale_pct"],
            marge_recurrente_pct=DEVLOG_SOUMISSION_DEFAULT_VALUES[
                "marge_recurrente_pct"
            ],
            base_modules_json=[],
        )
        db.add(rec)
        await db.flush()
        await db.refresh(rec)
    return rec


# -- Endpoints --------------------------------------------------------------


@router.get("", response_model=SoumissionDefaultsRead)
async def get_soumission_defaults(
    db: DBSession,
    user: RequireAdminOrOwner,
) -> SoumissionDefaultsRead:
    """Lit les valeurs par defaut appliquees aux nouvelles soumissions."""
    rec = await _get_or_create_row(db)
    return SoumissionDefaultsRead.model_validate(rec)


@router.put("", response_model=SoumissionDefaultsRead)
async def update_soumission_defaults(
    payload: SoumissionDefaultsUpdate,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> SoumissionDefaultsRead:
    """Modifie les valeurs par defaut. Audit log obligatoire. Seuls les champs
    fournis (``model_fields_set``) sont modifies - un champ absent garde sa
    valeur, ``base_modules_json=[]`` vide le template."""
    rec = await _get_or_create_row(db)

    old = {
        "taux_dev_horaire": rec.taux_dev_horaire,
        "taux_manager_horaire": rec.taux_manager_horaire,
        "commission_closer_pct": rec.commission_closer_pct,
        "marge_initiale_pct": rec.marge_initiale_pct,
        "marge_recurrente_pct": rec.marge_recurrente_pct,
        "base_modules_count": len(rec.base_modules_json or []),
        "default_features_count": len(rec.default_features_json or []),
        "default_manager_tasks_count": len(rec.default_manager_tasks_json or []),
    }

    fields_set = payload.model_fields_set
    if "taux_dev_horaire" in fields_set:
        rec.taux_dev_horaire = payload.taux_dev_horaire
    if "taux_manager_horaire" in fields_set:
        rec.taux_manager_horaire = payload.taux_manager_horaire
    if "commission_closer_pct" in fields_set:
        rec.commission_closer_pct = payload.commission_closer_pct
    if "marge_initiale_pct" in fields_set:
        rec.marge_initiale_pct = payload.marge_initiale_pct
    if "marge_recurrente_pct" in fields_set:
        rec.marge_recurrente_pct = payload.marge_recurrente_pct
    if "base_modules_json" in fields_set:
        # [LEGACY] Serialise les sous-modeles Pydantic en dict JSON-stockables.
        rec.base_modules_json = [
            m.model_dump() for m in (payload.base_modules_json or [])
        ]
    if "default_features_json" in fields_set:
        rec.default_features_json = [
            m.model_dump() for m in (payload.default_features_json or [])
        ]
    if "default_manager_tasks_json" in fields_set:
        rec.default_manager_tasks_json = [
            m.model_dump() for m in (payload.default_manager_tasks_json or [])
        ]

    rec.updated_by_user_id = getattr(user, "id", None)
    await db.flush()
    await db.refresh(rec)

    await log_action(
        db,
        user=user,
        action="devlog_soumission_default.updated",
        entity_type="devlog_soumission_default",
        entity_id=rec.id,
        details={
            "old": old,
            "new": {
                "taux_dev_horaire": rec.taux_dev_horaire,
                "taux_manager_horaire": rec.taux_manager_horaire,
                "commission_closer_pct": rec.commission_closer_pct,
                "marge_initiale_pct": rec.marge_initiale_pct,
                "marge_recurrente_pct": rec.marge_recurrente_pct,
                "base_modules_count": len(rec.base_modules_json or []),
                "default_features_count": len(rec.default_features_json or []),
                "default_manager_tasks_count": len(
                    rec.default_manager_tasks_json or []
                ),
            },
        },
    )

    return SoumissionDefaultsRead.model_validate(rec)
