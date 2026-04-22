"""Cron: parcourt les follow-ups dont next_action_at est dépassé et
crée une notification cloche pour les rappeler aux managers+ (et au
performed_by_user_id si défini). Marqué overdue_notified=True pour
éviter de spammer la cloche à chaque exécution.

Usage (Render cron, idéalement aux heures pleines) :
    python -m app.jobs.follow_up_reminders
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.contact_request import ContactRequest
from app.models.follow_up import FollowUp
from app.models.soumission import Soumission
from app.services.notifications import notify, notify_role


log = logging.getLogger(__name__)


STOP = ("won", "lost", "not_interested")


async def _run() -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)

        # 1) Notifs « suivi en retard » — un par follow-up, une seule fois.
        rows = (
            await db.execute(
                select(FollowUp)
                .where(
                    FollowUp.next_action_at.is_not(None),
                    FollowUp.next_action_at <= now,
                    FollowUp.outcome.notin_(STOP),
                    FollowUp.overdue_notified.is_(False),
                )
                .limit(500)
            )
        ).scalars().all()

        for f in rows:
            href = (
                f"/app/crm/{f.subject_id}"
                if f.subject_type == "prospect"
                else f"/app/soumissions/{f.subject_id}"
            )
            label = f.next_action_label or "Suivi"
            title = f"⏰ Suivi en retard : {label}"
            body = (
                f"{f.subject_type.capitalize()} #{f.subject_id} — "
                f"prévue le {f.next_action_at.strftime('%Y-%m-%d %H:%M')}."
            )
            try:
                if f.performed_by_user_id:
                    await notify(
                        db,
                        user_id=f.performed_by_user_id,
                        kind="followup.overdue",
                        title=title,
                        body=body,
                        href=href,
                    )
                else:
                    await notify_role(
                        db,
                        min_role="manager",
                        kind="followup.overdue",
                        title=title,
                        body=body,
                        href=href,
                    )
                f.overdue_notified = True
            except Exception as exc:
                log.warning("notif overdue %s failed: %s", f.id, exc)

        # 2) Lead créé > 24 h sans aucun follow-up de type call/email/visite
        # logué (auto-scheduled ne compte pas) → notif rouge aux managers+
        cutoff = now - timedelta(hours=24)
        prospects = (
            await db.execute(
                select(ContactRequest)
                .where(ContactRequest.created_at <= cutoff)
                .limit(200)
            )
        ).scalars().all()

        for p in prospects:
            # A-t-il déjà reçu un appel/courriel/visite manuel ?
            has_real = (
                await db.execute(
                    select(FollowUp.id).where(
                        FollowUp.subject_type == "prospect",
                        FollowUp.subject_id == p.id,
                        FollowUp.kind.in_(("call", "email", "sms", "visite")),
                    ).limit(1)
                )
            ).first() is not None
            if has_real:
                continue
            # Existe-t-il une notif déjà émise (pour pas spammer) ?
            already = (
                await db.execute(
                    select(FollowUp.id).where(
                        FollowUp.subject_type == "prospect",
                        FollowUp.subject_id == p.id,
                        FollowUp.kind == "auto",
                        FollowUp.overdue_notified.is_(True),
                    ).limit(1)
                )
            ).first() is not None
            if already:
                continue
            try:
                await notify_role(
                    db,
                    min_role="manager",
                    kind="lead.uncalled_24h",
                    title=f"⚠️ Prospect non rappelé : {p.name}",
                    body=(
                        f"Aucun appel, courriel ou visite logué depuis "
                        f"sa création ({p.created_at.strftime('%Y-%m-%d')})."
                    ),
                    href=f"/app/crm/{p.id}",
                )
                # Marque le 1er auto-followup comme notifié pour
                # éviter de re-notifier à la prochaine itération.
                first_auto = (
                    await db.execute(
                        select(FollowUp)
                        .where(
                            FollowUp.subject_type == "prospect",
                            FollowUp.subject_id == p.id,
                            FollowUp.kind == "auto",
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if first_auto:
                    first_auto.overdue_notified = True
            except Exception as exc:
                log.warning("notif lead %s failed: %s", p.id, exc)

        await db.commit()
        log.info(
            "follow-up reminders: %d overdue, %d prospects scanned",
            len(rows),
            len(prospects),
        )

        # Touch the soumissions table so the linter doesn't complain
        # (will use later for soumission-specific logic).
        _ = Soumission


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())
