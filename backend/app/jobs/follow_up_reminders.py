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
    from app.services.automation_state import is_automation_enabled
    if not await is_automation_enabled("follow_up_reminders"):
        return
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

        # 2) SLA : lead créé depuis +X h (settings.sla_first_contact_hours,
        # défaut 4 h) sans aucun follow-up de type call/email/visite
        # logué (auto-scheduled ne compte pas) → notif rouge aux
        # managers+ ET au prospecteur assigné si présent.
        from app.core.config import settings as _sla_settings
        sla_hours = max(1, int(getattr(_sla_settings, "sla_first_contact_hours", 4)))
        cutoff = now - timedelta(hours=sla_hours)
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
            # 1er verrou : le follow-up 'auto' marqué overdue_notified.
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
            # 2e verrou (anti-spam horaire) : cherche directement une
            # Notification déjà émise pour ce lead. Les leads Meta/voice/
            # webhooks n'ont AUCUN follow-up 'auto', donc le marqueur
            # overdue_notified ci-dessus n'est jamais posé pour eux → sans
            # ce garde, la cloche re-sonnerait à chaque run horaire. On
            # calque le pattern de dédup de la Section 4 (rdv.confirm).
            from app.models.notification import Notification as _Notif

            notif_exists = (
                await db.execute(
                    select(_Notif.id).where(
                        _Notif.kind == "lead.uncalled_24h",
                        _Notif.href == f"/app/crm/{p.id}",
                    ).limit(1)
                )
            ).first() is not None
            if notif_exists:
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

        # 3) Backfill : demandes de congé en attente qui n'ont pas de
        # notification cloche associée (cas d'une demande créée avant
        # l'activation du hook ou en cas d'échec du notify_role en
        # ligne). Une seule notif par LeaveRequest.
        from app.models.leave_request import LeaveRequest, LeaveStatus
        from app.models.notification import Notification
        from app.services.notifications import notify_role

        pending_leaves = (
            await db.execute(
                select(LeaveRequest).where(
                    LeaveRequest.status == LeaveStatus.PENDING.value
                ).limit(200)
            )
        ).scalars().all()
        leave_notified = 0
        for lr in pending_leaves:
            already = (
                await db.execute(
                    select(Notification.id).where(
                        Notification.kind == "leave.requested",
                        Notification.href.like(f"%/app/conges%"),
                        Notification.body.like(f"%#{lr.id}%"),
                    ).limit(1)
                )
            ).first() is not None
            if already:
                continue
            # Look up employee name
            from app.models.employe import Employe

            emp = (
                await db.execute(
                    select(Employe).where(Employe.id == lr.employe_id)
                )
            ).scalar_one_or_none()
            name = emp.full_name if emp else f"Employé #{lr.employe_id}"
            kind_label = {
                "vacation": "🌴 Vacances",
                "sick": "🤒 Maladie",
                "personal": "📋 Absence",
            }.get(lr.kind or "vacation", "Congé")
            try:
                await notify_role(
                    db,
                    min_role="manager",
                    kind="leave.requested",
                    title=f"Demande de congé : {name}",
                    body=(
                        f"{kind_label} · "
                        f"{lr.start_at.strftime('%Y-%m-%d')}"
                        + (
                            f" → {lr.end_at.strftime('%Y-%m-%d')}"
                            if lr.start_at.date() != lr.end_at.date()
                            else ""
                        )
                        + f" (ref #{lr.id})"
                    ),
                    href="/app/conges",
                )
                leave_notified += 1
            except Exception as exc:
                log.warning("notif leave %s failed: %s", lr.id, exc)

        # 4) Confirmation au responsable ~48 h avant un RDV prospect.
        # Remplace l'ancienne relance « en retard » : on prévient le
        # responsable du client pour qu'il confirme le rendez-vous.
        from zoneinfo import ZoneInfo

        from app.models.agenda_event import AgendaEvent

        confirm_window = now + timedelta(hours=48)
        upcoming = (
            await db.execute(
                select(AgendaEvent)
                .where(
                    AgendaEvent.contact_request_id.is_not(None),
                    AgendaEvent.start_at >= now,
                    AgendaEvent.start_at <= confirm_window,
                )
                .limit(200)
            )
        ).scalars().all()
        rdv_notified = 0
        for ev in upcoming:
            href = f"/app/crm/{ev.contact_request_id}?rdv={ev.id}"
            # Dédup : une seule notif de confirmation par RDV.
            already = (
                await db.execute(
                    select(Notification.id).where(
                        Notification.kind == "rdv.confirm",
                        Notification.href == href,
                    ).limit(1)
                )
            ).first() is not None
            if already:
                continue
            pr = (
                await db.execute(
                    select(ContactRequest).where(
                        ContactRequest.id == ev.contact_request_id
                    )
                )
            ).scalar_one_or_none()
            if pr is None:
                continue
            try:
                local = ev.start_at.astimezone(ZoneInfo("America/Toronto"))
            except Exception:
                local = ev.start_at
            title = f"📅 Confirmer le RDV : {pr.name}"
            body = (
                f"Rendez-vous le {local.strftime('%d/%m/%Y à %Hh%M')}. "
                "Confirme avec le client."
            )
            try:
                if pr.assigned_to_user_id:
                    await notify(
                        db,
                        user_id=pr.assigned_to_user_id,
                        kind="rdv.confirm",
                        title=title,
                        body=body,
                        href=href,
                    )
                else:
                    await notify_role(
                        db,
                        min_role="manager",
                        kind="rdv.confirm",
                        title=title,
                        body=body,
                        href=href,
                    )
                rdv_notified += 1
            except Exception as exc:
                log.warning("notif rdv confirm %s failed: %s", ev.id, exc)

        await db.commit()
        log.info(
            "follow-up reminders: %d overdue, %d prospects, %d leaves, "
            "%d RDV confirmations notified",
            len(rows),
            len(prospects),
            leave_notified,
            rdv_notified,
        )

        # Touch the soumissions table so the linter doesn't complain
        # (will use later for soumission-specific logic).
        _ = Soumission

    # Moteur de relances : enrôle les nouveaux leads, fait avancer la
    # cadence et envoie les courriels dus. Session + commit propres,
    # isolé pour ne pas faire échouer le reste du job.
    try:
        from app.services.relance_engine import run_relance_cadence

        stats = await run_relance_cadence()
        log.info("relance cadence: %s", stats)
    except Exception as exc:  # noqa: BLE001
        log.warning("relance cadence engine failed: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())
