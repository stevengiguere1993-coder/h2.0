"""Helpers to create in-app notifications.

Appelé par les autres services quand un événement important arrive
(soumission signée, facture payée, congé demandé, punch à approuver…).

Idempotence: les callers sont responsables de ne pas créer des
doublons — c'est plus simple que de dédupliquer ici avec une clé de
dédup, et en pratique chaque événement source ne se produit qu'une
fois par objet.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


log = logging.getLogger(__name__)


async def notify(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    title: str,
    body: Optional[str] = None,
    href: Optional[str] = None,
) -> Notification:
    n = Notification(
        user_id=user_id,
        kind=kind,
        title=title[:255],
        body=body,
        href=href[:500] if href else None,
    )
    db.add(n)
    await db.flush()
    return n


async def notify_role(
    db: AsyncSession,
    *,
    min_role: str,
    kind: str,
    title: str,
    body: Optional[str] = None,
    href: Optional[str] = None,
) -> int:
    """Fan-out a notification to every user at or above `min_role`.

    Utile pour « nouveau prospect », « punch à approuver » — on notifie
    tous les managers/admins d'un coup. Retourne le nombre de notifs
    créées.
    """
    from sqlalchemy import select

    from app.models.user import User

    rank_map = {"owner": 4, "admin": 3, "manager": 2, "employee": 1}
    min_rank = rank_map.get(min_role, 99)
    users = (
        await db.execute(select(User).where(User.is_active.is_(True)))
    ).scalars().all()
    count = 0
    for u in users:
        if rank_map.get(u.role, 0) >= min_rank:
            await notify(
                db,
                user_id=u.id,
                kind=kind,
                title=title,
                body=body,
                href=href,
            )
            count += 1
    return count
