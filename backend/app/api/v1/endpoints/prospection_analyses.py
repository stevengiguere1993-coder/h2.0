"""Endpoints du calculateur d'analyse financière multi-logements.

CRUD simple : liste, get, create, update, delete. Le calcul lui-même
est fait côté frontend (TypeScript pur, testé). Le backend ne fait
que persister `inputs_json` + `results_json`.

Filtrage par `lead_id` pour récupérer les analyses d'un lead donné
depuis sa fiche.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DBSession
from app.models.prospection_analyse import ProspectionAnalyse

router = APIRouter(prefix="/prospection/analyses", tags=["prospection-analyses"])


# ------------------------------ Schemas ------------------------------


class AnalyseRead(BaseModel):
    """Représentation lisible d'une analyse (inputs + résultats
    désérialisés depuis le JSON stocké en DB)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_id: Optional[int]
    name: str
    inputs: dict[str, Any]
    results: dict[str, Any]
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class AnalyseSummary(BaseModel):
    """Vue compacte pour la liste : on n'envoie pas les JSON complets,
    juste les KPIs principaux extraits des résultats."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_id: Optional[int]
    name: str
    created_at: datetime
    updated_at: datetime
    # KPIs extraits de results_json pour affichage rapide
    prix_achat: Optional[float] = None
    nombre_logements: Optional[int] = None
    achat_mise_de_fonds: Optional[float] = None
    schl_gain_actionnaires: Optional[float] = None
    aph50_gain_actionnaires: Optional[float] = None


class AnalyseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    lead_id: Optional[int] = None
    inputs: dict[str, Any]
    results: dict[str, Any]


class AnalyseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    lead_id: Optional[int] = None
    inputs: Optional[dict[str, Any]] = None
    results: Optional[dict[str, Any]] = None


# ------------------------------ Helpers ------------------------------


def _serialize(a: ProspectionAnalyse) -> AnalyseRead:
    return AnalyseRead(
        id=a.id,
        lead_id=a.lead_id,
        name=a.name,
        inputs=json.loads(a.inputs_json) if a.inputs_json else {},
        results=json.loads(a.results_json) if a.results_json else {},
        created_by_user_id=a.created_by_user_id,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def _summarize(a: ProspectionAnalyse) -> AnalyseSummary:
    """Extrait les KPIs sans désérialiser tout l'objet — coupe le
    payload de la liste de ~80% sur des analyses chargées."""
    inputs: dict = {}
    results: dict = {}
    try:
        inputs = json.loads(a.inputs_json) if a.inputs_json else {}
    except Exception:
        inputs = {}
    try:
        results = json.loads(a.results_json) if a.results_json else {}
    except Exception:
        results = {}

    achat = results.get("achat") or {}
    schl = results.get("schl") or {}
    aph50 = results.get("aph50") or {}

    return AnalyseSummary(
        id=a.id,
        lead_id=a.lead_id,
        name=a.name,
        created_at=a.created_at,
        updated_at=a.updated_at,
        prix_achat=inputs.get("prixAchat"),
        nombre_logements=inputs.get("nombreLogements"),
        achat_mise_de_fonds=achat.get("miseDeFonds"),
        schl_gain_actionnaires=schl.get("gainActionnaires"),
        aph50_gain_actionnaires=aph50.get("gainActionnaires"),
    )


# ------------------------------ Endpoints ------------------------------


@router.get("", response_model=List[AnalyseSummary])
async def list_analyses(
    db: DBSession,
    _: CurrentUser,
    lead_id: Optional[int] = Query(default=None),
    limit: int = Query(default=200, le=500),
) -> List[AnalyseSummary]:
    stmt = select(ProspectionAnalyse)
    if lead_id is not None:
        stmt = stmt.where(ProspectionAnalyse.lead_id == lead_id)
    stmt = stmt.order_by(ProspectionAnalyse.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_summarize(a) for a in rows]


@router.get("/{analyse_id}", response_model=AnalyseRead)
async def get_analyse(
    analyse_id: int,
    db: DBSession,
    _: CurrentUser,
) -> AnalyseRead:
    a = await db.get(ProspectionAnalyse, analyse_id)
    if a is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analyse introuvable.",
        )
    return _serialize(a)


@router.post("", response_model=AnalyseRead, status_code=status.HTTP_201_CREATED)
async def create_analyse(
    payload: AnalyseCreate,
    db: DBSession,
    user: CurrentUser,
) -> AnalyseRead:
    a = ProspectionAnalyse(
        lead_id=payload.lead_id,
        name=payload.name,
        inputs_json=json.dumps(payload.inputs, ensure_ascii=False),
        results_json=json.dumps(payload.results, ensure_ascii=False),
        created_by_user_id=user.id,
    )
    db.add(a)
    await db.flush()
    await db.refresh(a)
    return _serialize(a)


@router.patch("/{analyse_id}", response_model=AnalyseRead)
async def update_analyse(
    analyse_id: int,
    payload: AnalyseUpdate,
    db: DBSession,
    _: CurrentUser,
) -> AnalyseRead:
    a = await db.get(ProspectionAnalyse, analyse_id)
    if a is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analyse introuvable.",
        )
    if payload.name is not None:
        a.name = payload.name
    if payload.lead_id is not None:
        a.lead_id = payload.lead_id
    if payload.inputs is not None:
        a.inputs_json = json.dumps(payload.inputs, ensure_ascii=False)
    if payload.results is not None:
        a.results_json = json.dumps(payload.results, ensure_ascii=False)
    await db.flush()
    await db.refresh(a)
    return _serialize(a)


@router.delete("/{analyse_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analyse(
    analyse_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    res = await db.execute(
        delete(ProspectionAnalyse).where(ProspectionAnalyse.id == analyse_id)
    )
    if res.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analyse introuvable.",
        )
