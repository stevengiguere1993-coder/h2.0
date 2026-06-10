"""Logique d'accès au coffre « Abonnements ».

Règle : le propriétaire (``owner``) a toujours accès et gère la liste ;
tout autre utilisateur doit figurer explicitement dans
:class:`SubscriptionVaultAccess`. Les admins n'ont PAS d'accès
automatique — c'est une liste nominative choisie par le proprio.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription_vault_access import SubscriptionVaultAccess
from app.models.user import User


async def user_has_vault_access(db: AsyncSession, user: User) -> bool:
    """True si ``user`` peut voir/utiliser le coffre."""
    if user.role == "owner":
        return True
    row = (
        await db.execute(
            select(SubscriptionVaultAccess.id).where(
                SubscriptionVaultAccess.user_id == user.id
            )
        )
    ).first()
    return row is not None


async def list_access_user_ids(db: AsyncSession) -> list[int]:
    """Ids des utilisateurs explicitement autorisés (hors owner implicite)."""
    rows = (
        await db.execute(select(SubscriptionVaultAccess.user_id))
    ).all()
    return [r[0] for r in rows]
