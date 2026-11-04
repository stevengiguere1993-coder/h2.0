"""Gestion d'entreprise → Revenus et dépenses (2026-11-04) — mode SIMULATION.

Réservé aux administrateurs et propriétaires (Phil : « seulement les
admins »). Scénarios d'hypothèses enregistrés ; le calcul est fait par
``services/revenus_depenses.calculer`` (source unique, réutilisée plus tard
par le mode réel branché sur Kratos et QuickBooks).

    GET    /entreprises/revenus-depenses/scenarios            → liste (crée le scénario par défaut au besoin)
    POST   /entreprises/revenus-depenses/scenarios            → nouveau (vide ou copie de ``source_id``)
    GET    /entreprises/revenus-depenses/scenarios/{id}       → hypothèses + résultats + référentiel
    PUT    /entreprises/revenus-depenses/scenarios/{id}       → enregistre (nom, hypothèses) et recalcule
    DELETE /entreprises/revenus-depenses/scenarios/{id}
    POST   /entreprises/revenus-depenses/calculer             → résultats sans enregistrer
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.revenus_depenses import RdScenario
from app.services import revenus_depenses as svc
from app.services.audit import log_action

log = logging.getLogger(__name__)

router = APIRouter(prefix="/entreprises/revenus-depenses", tags=["entreprises-revenus-depenses"])


class ScenarioIn(BaseModel):
    nom: Optional[str] = Field(default=None, max_length=120)
    #: Copier les hypothèses d'un scénario existant.
    source_id: Optional[int] = None


class ScenarioUpdate(BaseModel):
    nom: Optional[str] = Field(default=None, max_length=120)
    data: Optional[Dict[str, Any]] = None


class CalculIn(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _resume_scenario(s: RdScenario) -> Dict[str, Any]:
    try:
        res = json.loads(s.resume_json) if s.resume_json else {}
    except Exception:  # noqa: BLE001
        res = {}
    return {
        "id": s.id, "nom": s.nom, "is_default": bool(s.is_default), "resume": res,
        "created_by_email": s.created_by_email,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _detail(s: RdScenario) -> Dict[str, Any]:
    data = svc.charger(s.data_json)
    return {**_resume_scenario(s), "data": data, "resultats": svc.calculer(data), "referentiel": svc.referentiel()}


async def _scenario_ou_404(db, scenario_id: int) -> RdScenario:
    s = await db.get(RdScenario, scenario_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Scénario introuvable.")
    return s


async def _assurer_defaut(db, user) -> List[RdScenario]:
    rows = (await db.execute(select(RdScenario).order_by(RdScenario.is_default.desc(), RdScenario.updated_at.desc()))).scalars().all()
    if rows:
        return list(rows)
    data = svc.scenario_defaut()
    s = RdScenario(
        nom="Scénario de base", data_json=json.dumps(data, ensure_ascii=False),
        resume_json=json.dumps(svc.resume(svc.calculer(data)), ensure_ascii=False),
        is_default=True, created_by_email=getattr(user, "email", None),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return [s]


@router.get("/scenarios", summary="Scénarios de simulation (revenus et dépenses de la société de gestion)")
async def lister_scenarios(db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    rows = await _assurer_defaut(db, user)
    return {"items": [_resume_scenario(s) for s in rows], "total": len(rows)}


@router.post("/scenarios", summary="Nouveau scénario (vide ou copie)", status_code=201)
async def creer_scenario(payload: ScenarioIn, db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    if payload.source_id is not None:
        src = await _scenario_ou_404(db, payload.source_id)
        data = svc.charger(src.data_json)
        nom = (payload.nom or "").strip() or f"{src.nom} (copie)"
    else:
        data = svc.scenario_defaut()
        nom = (payload.nom or "").strip() or "Nouveau scénario"
    s = RdScenario(
        nom=nom[:120], data_json=json.dumps(data, ensure_ascii=False),
        resume_json=json.dumps(svc.resume(svc.calculer(data)), ensure_ascii=False),
        is_default=False, created_by_email=getattr(user, "email", None),
    )
    db.add(s)
    await db.flush()
    await log_action(db, user=user, action="revenus_depenses.scenario_cree", entity_type="rd_scenario", entity_id=s.id,
                     details={"nom": s.nom, "source_id": payload.source_id})
    await db.commit()
    await db.refresh(s)
    return _detail(s)


@router.get("/scenarios/{scenario_id}", summary="Hypothèses, résultats et référentiel d'un scénario")
async def lire_scenario(scenario_id: int, db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    return _detail(await _scenario_ou_404(db, scenario_id))


@router.put("/scenarios/{scenario_id}", summary="Enregistrer les hypothèses et recalculer")
async def enregistrer_scenario(scenario_id: int, payload: ScenarioUpdate, db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    s = await _scenario_ou_404(db, scenario_id)
    if payload.nom is not None:
        nom = payload.nom.strip()
        if not nom:
            raise HTTPException(status_code=422, detail="Le nom du scénario ne peut pas être vide.")
        s.nom = nom[:120]
    if payload.data is not None:
        data = svc.normaliser(payload.data)
        s.data_json = json.dumps(data, ensure_ascii=False)
        s.resume_json = json.dumps(svc.resume(svc.calculer(data)), ensure_ascii=False)
    s.updated_at = _now()
    await log_action(db, user=user, action="revenus_depenses.scenario_modifie", entity_type="rd_scenario", entity_id=s.id,
                     details={"nom": s.nom, "resume": json.loads(s.resume_json) if s.resume_json else None})
    await db.commit()
    await db.refresh(s)
    return _detail(s)


@router.delete("/scenarios/{scenario_id}", summary="Supprimer un scénario", status_code=204)
async def supprimer_scenario(scenario_id: int, db: DBSession, user: RequireAdminOrOwner) -> None:
    s = await _scenario_ou_404(db, scenario_id)
    etait_defaut = bool(s.is_default)
    nom = s.nom
    await db.delete(s)
    await db.flush()
    if etait_defaut:
        autre = (await db.execute(select(RdScenario).order_by(RdScenario.updated_at.desc()))).scalars().first()
        if autre is not None:
            autre.is_default = True
    await log_action(db, user=user, action="revenus_depenses.scenario_supprime", entity_type="rd_scenario", entity_id=scenario_id,
                     details={"nom": nom})
    await db.commit()


@router.post("/calculer", summary="Calculer sans enregistrer")
async def calculer(payload: CalculIn, user: RequireAdminOrOwner) -> Dict[str, Any]:
    data = svc.normaliser(payload.data)
    return {"data": data, "resultats": svc.calculer(data)}
