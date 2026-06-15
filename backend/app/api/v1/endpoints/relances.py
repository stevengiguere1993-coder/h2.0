"""Séquence de relance (cadence) configurable — endpoints.

Une seule séquence GLOBALE partagée par tous les leads/clients. Les
étapes sont ordonnées par `position`. L'utilisateur les édite dans l'UI
Relances ; le moteur (cron) les exécute.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import DBSession, RequireManager
from app.models.cadence_step import CadenceStep
from app.schemas.cadence_step import (
    CadenceStepCreate,
    CadenceStepRead,
    CadenceStepUpdate,
)

router = APIRouter(prefix="/relances", tags=["relances"])


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
