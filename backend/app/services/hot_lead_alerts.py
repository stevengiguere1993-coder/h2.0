"""Notifications cloche pour les transitions de leads en statut HOT_LEAD.

Alimente la cloche de notifications de Philippe, Steven et Michael
(prénoms configurables via env `HOT_LEAD_ALERT_FIRSTNAMES`, sinon
défaut hardcodé). Match insensible à la casse sur `users.first_name`.

Pas d'idempotence côté service : c'est `update_lead` qui détecte
la transition (ancien_status != "hot_lead" → nouveau == "hot_lead")
et qui n'appelle qu'une seule fois.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prospection_lead import ProspectionLead
from app.models.user import User
from app.services.notifications import notify

log = logging.getLogger(__name__)

DEFAULT_ALERT_FIRSTNAMES = ("philippe", "steven", "michael")


def _alert_firstnames() -> List[str]:
    raw = os.environ.get("HOT_LEAD_ALERT_FIRSTNAMES", "")
    items = [x.strip().lower() for x in raw.split(",") if x.strip()]
    return items or list(DEFAULT_ALERT_FIRSTNAMES)


async def notify_hot_lead_team(
    db: AsyncSession,
    *,
    lead: ProspectionLead,
    triggered_by_user_id: Optional[int] = None,
) -> int:
    """Crée une notification cloche pour chaque membre de l'équipe
    HOT_LEAD configurée. Retourne le nombre de notifs créées."""
    firstnames = _alert_firstnames()
    if not firstnames:
        return 0

    # Match insensible à la casse sur first_name. On exclut la
    # personne qui vient de bouger le lead (pas la peine qu'elle
    # se notifie elle-même).
    stmt = select(User).where(
        User.is_active.is_(True),
        func.lower(User.first_name).in_(firstnames),
    )
    users = (await db.execute(stmt)).scalars().all()

    addr = (lead.address or "").strip() or "(adresse manquante)"
    title = f"🔥 Hot Lead — {lead.name or addr}"
    body_parts = [addr]
    if lead.score:
        body_parts.append(f"Score Horizon : {lead.score}")
    body = " · ".join(body_parts)
    href = f"/prospection/{lead.id}"

    count = 0
    for u in users:
        if triggered_by_user_id is not None and u.id == triggered_by_user_id:
            continue
        await notify(
            db,
            user_id=u.id,
            kind="prospection.hot_lead",
            title=title,
            body=body,
            href=href,
        )
        count += 1
    log.info(
        "Hot lead %s → %d notification(s) créées pour %s",
        lead.id,
        count,
        firstnames,
    )
    return count
