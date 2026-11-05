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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.revenus_depenses import RdScenario
from app.models.immobilier import (
    Bail,
    BailStatus,
    DepenseImmeuble,
    Evaluation,
    Hypotheque,
    HypothequeStatus,
    Immeuble,
    Logement,
    LogementStatus,
    bail_non_parallele,
)
from app.services import revenus_depenses as svc
from app.services.locatif_chambres import compter_chambres
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
    #: Horodatage ``updated_at`` que le client a chargé : s'il ne correspond plus
    #: (modifié ailleurs — autre onglet, mise à jour automatique), on refuse
    #: d'écraser (409) et on renvoie la version à jour. Absent = pas de contrôle.
    base_updated_at: Optional[str] = None


class CalculIn(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _meme_instant(base: Optional[str], courant: Optional[datetime]) -> bool:
    """L'horodatage chargé par le client est-il celui du scénario (à la ms) ?"""
    if not base or courant is None:
        return True
    try:
        a = datetime.fromisoformat(base.replace("Z", "+00:00"))
    except ValueError:
        return True
    b = courant
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return abs((a - b).total_seconds()) < 0.001


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


async def _bareme_schl(db) -> Dict[str, Any]:
    """Barème des dépenses normalisées SCHL de Prospection (Paramètres →
    Prospection) : LE même que l'analyse d'un lead, une seule source de vérité."""
    from app.api.v1.endpoints.lead_analyses import _load_bareme_overrides

    overrides, seuil, inocc = await _load_bareme_overrides(db)
    return {"overrides": overrides, "seuil": seuil, "taux_inoccupation": inocc}


async def _detail(db, s: RdScenario) -> Dict[str, Any]:
    data = await hydrater_kratos(db, svc.charger(s.data_json))
    bareme = await _bareme_schl(db)
    return {**_resume_scenario(s), "data": data, "resultats": svc.calculer(data, bareme), "referentiel": svc.referentiel(bareme)}


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
        resume_json=json.dumps(svc.resume(svc.calculer(data, await _bareme_schl(db))), ensure_ascii=False),
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
        resume_json=json.dumps(svc.resume(svc.calculer(data, await _bareme_schl(db))), ensure_ascii=False),
        is_default=False, created_by_email=getattr(user, "email", None),
    )
    db.add(s)
    await db.flush()
    await log_action(db, user=user, action="revenus_depenses.scenario_cree", entity_type="rd_scenario", entity_id=s.id,
                     details={"nom": s.nom, "source_id": payload.source_id})
    await db.commit()
    await db.refresh(s)
    return await _detail(db, s)


@router.get("/scenarios/{scenario_id}", summary="Hypothèses, résultats et référentiel d'un scénario")
async def lire_scenario(scenario_id: int, db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    return await _detail(db, await _scenario_ou_404(db, scenario_id))


@router.put("/scenarios/{scenario_id}", summary="Enregistrer les hypothèses et recalculer")
async def enregistrer_scenario(scenario_id: int, payload: ScenarioUpdate, db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    s = await _scenario_ou_404(db, scenario_id)
    if not _meme_instant(payload.base_updated_at, s.updated_at):
        # Phil 2026-11-05 : sa page restée ouverte avait réécrit les anciennes valeurs
        # par-dessus une mise à jour. On n'écrase plus : version à jour renvoyée.
        return JSONResponse(status_code=409, content=jsonable_encoder({
            "conflit": True,
            "message": "Le scénario a été modifié ailleurs (autre onglet ou mise à jour automatique) : la version à jour a été rechargée, tes dernières modifications sont à refaire.",
            **(await _detail(db, s)),
        }))
    if payload.nom is not None:
        nom = payload.nom.strip()
        if not nom:
            raise HTTPException(status_code=422, detail="Le nom du scénario ne peut pas être vide.")
        s.nom = nom[:120]
    if payload.data is not None:
        data = await hydrater_kratos(db, svc.normaliser(payload.data))
        s.data_json = json.dumps(data, ensure_ascii=False)
        s.resume_json = json.dumps(svc.resume(svc.calculer(data, await _bareme_schl(db))), ensure_ascii=False)
    s.updated_at = _now()
    await log_action(db, user=user, action="revenus_depenses.scenario_modifie", entity_type="rd_scenario", entity_id=s.id,
                     details={"nom": s.nom, "resume": json.loads(s.resume_json) if s.resume_json else None})
    await db.commit()
    await db.refresh(s)
    return await _detail(db, s)


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
async def calculer(payload: CalculIn, db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    data = await hydrater_kratos(db, svc.normaliser(payload.data))
    return {"data": data, "resultats": svc.calculer(data, await _bareme_schl(db))}


@router.get("/immeubles-kratos", summary="Immeubles déjà dans Kratos, prêts à être ajoutés à un scénario")
async def immeubles_kratos(db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    """Pour chaque immeuble actif : logements, chambres, loyers bruts des
    baux actifs (hors baux parallèles), gestion externe (→ sous-traitée),
    dette = solde des hypothèques actives, dernier rapport d'évaluation
    (valeur, année). Phil 2026-11-04 : « permet de sélectionner ceux que
    j'ai déjà dans Kratos »."""
    items = await lire_immeubles_kratos(db)
    return {"items": items, "total": len(items), "nb_total": int((await db.execute(select(func.count(Immeuble.id)))).scalar() or 0)}


#: Champs d'un immeuble du scénario qui viennent de Kratos (repris à jour tant que « suivre_kratos »).
CHAMPS_KRATOS = ("nb_logements", "nb_chambres", "loyers_bruts_mensuels", "gestion_interne", "valeur_rapport", "annee_rapport", "dette",
                 "taxes_municipales", "taxes_scolaires", "assurances", "energie", "autres_depenses")
_log = logging.getLogger(__name__)


async def hydrater_kratos(db, data: Dict[str, Any]) -> Dict[str, Any]:
    """Phil 2026-11-04 : « je t'ai dit de prendre toutes les informations qui
    étaient disponibles ». Les immeubles importés qui « suivent Kratos »
    reprennent, à chaque lecture / enregistrement / calcul, les valeurs à jour de
    Kratos (loyers, portes, chambres, rapport, dette, dépenses réelles) et leurs
    alertes, moins celles que l'utilisateur a fermées (``notes_ignorees``)."""
    cibles = [i for i in data.get("immeubles", []) if i.get("kratos_immeuble_id") and i.get("suivre_kratos")]
    if not cibles:
        return data
    try:
        items = {it["kratos_immeuble_id"]: it for it in await lire_immeubles_kratos(db, [int(i["kratos_immeuble_id"]) for i in cibles])}
    except Exception as exc:  # noqa: BLE001
        _log.warning("Hydratation Kratos impossible : %s", exc)
        return data
    for i in cibles:
        it = items.get(i["kratos_immeuble_id"])
        if not it:
            i["notes_import"] = ["Immeuble introuvable ou inactif dans Kratos : valeurs figées."]
            continue
        for k in CHAMPS_KRATOS:
            i[k] = (not it["gestion_externe"]) if k == "gestion_interne" else it[k]
        ignorees = set(i.get("notes_ignorees") or [])
        i["notes_import"] = [n for n in it["notes_import"] if n not in ignorees]
        if (i.get("taux_cap_pct") or 0) > 0:
            i["notes_import"] = [n for n in i["notes_import"] if "Taux de cap" not in n]
    return data


async def lire_immeubles_kratos(db, ids_filtre: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """Immeubles actifs de Kratos tels que la simulation les reprend (voir la route
    ``/immeubles-kratos``) ; ``ids_filtre`` limite aux immeubles d'un scénario."""
    q = select(Immeuble).where(Immeuble.is_active.is_(True))
    if ids_filtre:
        q = q.where(Immeuble.id.in_(ids_filtre))
    immeubles = (await db.execute(q.order_by(Immeuble.name))).scalars().all()
    ids = [i.id for i in immeubles]
    if not ids:
        return []
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
    # Portes et chambres : mêmes règles que la liste des immeubles (hors
    # location exclus, chambres par ``compter_chambres``).
    nb_log: Dict[int, int] = {}
    for l in logements:
        if l.status == LogementStatus.HORS_LOC.value:
            continue
        nb_log[l.immeuble_id] = nb_log.get(l.immeuble_id, 0) + 1
    nb_ch: Dict[int, int] = {iid: int(c.get("tot", 0)) for iid, c in (await compter_chambres(db, immeubles)).items()}
    # Logements loués en chambres SANS nombre de chambres dans Kratos (Phil :
    # « il semble pas reconnaître les chambres comme sur Saint-Clément ») :
    # Kratos n'en compte alors que les baux actifs — à signaler.
    sans_chambres: Dict[int, int] = {}
    for l in logements:
        if getattr(l, "location_en_chambres", False) and l.status != LogementStatus.HORS_LOC.value and not int(getattr(l, "nb_chambres", 0) or 0):
            sans_chambres[l.immeuble_id] = sans_chambres.get(l.immeuble_id, 0) + 1
    # Dépenses RÉELLES annuelles (fiche de l'immeuble → Dépenses), coût courant
    # comme le P&L : % des loyers → $, taxable → × 1,14975, mensuel × 12,
    # annuel × 1, ponctuel des 12 derniers mois. Taxes, assurances, énergie et
    # autres alimentent les revenus nets SCHL ; entretien, conciergerie et
    # gestion sont NORMALISÉS par le barème (pas repris : double compte).
    _CAT = {"taxes_municipales": "taxes_municipales", "taxes_scolaires": "taxes_scolaires", "assurances": "assurances",
            "energie": "energie", "deneigement": "autres_depenses", "autre": "autres_depenses"}
    depenses: Dict[int, Dict[str, float]] = {}
    depuis = date.today() - timedelta(days=365)
    for dp in (await db.execute(select(DepenseImmeuble).where(DepenseImmeuble.immeuble_id.in_(ids)))).scalars().all():
        cat = _CAT.get(dp.categorie or "autre")
        if cat is None:
            continue
        m = float(dp.montant or 0.0)
        if dp.is_pourcentage:
            m = loyers.get(dp.immeuble_id, 0.0) * m / 100.0
        if dp.taxable:
            m *= 1.14975
        if dp.frequence == "mensuel":
            annuel = m * 12.0
        elif dp.frequence == "annuel":
            annuel = m
        elif dp.date_depense and dp.date_depense >= depuis:
            annuel = m
        else:
            continue
        bucket = depenses.setdefault(dp.immeuble_id, {})
        bucket[cat] = bucket.get(cat, 0.0) + annuel
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
        if sans_chambres.get(i.id):
            notes.append(f"{sans_chambres[i.id]} logement(s) loué(s) en chambres sans nombre de chambres dans Kratos (fiche de l'immeuble → logements) : "
                         f"Kratos ne compte que les baux actifs ({nb_ch.get(i.id, 0)} chambre(s)) — ajuste les chambres ici ou dans la fiche.")
        if loyers.get(i.id, 0.0) <= 0:
            notes.append(
                "Aucun loyer dans Kratos : pas de bail actif ni de loyer saisi sur les logements"
                + (" (gestion externe : entre le loyer sur chaque logement de la fiche de l'immeuble)" if externe_par_imm.get(i.id) else "")
                + " — saisis les loyers bruts ici."
            )
        dep = depenses.get(i.id, {})
        manquantes = [lbl for k, lbl in (("taxes_municipales", "taxes municipales"), ("taxes_scolaires", "taxes scolaires"),
                                         ("assurances", "assurances"), ("energie", "énergie")) if not dep.get(k)]
        if manquantes and loyers.get(i.id, 0.0) > 0:
            notes.append("Dépenses réelles absentes dans Kratos (fiche de l'immeuble → Dépenses) : " + ", ".join(manquantes)
                         + " — à saisir ici pour des revenus nets SCHL justes.")
        if ev is None:
            notes.append("Aucun rapport d'évaluation dans Kratos (fiche de l'immeuble → Finances → Évaluations) : "
                         "valeur à saisir ici, ou taux de cap pour la calculer des revenus nets SCHL.")
        elif ev.kind != "appraisal":
            notes.append(f"Pas de rapport d'évaluateur dans Kratos : valeur reprise de l'évaluation « {ev.kind} » ({ev.date_evaluation.year if ev.date_evaluation else '?'}).")
        if ev is not None:
            notes.append("Taux de cap du rapport à saisir ici (Kratos ne le conserve pas) : la valeur suivra alors les revenus nets SCHL ÷ taux de cap.")
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
            "taxes_municipales": round(dep.get("taxes_municipales", 0.0), 2),
            "taxes_scolaires": round(dep.get("taxes_scolaires", 0.0), 2),
            "assurances": round(dep.get("assurances", 0.0), 2),
            "energie": round(dep.get("energie", 0.0), 2),
            "autres_depenses": round(dep.get("autres_depenses", 0.0), 2),
            "notes_import": notes,
        })
    return items
