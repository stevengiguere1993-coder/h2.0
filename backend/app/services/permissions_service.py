"""Grille de permissions : chargement caché + garde dynamique.

- ``get_min_role(cap)`` : rôle minimum requis pour une capacité, lu depuis la
  table ``role_permissions`` (cache court TTL). Fallback sur le défaut du
  registre si la ligne manque (nouvelle capacité pas encore semée).
- ``require_capability(cap)`` : fabrique une dépendance FastAPI (403 si le
  compte courant n'a pas le rôle minimum). Remplace les gardes en dur
  (RequireManager, etc.) sur les endpoints rendus configurables.
- ``invalidate_permissions_cache()`` : à appeler après une écriture (PUT).

Le cache est un simple dict module-level + horodatage monotone : la grille
change rarement, on évite un SELECT par requête sans complexité de plus.
"""
from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.access_registry import PAGE_KEY_PREFIX, PAGES_BY_KEY
from app.core.capabilities import CAPABILITIES_BY_ID
from app.db.session import AsyncSessionLocal, get_db
from app.models.role_permission import RolePermission
from app.models.user import User

_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, str] = {}
_cache_loaded_at: float = 0.0


async def _load_cache() -> None:
    global _cache, _cache_loaded_at
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(RolePermission))).scalars().all()
    _cache = {r.capability: r.min_role for r in rows}
    _cache_loaded_at = time.monotonic()


def invalidate_permissions_cache() -> None:
    """Force un rechargement au prochain accès (après une écriture)."""
    global _cache_loaded_at
    _cache_loaded_at = 0.0


async def get_min_role(capability: str) -> str:
    """Rôle minimum requis pour ``capability`` (DB si dispo, sinon défaut).

    Accepte aussi les clés de PAGE du registre central (``page:<page_key>``,
    refonte permissions 2026-07) : même table, même cache, fallback sur le
    défaut déclaré dans ``access_registry``."""
    if time.monotonic() - _cache_loaded_at > _CACHE_TTL_SECONDS:
        await _load_cache()
    stored = _cache.get(capability)
    if stored:
        return stored
    cap = CAPABILITIES_BY_ID.get(capability)
    if cap:
        return cap.default_min_role
    if capability.startswith(PAGE_KEY_PREFIX):
        page = PAGES_BY_KEY.get(capability[len(PAGE_KEY_PREFIX):])
        if page:
            return page.default_min_role
    # Sécurité par défaut : clé inconnue → on exige owner.
    return "owner"


async def user_has_capability(db, user: User, capability: str) -> bool:
    """L'utilisateur a-t-il la capacité ? — mêmes règles que
    ``compute_access`` (permissions v2, 2026-07-24) : exception
    individuelle d'abord (allow force l'accès, deny le retire — owner
    jamais bloqué), sinon rôle ≥ seuil configuré."""
    from app.models.user_access_override import UserAccessOverride

    row = (
        await db.execute(
            select(UserAccessOverride).where(
                UserAccessOverride.user_id == user.id,
                UserAccessOverride.key == capability,
            )
        )
    ).scalars().first()
    if row is not None:
        if row.allow:
            return True
        if user.role != "owner":
            return False
    return user.has_min_role(await get_min_role(capability))


def require_capability(capability: str):
    """Dépendance FastAPI : 403 si le compte courant n'a pas la capacité
    (rôle ≥ seuil configuré OU exception individuelle qui l'accorde —
    l'UI Paramètres → Permissions et les endpoints disent toujours
    pareil)."""

    async def check(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> User:
        if not await user_has_capability(db, current_user, capability):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissions insuffisantes pour cette action.",
            )
        return current_user

    return check
