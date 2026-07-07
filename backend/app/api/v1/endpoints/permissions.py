"""Permissions configurables (Paramètres → Permissions).

- GET  /permissions            — la grille (capacités + rôle minimum courant).
                                  Lecture réservée aux admins+ (pour voir les
                                  règles), édition à l'owner.
- PUT  /permissions/{capability} — change le rôle minimum d'une capacité
                                  (owner uniquement). Invalide le cache +
                                  journalise (audit log).

Socle : 4 rôles hiérarchiques (owner>admin>manager>employee). « Qui peut »
= rôle minimum requis. Les valeurs sont pré-remplies au démarrage avec le
comportement actuel (aucun changement visible tant que rien n'est modifié).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminRole, RequireOwner
from app.core.capabilities import (
    CAPABILITIES,
    CAPABILITIES_BY_ID,
    ROLES_ASCENDING,
    is_valid_role,
)
from app.models.role_permission import RolePermission
from app.services.audit import log_action
from app.services.permissions_service import invalidate_permissions_cache

router = APIRouter(prefix="/permissions", tags=["permissions"])


class CapabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    capability: str
    label: str
    description: str
    category: str
    min_role: str
    default_min_role: str


class PermissionsGrid(BaseModel):
    #: Rôles valides du plus bas au plus haut (pour construire l'UI).
    roles: list[str]
    capabilities: list[CapabilityRead]


class SetMinRoleBody(BaseModel):
    min_role: str


async def _current_min_roles(db) -> dict[str, str]:
    rows = (await db.execute(select(RolePermission))).scalars().all()
    return {r.capability: r.min_role for r in rows}


@router.get("", response_model=PermissionsGrid)
async def get_permissions(db: DBSession, _: RequireAdminRole) -> PermissionsGrid:
    stored = await _current_min_roles(db)
    caps = [
        CapabilityRead(
            capability=c.id,
            label=c.label,
            description=c.description,
            category=c.category,
            min_role=stored.get(c.id, c.default_min_role),
            default_min_role=c.default_min_role,
        )
        for c in CAPABILITIES
    ]
    return PermissionsGrid(roles=ROLES_ASCENDING, capabilities=caps)


@router.put("/{capability}", response_model=CapabilityRead)
async def set_min_role(
    capability: str,
    body: SetMinRoleBody,
    db: DBSession,
    owner: RequireOwner,
) -> CapabilityRead:
    cap = CAPABILITIES_BY_ID.get(capability)
    if cap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Capacité inconnue.",
        )
    if not is_valid_role(body.min_role):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Rôle invalide.",
        )

    row = (
        await db.execute(
            select(RolePermission).where(
                RolePermission.capability == capability
            )
        )
    ).scalar_one_or_none()
    old = row.min_role if row else cap.default_min_role
    if row is None:
        row = RolePermission(capability=capability, min_role=body.min_role)
        db.add(row)
    else:
        row.min_role = body.min_role
    await db.flush()
    invalidate_permissions_cache()

    await log_action(
        db,
        user=owner,
        action="permission.min_role_changed",
        entity_type="permission",
        details={
            "capability": capability,
            "old_min_role": old,
            "new_min_role": body.min_role,
        },
    )

    return CapabilityRead(
        capability=cap.id,
        label=cap.label,
        description=cap.description,
        category=cap.category,
        min_role=row.min_role,
        default_min_role=cap.default_min_role,
    )
