"""Relève des courriels entrants (réponses des clients) et rattachement
à la bonne fiche CRM, pour les afficher dans l'onglet Communications.

Nécessite la permission Graph **Mail.Read** sur la boîte. Best-effort :
si la permission manque, `list_inbox_messages` renvoie une liste vide et
le job ne fait rien.

Rapprochement : l'adresse de l'expéditeur est cherchée parmi les clients,
prospects (contact_requests) et locataires. Déduplication par
`provider_message_id` (id Graph du message).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import get_mailer
from app.models.email_log import EmailLog

log = logging.getLogger(__name__)


async def _match_entity(
    db: AsyncSession, email: str
) -> tuple[Optional[str], Optional[int]]:
    e = (email or "").strip().lower()
    if not e:
        return None, None

    from app.models.client import Client

    row = (
        await db.execute(
            select(Client.id).where(func.lower(Client.email) == e).limit(1)
        )
    ).scalar_one_or_none()
    if row:
        return "client", row

    from app.models.contact_request import ContactRequest

    row = (
        await db.execute(
            select(ContactRequest.id)
            .where(func.lower(ContactRequest.email) == e)
            .order_by(ContactRequest.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row:
        return "contact_request", row

    from app.models.immobilier import Locataire

    row = (
        await db.execute(
            select(Locataire.id)
            .where(func.lower(Locataire.email) == e)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row:
        return "locataire", row

    return None, None


async def poll_inbound_emails(db: AsyncSession, *, top: int = 50) -> dict:
    """Relève la boîte, logge les réponses rattachables à une fiche."""
    mailer = get_mailer()
    if not mailer.ready:
        return {"polled": 0, "logged": 0, "skipped": 0}

    msgs = await mailer.list_inbox_messages(top=top)
    logged = 0
    skipped = 0
    for m in msgs:
        mid = m.get("id")
        frm = m.get("from_email")
        if not mid or not frm:
            skipped += 1
            continue
        # Déjà logué ?
        exists = (
            await db.execute(
                select(EmailLog.id)
                .where(EmailLog.provider_message_id == mid)
                .limit(1)
            )
        ).scalar_one_or_none()
        if exists:
            skipped += 1
            continue
        # Notre propre adesse (échos) → on saute.
        if frm == (mailer.sender or "").strip().lower():
            skipped += 1
            continue
        etype, eid = await _match_entity(db, frm)
        if etype is None:
            # Expéditeur inconnu : pas de fiche → on ne logge pas.
            skipped += 1
            continue
        received_at = None
        recv = m.get("received_at")
        if recv:
            try:
                received_at = datetime.fromisoformat(
                    str(recv).replace("Z", "+00:00")
                )
            except Exception:
                received_at = None
        db.add(
            EmailLog(
                direction="inbound",
                status="received",
                from_email=frm,
                to_email=mailer.sender,
                subject=m.get("subject"),
                body_preview=(m.get("preview") or "")[:2000],
                entity_type=etype,
                entity_id=eid,
                provider_message_id=mid,
                thread_id=m.get("conversation_id"),
                received_at=received_at,
            )
        )
        logged += 1
    await db.flush()
    return {"polled": len(msgs), "logged": logged, "skipped": skipped}
