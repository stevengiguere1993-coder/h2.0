"""Endpoints REST Drive Page Modules — Phase 7.

Pilotent l'affichage de la section Drive (``<EntityDriveSection>``) sur
les pages d'entités Kratos. Tous protégés par
:data:`RequireAdminOrOwner`. Les mutations posent un audit log
(table générique ``audit_logs``).

Surface :

- ``GET   /api/v1/drive/page-modules`` — liste tous les modules + stats
  (nb ``DriveEntityLink`` par type).
- ``GET   /api/v1/drive/page-modules/{entity_type}/status`` — statut
  minimal ``{active, display_title, has_convention}`` consommé par le
  composant frontend. Si le module n'existe pas → ``{active: False}``
  par défaut (jamais un 404).
- ``PATCH /api/v1/drive/page-modules/{entity_type}`` — upsert du toggle
  et/ou du titre (auto-crée la ligne si absente).
- ``POST  /api/v1/drive/page-modules`` — création explicite.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.drive_convention import DriveConvention
from app.models.drive_entity_link import DriveEntityLink
from app.models.drive_page_module import DrivePageModule
from app.schemas.drive_page_module import (
    DrivePageModuleCreate,
    DrivePageModulePatch,
    DrivePageModuleRead,
    DrivePageModuleStatus,
)
from app.services.audit import log_action

log = logging.getLogger(__name__)

router = APIRouter(prefix="/drive", tags=["drive-page-modules"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _has_active_convention(db: DBSession, entity_type: str) -> bool:
    """True s'il existe au moins une convention active pour ce type."""
    stmt = select(DriveConvention.id).where(
        DriveConvention.entity_type == entity_type,
        DriveConvention.active.is_(True),
    )
    return (await db.execute(stmt)).first() is not None


# ---------------------------------------------------------------------------
# Listing + stats
# ---------------------------------------------------------------------------


@router.get(
    "/page-modules",
    response_model=list[DrivePageModuleRead],
)
async def list_page_modules(
    db: DBSession,
    user: RequireAdminOrOwner,
) -> list[DrivePageModuleRead]:
    """Liste tous les modules avec le nombre de liens Drive par type."""
    stmt = select(DrivePageModule).order_by(
        DrivePageModule.display_order.asc(), DrivePageModule.id.asc()
    )
    modules = (await db.execute(stmt)).scalars().all()

    # Stat : nombre de DriveEntityLink groupés par entity_type. Une
    # seule requête agrégée plutôt qu'un COUNT par module.
    count_stmt = select(
        DriveEntityLink.entity_type,
        func.count(DriveEntityLink.id),
    ).group_by(DriveEntityLink.entity_type)
    counts = {
        row[0]: row[1] for row in (await db.execute(count_stmt)).all()
    }

    out: list[DrivePageModuleRead] = []
    for m in modules:
        read = DrivePageModuleRead.model_validate(m)
        read.linked_count = int(counts.get(m.entity_type, 0))
        out.append(read)
    return out


# ---------------------------------------------------------------------------
# Statut (consommé par le composant frontend)
# ---------------------------------------------------------------------------


@router.get(
    "/page-modules/{entity_type}/status",
    response_model=DrivePageModuleStatus,
)
async def get_page_module_status(
    entity_type: str,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> DrivePageModuleStatus:
    """Statut minimal pour ``<EntityDriveSection>``.

    Si le module n'existe pas en BDD → ``{active: False}`` par défaut.
    On ne 404 jamais : une page câblée pour un type non encore seedé
    doit simplement masquer sa section sans erreur.
    """
    stmt = select(DrivePageModule).where(
        DrivePageModule.entity_type == entity_type
    )
    module = (await db.execute(stmt)).scalar_one_or_none()
    if module is None:
        return DrivePageModuleStatus(active=False, display_title=None)
    return DrivePageModuleStatus(
        active=module.active,
        display_title=module.display_title,
        has_convention=await _has_active_convention(db, entity_type),
    )


# ---------------------------------------------------------------------------
# Upsert (toggle + titre)
# ---------------------------------------------------------------------------


@router.patch(
    "/page-modules/{entity_type}",
    response_model=DrivePageModuleRead,
)
async def patch_page_module(
    entity_type: str,
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DrivePageModulePatch = Body(...),
) -> DrivePageModuleRead:
    """Upsert : met à jour les champs présents, crée la ligne si absente."""
    stmt = select(DrivePageModule).where(
        DrivePageModule.entity_type == entity_type
    )
    module = (await db.execute(stmt)).scalar_one_or_none()
    created = False
    if module is None:
        module = DrivePageModule(
            entity_type=entity_type,
            active=False,
            created_by_user_id=user.id,
        )
        db.add(module)
        created = True

    changes: dict[str, object] = {}
    if payload.active is not None:
        module.active = payload.active
        changes["active"] = payload.active
    if payload.display_title is not None:
        # Chaîne vide → on remet NULL (libellé par défaut côté composant).
        cleaned = payload.display_title.strip() or None
        module.display_title = cleaned
        changes["display_title"] = cleaned
    if payload.display_order is not None:
        module.display_order = payload.display_order
        changes["display_order"] = payload.display_order

    await db.flush()
    await log_action(
        db,
        user=user,
        action="drive_page_module.upsert",
        entity_type="drive_page_module",
        entity_id=module.id,
        details={
            "target_entity_type": entity_type,
            "created": created,
            "changes": changes,
        },
    )
    await db.commit()
    await db.refresh(module)

    read = DrivePageModuleRead.model_validate(module)
    count_stmt = select(func.count(DriveEntityLink.id)).where(
        DriveEntityLink.entity_type == entity_type
    )
    read.linked_count = int((await db.execute(count_stmt)).scalar() or 0)
    return read


# ---------------------------------------------------------------------------
# Création explicite
# ---------------------------------------------------------------------------


@router.post(
    "/page-modules",
    response_model=DrivePageModuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_page_module(
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DrivePageModuleCreate = Body(...),
) -> DrivePageModuleRead:
    """Crée explicitement un module. 409 si le type existe déjà."""
    stmt = select(DrivePageModule).where(
        DrivePageModule.entity_type == payload.entity_type
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Un module existe déjà pour {payload.entity_type} "
            f"(#{existing.id}). Utilise PATCH pour le modifier.",
        )

    module = DrivePageModule(
        entity_type=payload.entity_type,
        active=payload.active,
        display_title=(payload.display_title or None),
        display_order=payload.display_order,
        created_by_user_id=user.id,
    )
    db.add(module)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="drive_page_module.create",
        entity_type="drive_page_module",
        entity_id=module.id,
        details={
            "target_entity_type": payload.entity_type,
            "active": payload.active,
        },
    )
    await db.commit()
    await db.refresh(module)
    return DrivePageModuleRead.model_validate(module)
