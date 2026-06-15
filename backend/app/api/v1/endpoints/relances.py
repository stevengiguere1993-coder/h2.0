"""Séquence de relance (cadence) configurable — endpoints.

Une seule séquence GLOBALE partagée par tous les leads/clients. Les
étapes sont ordonnées par `position`. L'utilisateur les édite dans l'UI
Relances ; le moteur (cron) les exécute.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.automation_setting import AutomationSetting
from app.models.cadence_step import CadenceStep
from app.models.relance_item import RelanceItem
from app.schemas.cadence_step import (
    CadenceStepCreate,
    CadenceStepRead,
    CadenceStepUpdate,
)
from app.schemas.relance_item import (
    RelanceItemCreate,
    RelanceItemRead,
    RelanceItemUpdate,
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


# ── Relances planifiées d'un lead (modifiables une à une) ──
@router.get(
    "/plan/{contact_request_id}", response_model=list[RelanceItemRead]
)
async def list_items(
    contact_request_id: int, db: DBSession, _: CurrentUser
) -> list[RelanceItemRead]:
    rows = list(
        (
            await db.execute(
                select(RelanceItem)
                .where(
                    RelanceItem.contact_request_id == contact_request_id
                )
                .order_by(
                    RelanceItem.scheduled_at.asc(),
                    RelanceItem.position.asc(),
                    RelanceItem.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [RelanceItemRead.model_validate(r) for r in rows]


@router.post(
    "/plan/{contact_request_id}",
    response_model=RelanceItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    contact_request_id: int,
    data: RelanceItemCreate,
    db: DBSession,
    _: RequireManager,
) -> RelanceItemRead:
    pos = data.position
    if pos is None:
        existing = (
            await db.execute(
                select(RelanceItem.position).where(
                    RelanceItem.contact_request_id == contact_request_id
                )
            )
        ).all()
        pos = (max((p[0] for p in existing), default=-1)) + 1
    item = RelanceItem(
        contact_request_id=contact_request_id,
        position=pos,
        channel=data.channel,
        label=data.label,
        email_template_id=data.email_template_id,
        scheduled_at=data.scheduled_at,
        status="pending",
    )
    db.add(item)
    await db.flush()
    return RelanceItemRead.model_validate(item)


@router.patch("/item/{item_id}", response_model=RelanceItemRead)
async def update_item(
    item_id: int, data: RelanceItemUpdate, db: DBSession, _: RequireManager
) -> RelanceItemRead:
    item = (
        await db.execute(
            select(RelanceItem).where(RelanceItem.id == item_id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Relance introuvable."
        )
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.flush()
    return RelanceItemRead.model_validate(item)


@router.delete("/item/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: int, db: DBSession, _: RequireManager
) -> Response:
    item = (
        await db.execute(
            select(RelanceItem).where(RelanceItem.id == item_id)
        )
    ).scalar_one_or_none()
    if item is not None:
        await db.delete(item)
        await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
