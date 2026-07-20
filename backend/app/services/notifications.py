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
    push: bool = True,
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
    if push:
        await _push_best_effort(
            db, [user_id], kind=kind, title=title, body=body, href=href
        )
    return n


async def _push_best_effort(
    db: AsyncSession,
    user_ids: list[int],
    *,
    kind: str,
    title: str,
    body: Optional[str] = None,
    href: Optional[str] = None,
) -> None:
    """Double la notification « cloche » d'une notification PUSH.

    Sans ça, une notification n'existait que dans l'app : un gestionnaire
    qui n'a pas Kratos ouvert ne savait jamais qu'un client attendait une
    réponse (retour Phil 2026-07-20 : « Olivier ne reçoit pas de
    notification pour répondre au client »). Best-effort : si VAPID n'est
    pas configuré ou qu'aucun appareil n'est abonné, c'est un no-op
    silencieux — la cloche reste la source de vérité.
    """
    try:
        from app.integrations.webpush import push_to_users

        await push_to_users(
            db,
            user_ids=user_ids,
            title=title,
            body=body,
            href=href,
            tag=kind,
        )
    except Exception:  # noqa: BLE001 — jamais bloquant
        log.exception("push_to_users a échoué (kind=%s)", kind)


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
    cibles: list[int] = []
    for u in users:
        if rank_map.get(u.role, 0) >= min_rank:
            # push=False ici : un SEUL envoi push groupé après la boucle
            # (une requête au lieu d'une par destinataire).
            await notify(
                db,
                user_id=u.id,
                kind=kind,
                title=title,
                body=body,
                href=href,
                push=False,
            )
            cibles.append(u.id)
            count += 1
    if cibles:
        await _push_best_effort(
            db, cibles, kind=kind, title=title, body=body, href=href
        )
    return count
