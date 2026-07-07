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

from app.api.deps import get_current_user
from app.core.capabilities import CAPABILITIES_BY_ID
from app.db.session import AsyncSessionLocal
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
    """Rôle minimum requis pour ``capability`` (DB si dispo, sinon défaut)."""
    if time.monotonic() - _cache_loaded_at > _CACHE_TTL_SECONDS:
        await _load_cache()
    stored = _cache.get(capability)
    if stored:
        return stored
    cap = CAPABILITIES_BY_ID.get(capability)
    # Sécurité par défaut : si la capacité est inconnue, on exige owner.
    return cap.default_min_role if cap else "owner"


def require_capability(capability: str):
    """Dépendance FastAPI : 403 si le compte courant n'atteint pas le rôle
    minimum configuré pour ``capability``."""

    async def check(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        min_role = await get_min_role(capability)
        if not current_user.has_min_role(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissions insuffisantes pour cette action.",
            )
        return current_user

    return check
