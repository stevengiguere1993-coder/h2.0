"""Endpoints du QG Gestion d'entreprises — extensions Phase 5.

Couvre les 3 chantiers :
- Templates de tâches récurrentes (CRUD + run)
- Snapshots financiers mensuels (CRUD + timeseries + summary heatmap)
- Value plan + milestones (CRUD)

Restreint au volet `entreprises` via _require_volet.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import CurrentUser, DBSession
from app.models.entreprise import Entreprise
from app.models.entreprise_finance import (
    EntrepriseFinanceSnapshot,
    EntrepriseValueMilestone,
    EntrepriseValuePlan,
)
from app.models.entreprise_recurrence import TacheTemplate
from app.schemas.entreprise_extras import (
    ComplianceCatalogItem,
    ComplianceImportRequest,
    ComplianceImportResult,
    EntrepriseFinanceSummary,
    FinanceSnapshotCreate,
    FinanceSnapshotRead,
    FinanceSnapshotUpdate,
    FinanceTimeseries,
    MaterializeResult,
    TacheTemplateBulkCreate,
    TacheTemplateBulkResult,
    TacheTemplateCreate,
    TacheTemplateGlobalRead,
    TacheTemplateRead,
    TacheTemplateUpdate,
    ValueMilestoneCreate,
    ValueMilestoneRead,
    ValueMilestoneUpdate,
    ValuePlanCreate,
    ValuePlanDriverItem,
    ValuePlanRead,
    ValuePlanUpdate,
)
from app.services.qg_compliance_catalog import (
    COMPLIANCE_TEMPLATES,
    first_day_next_month,
    get_by_codes,
)
from app.services.qg_recurrence import materialize_due_templates


log = logging.getLogger(__name__)
router = APIRouter(prefix="/entreprises", tags=["entreprises"])


# ── Helpers ────────────────────────────────────────────────────────────


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "entreprises" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion d'entreprises » non autorisé.",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _drivers_to_json(drivers: List[ValuePlanDriverItem] | None) -> str | None:
    if not drivers:
        return None
    return json.dumps([d.model_dump() for d in drivers])


def _drivers_from_json(s: str | None) -> List[ValuePlanDriverItem]:
    if not s:
        return []
    try:
        raw = json.loads(s)
        if not isinstance(raw, list):
            return []
        out: List[ValuePlanDriverItem] = []
        for item in raw:
            if isinstance(item, dict):
                try:
                    out.append(ValuePlanDriverItem(**item))
                except Exception:  # noqa: BLE001
                    continue
        return out
    except Exception:  # noqa: BLE001
        return []


def _plan_to_read(p: EntrepriseValuePlan) -> ValuePlanRead:
    out = ValuePlanRead.model_validate(p, from_attributes=True)
    out.drivers = _drivers_from_json(p.drivers_json)
    return out


# ── Tâches récurrentes (templates) ─────────────────────────────────────


@router.get(
    "/{entreprise_id}/tache-templates",
    response_model=List[TacheTemplateRead],
)
async def list_templates(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> List[TacheTemplateRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(TacheTemplate)
            .where(TacheTemplate.entreprise_id == entreprise_id)
            .order_by(TacheTemplate.next_due.asc())
        )
    ).scalars().all()
    return [
        TacheTemplateRead.model_validate(_serialize_template_for_read(r))
        for r in rows
    ]


@router.get(
    "/tache-templates/all",
    response_model=List[TacheTemplateGlobalRead],
    summary="Liste cross-entreprise de tous les templates récurrents.",
)
async def list_templates_all(
    db: DBSession, user: CurrentUser
) -> List[TacheTemplateGlobalRead]:
    """Page globale `/taches/recurrentes` — joint le nom de
    l'entreprise pour éviter N+1 côté front. Tri par next_due
    croissant (les modèles dus en premier)."""
    _require_volet(user)
    stmt = (
        select(TacheTemplate, Entreprise.name)
        .join(Entreprise, Entreprise.id == TacheTemplate.entreprise_id)
        .order_by(TacheTemplate.next_due.asc())
    )
    out: List[TacheTemplateGlobalRead] = []
    for tpl, ent_name in (await db.execute(stmt)).all():
        data = _serialize_template_for_read(tpl)
        data["entreprise_name"] = ent_name
        out.append(TacheTemplateGlobalRead.model_validate(data))
    return out


def _serialize_template_for_read(obj: TacheTemplate) -> dict:
    """Convertit un row TacheTemplate en dict prêt pour TacheTemplateRead.

    `immeuble_ids` est exposé comme List[int] côté front mais stocké
    en TEXT JSON côté DB (`immeuble_ids_json`). On désérialise ici."""
    raw = getattr(obj, "immeuble_ids_json", None)
    imm_ids: List[int] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                imm_ids = [int(x) for x in parsed if isinstance(x, int)]
        except Exception:  # noqa: BLE001
            imm_ids = []
    return {
        "id": obj.id,
        "entreprise_id": obj.entreprise_id,
        "title": obj.title,
        "description": obj.description,
        "departement": obj.departement,
        "impact": obj.impact,
        "confidence": obj.confidence,
        "effort": obj.effort,
        "assignee_user_id": obj.assignee_user_id,
        "every_n": obj.every_n,
        "unit": obj.unit,
        "lead_days": obj.lead_days,
        "next_due": obj.next_due,
        "default_status": getattr(obj, "default_status", "todo") or "todo",
        "immeuble_ids": imm_ids,
        "is_active": obj.is_active,
        "nb_materialized": obj.nb_materialized,
        "last_materialized_at": obj.last_materialized_at,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


def _build_template_kwargs(payload_dump: dict) -> dict:
    """Convertit le dump Pydantic d'un TemplateCreate/Bulk en kwargs
    prêts pour TacheTemplate(...). `immeuble_ids` (List[int]) →
    `immeuble_ids_json` (str JSON ou None)."""
    out = dict(payload_dump)
    imm_ids = out.pop("immeuble_ids", None) or []
    out["immeuble_ids_json"] = (
        json.dumps([int(x) for x in imm_ids]) if imm_ids else None
    )
    return out


@router.post(
    "/tache-templates",
    response_model=TacheTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    payload: TacheTemplateCreate, db: DBSession, user: CurrentUser
) -> TacheTemplateRead:
    _require_volet(user)
    ent = await db.get(Entreprise, payload.entreprise_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entreprise introuvable.")
    obj = TacheTemplate(**_build_template_kwargs(payload.model_dump()))
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return TacheTemplateRead.model_validate(_serialize_template_for_read(obj))


@router.post(
    "/tache-templates/bulk",
    response_model=TacheTemplateBulkResult,
    status_code=status.HTTP_201_CREATED,
    summary="Crée un même modèle pour plusieurs entreprises (multi-select).",
)
async def create_template_bulk(
    payload: TacheTemplateBulkCreate, db: DBSession, user: CurrentUser
) -> TacheTemplateBulkResult:
    """Crée un modèle identique pour chaque entreprise demandée.
    Idempotent par (entreprise_id, title) : si un template existe
    déjà avec le même titre dans une entreprise, on l'ignore et on
    le note dans `skipped_entreprise_ids`."""
    _require_volet(user)
    base = payload.model_dump()
    entreprise_ids = base.pop("entreprise_ids")

    # Vérifie que toutes les entreprises existent en un seul round-trip.
    existing_ids = set(
        (
            await db.execute(
                select(Entreprise.id).where(Entreprise.id.in_(entreprise_ids))
            )
        ).scalars().all()
    )
    missing = [eid for eid in entreprise_ids if eid not in existing_ids]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Entreprise(s) introuvable(s) : {missing}",
        )

    # Pour idempotence : récupère les titres déjà présents.
    existing_titles = (
        await db.execute(
            select(
                TacheTemplate.entreprise_id, TacheTemplate.title
            ).where(TacheTemplate.entreprise_id.in_(entreprise_ids))
        )
    ).all()
    seen: set[tuple[int, str]] = {(eid, t) for eid, t in existing_titles}

    created = 0
    skipped: List[int] = []
    for eid in entreprise_ids:
        key = (eid, base["title"])
        if key in seen:
            skipped.append(eid)
            continue
        kwargs = _build_template_kwargs({**base, "entreprise_id": eid})
        obj = TacheTemplate(**kwargs)
        obj.created_at = _now()
        obj.updated_at = _now()
        db.add(obj)
        created += 1

    if created:
        await db.commit()
    return TacheTemplateBulkResult(
        created=created, skipped_entreprise_ids=skipped
    )


@router.patch(
    "/tache-templates/{template_id}",
    response_model=TacheTemplateRead,
)
async def update_template(
    template_id: int,
    payload: TacheTemplateUpdate,
    db: DBSession,
    user: CurrentUser,
) -> TacheTemplateRead:
    _require_volet(user)
    obj = await db.get(TacheTemplate, template_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Template introuvable.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        if k == "immeuble_ids":
            obj.immeuble_ids_json = (
                json.dumps([int(x) for x in (v or [])]) if v else None
            )
            continue
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return TacheTemplateRead.model_validate(_serialize_template_for_read(obj))


@router.delete(
    "/tache-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_template(
    template_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(TacheTemplate, template_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Template introuvable.")
    await db.delete(obj)
    await db.commit()


@router.get(
    "/tache-templates/compliance-catalog",
    response_model=List[ComplianceCatalogItem],
)
async def list_compliance_catalog(
    user: CurrentUser,
) -> List[ComplianceCatalogItem]:
    """Liste les templates compliance Québec disponibles à l'import."""
    _require_volet(user)
    return [
        ComplianceCatalogItem(**t.__dict__) for t in COMPLIANCE_TEMPLATES
    ]


@router.post(
    "/{entreprise_id}/tache-templates/import-compliance",
    response_model=ComplianceImportResult,
)
async def import_compliance_templates(
    entreprise_id: int,
    payload: ComplianceImportRequest,
    db: DBSession,
    user: CurrentUser,
) -> ComplianceImportResult:
    """Crée d'un coup les templates correspondant aux codes catalogue.

    Idempotent par (entreprise_id, code catalogue) : si un template avec
    le même titre existe déjà sur cette entreprise, on l'ignore et on
    renvoie son code dans `skipped`.
    """
    _require_volet(user)
    ent = await db.get(Entreprise, entreprise_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entreprise introuvable.")

    selected = get_by_codes(payload.codes)
    if not selected:
        raise HTTPException(
            status_code=400,
            detail="Aucun code catalogue valide.",
        )

    existing_titles = set(
        (
            await db.execute(
                select(TacheTemplate.title).where(
                    TacheTemplate.entreprise_id == entreprise_id
                )
            )
        ).scalars().all()
    )

    next_due = payload.next_due or first_day_next_month(date.today())
    now = _now()
    created: List[TacheTemplate] = []
    skipped: List[str] = []

    for cat in selected:
        if cat.label in existing_titles:
            skipped.append(cat.code)
            continue
        obj = TacheTemplate(
            entreprise_id=entreprise_id,
            title=cat.label,
            description=cat.description,
            departement=cat.departement,
            impact=cat.impact,
            confidence=cat.confidence,
            effort=cat.effort,
            every_n=cat.every_n,
            unit=cat.unit,
            lead_days=cat.lead_days,
            next_due=next_due,
            is_active=True,
        )
        obj.created_at = now
        obj.updated_at = now
        db.add(obj)
        created.append(obj)

    if created:
        await db.commit()
        for c in created:
            await db.refresh(c)

    return ComplianceImportResult(
        created=len(created),
        skipped=skipped,
        templates=[TacheTemplateRead.model_validate(c) for c in created],
    )


@router.post(
    "/tache-templates/run-materialize",
    response_model=MaterializeResult,
)
async def run_materialize(
    db: DBSession, user: CurrentUser
) -> MaterializeResult:
    """Déclenche manuellement le cron de matérialisation.

    Aussi appelé automatiquement par le cron job daily.
    """
    _require_volet(user)
    res = await materialize_due_templates(db)
    return MaterializeResult(**res)


# ── Finance snapshots ──────────────────────────────────────────────────


def _normalize_year_month(d: date) -> date:
    """Force au 1er du mois."""
    return d.replace(day=1)


@router.get(
    "/{entreprise_id}/finance/snapshots",
    response_model=List[FinanceSnapshotRead],
)
async def list_finance_snapshots(
    entreprise_id: int,
    db: DBSession,
    user: CurrentUser,
    months: int = 12,
) -> List[FinanceSnapshotRead]:
    _require_volet(user)
    cutoff = _normalize_year_month(date.today()) - timedelta(days=months * 31)
    rows = (
        await db.execute(
            select(EntrepriseFinanceSnapshot)
            .where(
                and_(
                    EntrepriseFinanceSnapshot.entreprise_id == entreprise_id,
                    EntrepriseFinanceSnapshot.year_month >= cutoff,
                )
            )
            .order_by(EntrepriseFinanceSnapshot.year_month.asc())
        )
    ).scalars().all()
    return [FinanceSnapshotRead.model_validate(r) for r in rows]


@router.put(
    "/{entreprise_id}/finance/snapshots",
    response_model=FinanceSnapshotRead,
)
async def upsert_finance_snapshot(
    entreprise_id: int,
    payload: FinanceSnapshotCreate,
    db: DBSession,
    user: CurrentUser,
) -> FinanceSnapshotRead:
    """Upsert sur (entreprise_id, year_month). Idempotent."""
    _require_volet(user)
    if payload.entreprise_id != entreprise_id:
        raise HTTPException(
            status_code=400,
            detail="entreprise_id du body ≠ path.",
        )
    ent = await db.get(Entreprise, entreprise_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entreprise introuvable.")

    ym = _normalize_year_month(payload.year_month)
    data = payload.model_dump()
    data["year_month"] = ym
    data["created_at"] = _now()
    data["updated_at"] = _now()

    # Dialect-aware upsert : on tente Postgres ON CONFLICT, fallback select+update.
    try:
        stmt = (
            pg_insert(EntrepriseFinanceSnapshot)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["entreprise_id", "year_month"],
                set_={
                    "revenu": data.get("revenu"),
                    "depenses": data.get("depenses"),
                    "ebitda": data.get("ebitda"),
                    "resultat_net": data.get("resultat_net"),
                    "tresorerie": data.get("tresorerie"),
                    "dette_long_terme": data.get("dette_long_terme"),
                    "valorisation_estimee": data.get("valorisation_estimee"),
                    "source": data.get("source"),
                    "notes": data.get("notes"),
                    "updated_at": data["updated_at"],
                },
            )
            .returning(EntrepriseFinanceSnapshot)
        )
        row = (await db.execute(stmt)).scalar_one()
        await db.commit()
        return FinanceSnapshotRead.model_validate(row)
    except Exception:  # noqa: BLE001
        await db.rollback()
        # Fallback générique
        existing = (
            await db.execute(
                select(EntrepriseFinanceSnapshot).where(
                    and_(
                        EntrepriseFinanceSnapshot.entreprise_id == entreprise_id,
                        EntrepriseFinanceSnapshot.year_month == ym,
                    )
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            obj = EntrepriseFinanceSnapshot(**data)
            db.add(obj)
            await db.commit()
            await db.refresh(obj)
            return FinanceSnapshotRead.model_validate(obj)
        for k, v in payload.model_dump(exclude={"entreprise_id", "year_month"}).items():
            setattr(existing, k, v)
        existing.updated_at = _now()
        await db.commit()
        await db.refresh(existing)
        return FinanceSnapshotRead.model_validate(existing)


@router.patch(
    "/finance/snapshots/{snapshot_id}",
    response_model=FinanceSnapshotRead,
)
async def update_finance_snapshot(
    snapshot_id: int,
    payload: FinanceSnapshotUpdate,
    db: DBSession,
    user: CurrentUser,
) -> FinanceSnapshotRead:
    _require_volet(user)
    obj = await db.get(EntrepriseFinanceSnapshot, snapshot_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Snapshot introuvable.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return FinanceSnapshotRead.model_validate(obj)


@router.delete(
    "/finance/snapshots/{snapshot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_finance_snapshot(
    snapshot_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(EntrepriseFinanceSnapshot, snapshot_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Snapshot introuvable.")
    await db.delete(obj)
    await db.commit()


@router.get(
    "/{entreprise_id}/finance/timeseries",
    response_model=FinanceTimeseries,
)
async def get_finance_timeseries(
    entreprise_id: int,
    db: DBSession,
    user: CurrentUser,
    months: int = 24,
) -> FinanceTimeseries:
    _require_volet(user)
    cutoff = _normalize_year_month(date.today()) - timedelta(days=months * 31)
    rows = (
        await db.execute(
            select(EntrepriseFinanceSnapshot)
            .where(
                and_(
                    EntrepriseFinanceSnapshot.entreprise_id == entreprise_id,
                    EntrepriseFinanceSnapshot.year_month >= cutoff,
                )
            )
            .order_by(EntrepriseFinanceSnapshot.year_month.asc())
        )
    ).scalars().all()

    out = FinanceTimeseries(entreprise_id=entreprise_id)
    for r in rows:
        out.months.append(r.year_month.strftime("%Y-%m"))
        out.revenu.append(float(r.revenu) if r.revenu is not None else None)
        out.depenses.append(
            float(r.depenses) if r.depenses is not None else None
        )
        out.ebitda.append(float(r.ebitda) if r.ebitda is not None else None)
        out.tresorerie.append(
            float(r.tresorerie) if r.tresorerie is not None else None
        )
        out.valorisation.append(
            float(r.valorisation_estimee)
            if r.valorisation_estimee is not None
            else None
        )
    return out


@router.get(
    "/finance/summaries",
    response_model=List[EntrepriseFinanceSummary],
)
async def list_finance_summaries(
    db: DBSession, user: CurrentUser
) -> List[EntrepriseFinanceSummary]:
    """Heatmap multi-entreprises : 1 row par entreprise active."""
    _require_volet(user)
    entreprises = (
        await db.execute(
            select(Entreprise)
            .where(Entreprise.is_active.is_(True))
            .order_by(Entreprise.name.asc())
        )
    ).scalars().all()

    summaries: List[EntrepriseFinanceSummary] = []
    cutoff_12m = _normalize_year_month(date.today()) - timedelta(days=365)
    for ent in entreprises:
        # Last snapshot
        last = (
            await db.execute(
                select(EntrepriseFinanceSnapshot)
                .where(EntrepriseFinanceSnapshot.entreprise_id == ent.id)
                .order_by(EntrepriseFinanceSnapshot.year_month.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        # TTM (12 derniers mois)
        ttm_row = (
            await db.execute(
                select(
                    func.coalesce(func.sum(EntrepriseFinanceSnapshot.revenu), 0),
                    func.coalesce(func.sum(EntrepriseFinanceSnapshot.ebitda), 0),
                ).where(
                    and_(
                        EntrepriseFinanceSnapshot.entreprise_id == ent.id,
                        EntrepriseFinanceSnapshot.year_month >= cutoff_12m,
                    )
                )
            )
        ).one()

        # Active value plan
        plan = (
            await db.execute(
                select(EntrepriseValuePlan).where(
                    and_(
                        EntrepriseValuePlan.entreprise_id == ent.id,
                        EntrepriseValuePlan.is_active.is_(True),
                    )
                )
            )
        ).scalar_one_or_none()

        valo_courante = (
            float(last.valorisation_estimee)
            if last and last.valorisation_estimee is not None
            else None
        )
        target = float(plan.target_valuation) if plan else None
        progress = (
            round((valo_courante / target) * 100, 1)
            if (valo_courante and target and target > 0)
            else None
        )

        summaries.append(
            EntrepriseFinanceSummary(
                entreprise_id=ent.id,
                name=ent.name,
                color_accent=ent.color_accent,
                last_month=(
                    last.year_month.strftime("%Y-%m") if last else None
                ),
                revenu_ttm=float(ttm_row[0] or 0) or None,
                ebitda_ttm=float(ttm_row[1] or 0) or None,
                tresorerie_courante=(
                    float(last.tresorerie)
                    if last and last.tresorerie is not None
                    else None
                ),
                valorisation_courante=valo_courante,
                target_valuation=target,
                progress_pct=progress,
            )
        )
    return summaries


# ── Value plan + milestones ────────────────────────────────────────────


@router.get(
    "/{entreprise_id}/value-plan", response_model=Optional[ValuePlanRead]
)
async def get_active_value_plan(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> Optional[ValuePlanRead]:
    """Retourne le plan actif (ou None s'il n'y en a pas)."""
    _require_volet(user)
    obj = (
        await db.execute(
            select(EntrepriseValuePlan).where(
                and_(
                    EntrepriseValuePlan.entreprise_id == entreprise_id,
                    EntrepriseValuePlan.is_active.is_(True),
                )
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        return None
    return _plan_to_read(obj)


@router.post(
    "/value-plans",
    response_model=ValuePlanRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_value_plan(
    payload: ValuePlanCreate, db: DBSession, user: CurrentUser
) -> ValuePlanRead:
    _require_volet(user)
    ent = await db.get(Entreprise, payload.entreprise_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entreprise introuvable.")

    # Désactive les plans actifs existants si on en crée un nouveau actif.
    if payload.is_active:
        existing = (
            await db.execute(
                select(EntrepriseValuePlan).where(
                    and_(
                        EntrepriseValuePlan.entreprise_id == payload.entreprise_id,
                        EntrepriseValuePlan.is_active.is_(True),
                    )
                )
            )
        ).scalars().all()
        for old in existing:
            old.is_active = False
            old.updated_at = _now()

    data = payload.model_dump()
    drivers = data.pop("drivers", None)
    obj = EntrepriseValuePlan(**data)
    obj.drivers_json = _drivers_to_json(
        [ValuePlanDriverItem(**d) for d in drivers] if drivers else None
    )
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _plan_to_read(obj)


@router.patch("/value-plans/{plan_id}", response_model=ValuePlanRead)
async def update_value_plan(
    plan_id: int,
    payload: ValuePlanUpdate,
    db: DBSession,
    user: CurrentUser,
) -> ValuePlanRead:
    _require_volet(user)
    obj = await db.get(EntrepriseValuePlan, plan_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Plan introuvable.")
    data = payload.model_dump(exclude_unset=True)
    if "drivers" in data:
        drivers = data.pop("drivers")
        obj.drivers_json = _drivers_to_json(
            [ValuePlanDriverItem(**d) if isinstance(d, dict) else d for d in (drivers or [])]
        )
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return _plan_to_read(obj)


@router.delete(
    "/value-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_value_plan(
    plan_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(EntrepriseValuePlan, plan_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Plan introuvable.")
    await db.delete(obj)
    await db.commit()


# Milestones


@router.get(
    "/value-plans/{plan_id}/milestones",
    response_model=List[ValueMilestoneRead],
)
async def list_milestones(
    plan_id: int, db: DBSession, user: CurrentUser
) -> List[ValueMilestoneRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(EntrepriseValueMilestone)
            .where(EntrepriseValueMilestone.plan_id == plan_id)
            .order_by(EntrepriseValueMilestone.target_date.asc())
        )
    ).scalars().all()
    return [ValueMilestoneRead.model_validate(r) for r in rows]


@router.post(
    "/value-milestones",
    response_model=ValueMilestoneRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_milestone(
    payload: ValueMilestoneCreate, db: DBSession, user: CurrentUser
) -> ValueMilestoneRead:
    _require_volet(user)
    plan = await db.get(EntrepriseValuePlan, payload.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan introuvable.")
    obj = EntrepriseValueMilestone(**payload.model_dump())
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return ValueMilestoneRead.model_validate(obj)


@router.patch(
    "/value-milestones/{milestone_id}",
    response_model=ValueMilestoneRead,
)
async def update_milestone(
    milestone_id: int,
    payload: ValueMilestoneUpdate,
    db: DBSession,
    user: CurrentUser,
) -> ValueMilestoneRead:
    _require_volet(user)
    obj = await db.get(EntrepriseValueMilestone, milestone_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Milestone introuvable.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return ValueMilestoneRead.model_validate(obj)


@router.delete(
    "/value-milestones/{milestone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_milestone(
    milestone_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(EntrepriseValueMilestone, milestone_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Milestone introuvable.")
    await db.delete(obj)
    await db.commit()
