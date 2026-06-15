"""Séquence de relance (cadence) configurable — endpoints.

Une seule séquence GLOBALE partagée par tous les leads/clients. Les
étapes sont ordonnées par `position`. L'utilisateur les édite dans l'UI
Relances ; le moteur (cron) les exécute.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.automation_setting import AutomationSetting
from app.models.cadence_step import CadenceStep
from app.models.relance_plan import RelancePlan
from app.schemas.cadence_step import (
    CadenceStepCreate,
    CadenceStepRead,
    CadenceStepUpdate,
)

router = APIRouter(prefix="/relances", tags=["relances"])

# Clé d'automatisation (hub Réglages) pour activer/couper le moteur.
_RELANCE_KEY = "construction_relances"


# Cadence par défaut, créée au premier chargement si la table est vide :
# Appel J0 → Appel J+2 → Courriel J+2 (tentatives sans réponse).
_DEFAULT_STEPS = [
    {"channel": "call", "delay_days": 0, "label": "Premier appel"},
    {"channel": "call", "delay_days": 2, "label": "Deuxième appel"},
    {
        "channel": "email",
        "delay_days": 2,
        "label": "Courriel — 2 tentatives sans réponse",
    },
]


async def _all_steps(db) -> list[CadenceStep]:
    return list(
        (
            await db.execute(
                select(CadenceStep).order_by(
                    CadenceStep.position.asc(), CadenceStep.id.asc()
                )
            )
        )
        .scalars()
        .all()
    )


@router.get("/cadence", response_model=list[CadenceStepRead])
async def list_cadence(db: DBSession, _: RequireManager) -> list[CadenceStepRead]:
    steps = await _all_steps(db)
    if not steps:
        # Amorçage de la cadence par défaut pour que l'utilisateur ait
        # tout de suite quelque chose à visualiser / personnaliser.
        for i, s in enumerate(_DEFAULT_STEPS):
            db.add(
                CadenceStep(
                    position=i,
                    channel=s["channel"],
                    delay_days=s["delay_days"],
                    label=s["label"],
                    active=True,
                )
            )
        await db.flush()
        steps = await _all_steps(db)
    return [CadenceStepRead.model_validate(s) for s in steps]


@router.post(
    "/cadence",
    response_model=CadenceStepRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_step(
    data: CadenceStepCreate, db: DBSession, _: RequireManager
) -> CadenceStepRead:
    if data.position is None:
        existing = await _all_steps(db)
        position = (max((s.position for s in existing), default=-1)) + 1
    else:
        position = data.position
    step = CadenceStep(
        position=position,
        channel=data.channel,
        delay_days=data.delay_days,
        label=data.label,
        email_template_id=data.email_template_id,
        active=data.active,
    )
    db.add(step)
    await db.flush()
    return CadenceStepRead.model_validate(step)


@router.patch("/cadence/{step_id}", response_model=CadenceStepRead)
async def update_step(
    step_id: int, data: CadenceStepUpdate, db: DBSession, _: RequireManager
) -> CadenceStepRead:
    step = (
        await db.execute(select(CadenceStep).where(CadenceStep.id == step_id))
    ).scalar_one_or_none()
    if step is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Étape introuvable.")
    patch = data.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(step, field, value)
    await db.flush()
    return CadenceStepRead.model_validate(step)


@router.delete("/cadence/{step_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_step(
    step_id: int, db: DBSession, _: RequireManager
) -> Response:
    step = (
        await db.execute(select(CadenceStep).where(CadenceStep.id == step_id))
    ).scalar_one_or_none()
    if step is not None:
        await db.delete(step)
        await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Activation globale du moteur de relances ──
class RelanceSettings(BaseModel):
    enabled: bool


@router.get("/settings", response_model=RelanceSettings)
async def get_settings(db: DBSession, _: RequireManager) -> RelanceSettings:
    row = (
        await db.execute(
            select(AutomationSetting).where(
                AutomationSetting.key == _RELANCE_KEY
            )
        )
    ).scalar_one_or_none()
    # Absence de ligne = activé par défaut (fail-open).
    return RelanceSettings(enabled=True if row is None else bool(row.enabled))


@router.put("/settings", response_model=RelanceSettings)
async def put_settings(
    data: RelanceSettings, db: DBSession, user: RequireManager
) -> RelanceSettings:
    row = (
        await db.execute(
            select(AutomationSetting).where(
                AutomationSetting.key == _RELANCE_KEY
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = AutomationSetting(key=_RELANCE_KEY, enabled=data.enabled)
        db.add(row)
    else:
        row.enabled = data.enabled
    row.updated_by_user_id = getattr(user, "id", None)
    await db.flush()
    return RelanceSettings(enabled=bool(row.enabled))


# ── Plan de relance d'un lead (étapes faites / en cours / à venir) ──
class PlanStepView(BaseModel):
    position: int
    channel: str
    label: str
    delay_days: int
    state: str  # done | current | upcoming


class PlanView(BaseModel):
    status: str  # none | active | done | stopped
    next_at: Optional[datetime]
    current_index: Optional[int]
    steps: list[PlanStepView]


@router.get("/plan/{contact_request_id}", response_model=PlanView)
async def get_plan(
    contact_request_id: int, db: DBSession, _: CurrentUser
) -> PlanView:
    # On indexe sur les étapes ACTIVES (cohérent avec le moteur).
    steps = list(
        (
            await db.execute(
                select(CadenceStep)
                .where(CadenceStep.active.is_(True))
                .order_by(
                    CadenceStep.position.asc(), CadenceStep.id.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    plan = (
        await db.execute(
            select(RelancePlan).where(
                RelancePlan.contact_request_id == contact_request_id
            )
        )
    ).scalar_one_or_none()

    if plan is None:
        return PlanView(
            status="none",
            next_at=None,
            current_index=None,
            steps=[
                PlanStepView(
                    position=s.position,
                    channel=s.channel,
                    label=s.label,
                    delay_days=s.delay_days,
                    state="upcoming",
                )
                for s in steps
            ],
        )

    cur = plan.step_index
    views: list[PlanStepView] = []
    for idx, s in enumerate(steps):
        if plan.status == "done" or idx < cur:
            state = "done"
        elif idx == cur and plan.status == "active":
            state = "current"
        else:
            state = "upcoming"
        views.append(
            PlanStepView(
                position=s.position,
                channel=s.channel,
                label=s.label,
                delay_days=s.delay_days,
                state=state,
            )
        )
    return PlanView(
        status=plan.status,
        next_at=plan.next_at,
        current_index=cur,
        steps=views,
    )
