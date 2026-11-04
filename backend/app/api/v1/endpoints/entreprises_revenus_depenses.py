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
from sqlalchemy import func, select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.revenus_depenses import RdScenario
from app.models.immobilier import (
    Bail,
    BailStatus,
    Evaluation,
    Hypotheque,
    HypothequeStatus,
    Immeuble,
    Logement,
    bail_non_parallele,
)
from app.services import revenus_depenses as svc
from app.services.loyer_effectif import loyer_effectif_loue
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


@router.get("/immeubles-kratos", summary="Immeubles déjà dans Kratos, prêts à être ajoutés à un scénario")
async def immeubles_kratos(db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    """Pour chaque immeuble actif : logements, chambres, loyers bruts des
    baux actifs (hors baux parallèles), gestion externe (→ sous-traitée),
    dette = solde des hypothèques actives, dernier rapport d'évaluation
    (valeur, année). Phil 2026-11-04 : « permet de sélectionner ceux que
    j'ai déjà dans Kratos »."""
    immeubles = (await db.execute(select(Immeuble).where(Immeuble.is_active.is_(True)).order_by(Immeuble.name))).scalars().all()
    ids = [i.id for i in immeubles]
    if not ids:
        return {"items": []}
    logements = (await db.execute(select(Logement).where(Logement.immeuble_id.in_(ids)))).scalars().all()
    log_ids = [l.id for l in logements]
    # Loyer effectif par logement, LA définition commune de Kratos (liste des
    # immeubles, P&L) : interne = baux actifs + loyer demandé des occupés sans
    # bail ; gestion externe = le loyer saisi sur le logement prime. Phil
    # 2026-11-04 : « ceux en gestion externe, on peut quand même voir leur
    # total mensuel et annuel » — l'import doit donner le même chiffre.
    externe_par_imm = {i.id: bool(getattr(i, "gestion_externe", False)) for i in immeubles}
    loyer_bail: Dict[int, float] = {}
    if log_ids:
        baux = (
            await db.execute(
                select(Bail.logement_id, Bail.loyer_mensuel).where(
                    Bail.logement_id.in_(log_ids), Bail.status == BailStatus.ACTIF.value, bail_non_parallele()
                )
            )
        ).all()
        for lid, loyer in baux:
            loyer_bail[lid] = loyer_bail.get(lid, 0.0) + float(loyer or 0.0)
    loyers: Dict[int, float] = {}
    for l in logements:
        m = loyer_effectif_loue(l, loyer_bail.get(l.id), gestion_externe=externe_par_imm.get(l.immeuble_id, False))
        if m is not None:
            loyers[l.immeuble_id] = loyers.get(l.immeuble_id, 0.0) + float(m)
    nb_log: Dict[int, int] = {}
    nb_ch: Dict[int, int] = {}
    for l in logements:
        nb_log[l.immeuble_id] = nb_log.get(l.immeuble_id, 0) + 1
        if getattr(l, "location_en_chambres", False):
            nb_ch[l.immeuble_id] = nb_ch.get(l.immeuble_id, 0) + int(getattr(l, "nb_chambres", 0) or 0)
    dettes: Dict[int, float] = {}
    for iid, solde, initial in (
        await db.execute(
            select(Hypotheque.immeuble_id, Hypotheque.balance_actuelle, Hypotheque.montant_initial).where(
                Hypotheque.immeuble_id.in_(ids), Hypotheque.status == HypothequeStatus.ACTIVE.value
            )
        )
    ).all():
        dettes[iid] = dettes.get(iid, 0.0) + float(solde if solde is not None else (initial or 0.0))
    evals: Dict[int, Evaluation] = {}
    for ev in (
        await db.execute(select(Evaluation).where(Evaluation.immeuble_id.in_(ids)).order_by(Evaluation.date_evaluation.desc(), Evaluation.id.desc()))
    ).scalars().all():
        cur = evals.get(ev.immeuble_id)
        # Un rapport pro ou l'évaluation de référence prime sur les autres.
        prio = (ev.kind == "appraisal") * 2 + int(bool(getattr(ev, "is_reference", False)))
        cur_prio = ((cur.kind == "appraisal") * 2 + int(bool(getattr(cur, "is_reference", False)))) if cur else -1
        if cur is None or prio > cur_prio:
            evals[ev.immeuble_id] = ev
    items = []
    for i in immeubles:
        ev = evals.get(i.id)
        notes: List[str] = []
        if not nb_log.get(i.id):
            notes.append("Aucun logement dans Kratos pour cet immeuble : logements et chambres à saisir.")
        if loyers.get(i.id, 0.0) <= 0:
            notes.append(
                "Aucun loyer dans Kratos : pas de bail actif ni de loyer saisi sur les logements"
                + (" (gestion externe : entre le loyer sur chaque logement de la fiche de l'immeuble)" if externe_par_imm.get(i.id) else "")
                + " — saisis les loyers bruts ici."
            )
        if ev is None:
            notes.append("Aucun rapport d'évaluation dans Kratos (fiche de l'immeuble → Finances → Évaluations) : valeur à saisir ici.")
        elif ev.kind != "appraisal":
            notes.append(f"Pas de rapport d'évaluateur dans Kratos : valeur reprise de l'évaluation « {ev.kind} » ({ev.date_evaluation.year if ev.date_evaluation else '?'}).")
        if not dettes.get(i.id):
            notes.append("Aucune hypothèque active dans Kratos : dette à 0 $, à vérifier.")
        items.append({
            "kratos_immeuble_id": i.id,
            "nom": i.name,
            "adresse": i.address,
            "ville": i.city,
            "nb_logements": nb_log.get(i.id) or int(i.nb_logements or 0),
            "nb_chambres": nb_ch.get(i.id, 0),
            "loyers_bruts_mensuels": round(loyers.get(i.id, 0.0), 2),
            "gestion_externe": bool(getattr(i, "gestion_externe", False)),
            "dette": round(dettes.get(i.id, 0.0), 2),
            "valeur_rapport": round(float(ev.valeur), 2) if ev else 0.0,
            "annee_rapport": ev.date_evaluation.year if ev and ev.date_evaluation else None,
            "source_rapport": (ev.kind if ev else None),
            "notes_import": notes,
        })
    return {"items": items, "total": len(items), "nb_total": int((await db.execute(select(func.count(Immeuble.id)))).scalar() or 0)}
