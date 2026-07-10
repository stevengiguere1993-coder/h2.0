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

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireAdminRole, RequireOwner
from app.core.access_registry import (
    PAGE_KEY_PREFIX,
    PAGES,
    PAGES_BY_KEY,
    VOLET_LABELS,
)
from app.core.capabilities import (
    CAPABILITIES,
    CAPABILITIES_BY_ID,
    ROLES_ASCENDING,
    is_valid_role,
)
from app.models.role_permission import RolePermission
from app.models.user import User
from app.models.user_access_override import UserAccessOverride
from app.services.access_service import compute_access
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


# ═══ Refonte permissions 2026-07 — PAGES (visibilité), access-map, vue par
# utilisateur et exceptions individuelles ═══════════════════════════════════


class PageRead(BaseModel):
    key: str
    label: str
    volet: str
    volet_label: str
    min_role: str
    default_min_role: str


class PagesGrid(BaseModel):
    roles: list[str]
    #: Libellés FR des volets, pour grouper la matrice par pôle.
    volet_labels: dict[str, str]
    pages: list[PageRead]


class AccessMapEntry(BaseModel):
    key: str
    volet: str
    routes: List[str]


@router.get("/pages", response_model=PagesGrid)
async def get_pages_grid(db: DBSession, _: RequireAdminRole) -> PagesGrid:
    """Grille de VISIBILITÉ des pages (matrice par pôle de la nouvelle page
    Permissions) : chaque page du registre + son rôle minimum courant."""
    stored = await _current_min_roles(db)
    out = [
        PageRead(
            key=p.key,
            label=p.label,
            volet=p.volet,
            volet_label=VOLET_LABELS.get(p.volet, p.volet),
            min_role=stored.get(
                f"{PAGE_KEY_PREFIX}{p.key}", p.default_min_role
            ),
            default_min_role=p.default_min_role,
        )
        for p in PAGES
    ]
    return PagesGrid(
        roles=ROLES_ASCENDING, volet_labels=VOLET_LABELS, pages=out
    )


@router.put("/pages/{page_key}", response_model=PageRead)
async def set_page_min_role(
    page_key: str,
    body: SetMinRoleBody,
    db: DBSession,
    owner: RequireOwner,
) -> PageRead:
    """Change le rôle minimum requis pour VOIR une page (owner). Audit log +
    invalidation du cache — effet immédiat (menus, garde de page, backend)."""
    page = PAGES_BY_KEY.get(page_key)
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Page inconnue."
        )
    if not is_valid_role(body.min_role):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Rôle invalide.",
        )
    full_key = f"{PAGE_KEY_PREFIX}{page_key}"
    row = (
        await db.execute(
            select(RolePermission).where(RolePermission.capability == full_key)
        )
    ).scalar_one_or_none()
    old = row.min_role if row else page.default_min_role
    if row is None:
        row = RolePermission(capability=full_key, min_role=body.min_role)
        db.add(row)
    else:
        row.min_role = body.min_role
    await db.flush()
    invalidate_permissions_cache()

    await log_action(
        db,
        user=owner,
        action="permission.page_min_role_changed",
        entity_type="permission",
        details={
            "page": page_key,
            "old_min_role": old,
            "new_min_role": body.min_role,
        },
    )

    return PageRead(
        key=page.key,
        label=page.label,
        volet=page.volet,
        volet_label=VOLET_LABELS.get(page.volet, page.volet),
        min_role=row.min_role,
        default_min_role=page.default_min_role,
    )


@router.get("/access-map", response_model=List[AccessMapEntry])
async def get_access_map(_: CurrentUser) -> List[AccessMapEntry]:
    """Mapping route → clé de page pour le garde frontend (AccessGuard).
    Statique (dérivé du registre), lisible par tout utilisateur connecté —
    les DROITS eux-mêmes viennent de /auth/me (dict ``access``)."""
    return [
        AccessMapEntry(key=p.key, volet=p.volet, routes=list(p.routes))
        for p in PAGES
    ]


class UserAccessRead(BaseModel):
    user_id: int
    email: str
    display_name: str
    role: str
    volets: List[str]
    access: dict[str, bool]


async def _get_user_or_404(db, user_id: int) -> User:
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable.",
        )
    return u


@router.get("/users/{user_id}/access", response_model=UserAccessRead)
async def get_user_access(
    user_id: int, db: DBSession, _: RequireAdminRole
) -> UserAccessRead:
    """Vue « par utilisateur » : TOUT ce que ce compte voit et peut faire,
    calculé exactement comme /auth/me le ferait pour lui."""
    u = await _get_user_or_404(db, user_id)
    return UserAccessRead(
        user_id=u.id,
        email=u.email,
        display_name=u.display_name,
        role=u.role,
        volets=u.volets,
        access=await compute_access(db, u),
    )


class OverrideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    allow: bool


class OverrideSet(BaseModel):
    key: str = Field(..., min_length=1, max_length=128)
    #: True = accorder, False = retirer, None = supprimer l'exception
    #: (retour à la règle générale).
    allow: Optional[bool] = None


@router.get(
    "/users/{user_id}/overrides", response_model=List[OverrideRead]
)
async def list_user_overrides(
    user_id: int, db: DBSession, _: RequireAdminRole
) -> List[OverrideRead]:
    rows = (
        await db.execute(
            select(UserAccessOverride).where(
                UserAccessOverride.user_id == user_id
            )
        )
    ).scalars().all()
    return [OverrideRead.model_validate(r) for r in rows]


@router.put(
    "/users/{user_id}/overrides", response_model=List[OverrideRead]
)
async def set_user_override(
    user_id: int,
    body: OverrideSet,
    db: DBSession,
    owner: RequireOwner,
) -> List[OverrideRead]:
    """Pose / met à jour / supprime UNE exception individuelle (owner).
    ``allow=null`` supprime l'exception → la règle générale reprend."""
    u = await _get_user_or_404(db, user_id)
    row = (
        await db.execute(
            select(UserAccessOverride).where(
                UserAccessOverride.user_id == user_id,
                UserAccessOverride.key == body.key,
            )
        )
    ).scalar_one_or_none()

    if body.allow is None:
        old = row.allow if row else None
        if row is not None:
            await db.delete(row)
            await db.flush()
        action = "removed"
    else:
        old = row.allow if row else None
        if row is None:
            row = UserAccessOverride(
                user_id=user_id,
                key=body.key,
                allow=body.allow,
                updated_by_user_id=getattr(owner, "id", None),
            )
            db.add(row)
        else:
            row.allow = body.allow
            row.updated_by_user_id = getattr(owner, "id", None)
        await db.flush()
        action = "set"

    await log_action(
        db,
        user=owner,
        action="permission.user_override_changed",
        entity_type="permission",
        entity_id=user_id,
        details={
            "target_user": u.email,
            "key": body.key,
            "old_allow": old,
            "new_allow": body.allow,
            "op": action,
        },
    )

    rows = (
        await db.execute(
            select(UserAccessOverride).where(
                UserAccessOverride.user_id == user_id
            )
        )
    ).scalars().all()
    return [OverrideRead.model_validate(r) for r in rows]
