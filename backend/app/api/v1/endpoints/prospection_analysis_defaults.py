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

import uuid
from datetime import datetime
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

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
    # Mai 2026 : statut « finançable par défaut » pour les items des
    # groupes ``mdf_frais`` / ``mdf_pct``. None pour les autres groupes
    # (non applicable).
    financable_par_defaut: Optional[bool] = None
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
    financable_par_defaut: Optional[bool] = Field(
        default=None,
        description=(
            "Statut « finançable par défaut » pour les items MDF "
            "(groupes mdf_frais / mdf_pct). Pré-coche la case "
            "« Finançable » sur les nouvelles fiches d'analyse."
        ),
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
    old_financable = rec.financable_par_defaut

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

    # Mai 2026 : mise à jour du flag « finançable par défaut » pour les
    # items MDF. On accepte `False` explicitement (pas juste `None`) :
    # `model_fields_set` permet de distinguer absence vs envoi de
    # `false` dans le payload JSON.
    financable_touched = "financable_par_defaut" in payload.model_fields_set
    if financable_touched:
        rec.financable_par_defaut = payload.financable_par_defaut

    rec.updated_by_user_id = getattr(user, "id", None)
    await db.flush()
    await db.refresh(rec)

    audit_details: dict[str, Any] = {
        "key": rec.key,
        "old_value_float": old_value_float,
        "new_value_float": rec.value_float,
        "old_value_json": old_value_json,
        "new_value_json": rec.value_json,
    }
    if financable_touched:
        audit_details["old_financable_par_defaut"] = old_financable
        audit_details["new_financable_par_defaut"] = rec.financable_par_defaut

    # Action discriminée : si le toggle « finançable par défaut » est
    # le seul changement, on log avec une action dédiée pour faciliter
    # les recherches ultérieures.
    action = (
        "prospection_analysis_default.financable_default_updated"
        if (
            financable_touched
            and payload.value_float is None
            and payload.value_json is None
        )
        else "prospection_analysis_default.updated"
    )
    await log_action(
        db,
        user=user,
        action=action,
        entity_type="prospection_analysis_default",
        entity_id=rec.id,
        details=audit_details,
    )

    return AnalysisDefaultRead.model_validate(rec)


# ── Frais de démarrage PERSONNALISÉS (dynamiques, juin 2026) ────────
#
# Postes de frais de démarrage ajoutables / retirables par l'admin.
# Stockés dans la LISTE ``value_json`` de la clé ``frais_mdf_custom``
# (groupe ``mdf_frais``). Routes dédiées par item (POST/PATCH/DELETE)
# pour éviter les races d'un PATCH de liste complète. Restreint à
# admin/owner, chaque mutation est tracée (audit log).

_FRAIS_CUSTOM_KEY = "frais_mdf_custom"
_FraisCustomType = Literal["fixe", "pct_prix_achat", "pct_financement"]


class FraisCustomItem(BaseModel):
    """Un poste de frais de démarrage personnalisé."""

    id: str
    label_fr: str
    # "fixe" = montant $ ; "pct_prix_achat" = % du prix d'achat ;
    # "pct_financement" = % du financement refi (best APH).
    type_montant: _FraisCustomType
    # Montant $ (type "fixe") ou taux en POURCENTAGE (5.0 = 5 %) pour
    # les types pct_*. Convention alignée sur les autres % de la table.
    valeur: float
    financable_par_defaut: bool = False


class FraisCustomCreate(BaseModel):
    label_fr: str = Field(min_length=1, max_length=120)
    type_montant: _FraisCustomType
    valeur: float = Field(ge=0)
    financable_par_defaut: bool = False


class FraisCustomUpdate(BaseModel):
    label_fr: Optional[str] = Field(default=None, min_length=1, max_length=120)
    type_montant: Optional[_FraisCustomType] = None
    valeur: Optional[float] = Field(default=None, ge=0)
    financable_par_defaut: Optional[bool] = None


async def _get_frais_custom_row(db) -> ProspectionAnalysisDefault:
    """Récupère (ou crée si absente) la ligne ``frais_mdf_custom``."""
    rec = (
        await db.execute(
            select(ProspectionAnalysisDefault).where(
                ProspectionAnalysisDefault.key == _FRAIS_CUSTOM_KEY
            )
        )
    ).scalar_one_or_none()
    if rec is None:
        # La ligne est normalement seedée au boot ; on la crée à la
        # volée si elle manque (déploiement antérieur au seed).
        rec = ProspectionAnalysisDefault(
            key=_FRAIS_CUSTOM_KEY,
            value_json=[],
            label_fr="Frais de démarrage personnalisés (liste)",
            description_fr=(
                "Liste des postes de frais de démarrage personnalisés "
                "ajoutés par l'admin."
            ),
            step=0.01,
            group="mdf_frais",
        )
        db.add(rec)
        await db.flush()
    return rec


def _current_items(rec: ProspectionAnalysisDefault) -> list[dict]:
    items = rec.value_json
    return list(items) if isinstance(items, list) else []


@router.get(
    "/frais-custom",
    response_model=List[FraisCustomItem],
)
async def list_frais_custom(
    db: DBSession,
    user: RequireAdminOrOwner,
) -> List[FraisCustomItem]:
    """Liste les postes de frais de démarrage personnalisés."""
    rec = await _get_frais_custom_row(db)
    return [FraisCustomItem(**it) for it in _current_items(rec)]


@router.post(
    "/frais-custom",
    response_model=FraisCustomItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_frais_custom(
    payload: FraisCustomCreate,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> FraisCustomItem:
    """Ajoute un poste de frais de démarrage personnalisé. Audit log."""
    rec = await _get_frais_custom_row(db)
    items = _current_items(rec)
    new_item = {
        "id": uuid.uuid4().hex,
        "label_fr": payload.label_fr,
        "type_montant": payload.type_montant,
        "valeur": float(payload.valeur),
        "financable_par_defaut": bool(payload.financable_par_defaut),
    }
    items.append(new_item)
    rec.value_json = items
    flag_modified(rec, "value_json")
    rec.updated_by_user_id = getattr(user, "id", None)
    await db.flush()

    await log_action(
        db,
        user=user,
        action="prospection_analysis_default.frais_custom_created",
        entity_type="prospection_analysis_default",
        entity_id=rec.id,
        details={"key": _FRAIS_CUSTOM_KEY, "item": new_item},
    )
    return FraisCustomItem(**new_item)


@router.patch(
    "/frais-custom/{item_id}",
    response_model=FraisCustomItem,
)
async def update_frais_custom(
    item_id: str,
    payload: FraisCustomUpdate,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> FraisCustomItem:
    """Modifie un poste personnalisé existant. Audit log."""
    rec = await _get_frais_custom_row(db)
    items = _current_items(rec)
    idx = next(
        (i for i, it in enumerate(items) if it.get("id") == item_id), None
    )
    if idx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poste de frais personnalisé introuvable : {item_id}",
        )
    old_item = dict(items[idx])
    updated = dict(old_item)
    fields = payload.model_dump(exclude_unset=True)
    for fld in ("label_fr", "type_montant", "financable_par_defaut"):
        if fld in fields and fields[fld] is not None:
            updated[fld] = fields[fld]
    if "valeur" in fields and fields["valeur"] is not None:
        updated["valeur"] = float(fields["valeur"])
    items[idx] = updated
    rec.value_json = items
    flag_modified(rec, "value_json")
    rec.updated_by_user_id = getattr(user, "id", None)
    await db.flush()

    await log_action(
        db,
        user=user,
        action="prospection_analysis_default.frais_custom_updated",
        entity_type="prospection_analysis_default",
        entity_id=rec.id,
        details={
            "key": _FRAIS_CUSTOM_KEY,
            "item_id": item_id,
            "old_item": old_item,
            "new_item": updated,
        },
    )
    return FraisCustomItem(**updated)


@router.delete(
    "/frais-custom/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_frais_custom(
    item_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> None:
    """Retire un poste personnalisé. Audit log."""
    rec = await _get_frais_custom_row(db)
    items = _current_items(rec)
    removed = next((it for it in items if it.get("id") == item_id), None)
    if removed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poste de frais personnalisé introuvable : {item_id}",
        )
    items = [it for it in items if it.get("id") != item_id]
    rec.value_json = items
    flag_modified(rec, "value_json")
    rec.updated_by_user_id = getattr(user, "id", None)
    await db.flush()

    await log_action(
        db,
        user=user,
        action="prospection_analysis_default.frais_custom_deleted",
        entity_type="prospection_analysis_default",
        entity_id=rec.id,
        details={"key": _FRAIS_CUSTOM_KEY, "item": removed},
    )
    return None
