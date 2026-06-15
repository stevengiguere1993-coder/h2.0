"""Moteur de relances (cadence) — exécuté par le cron horaire.

- Enrôle les nouveaux leads récents (ContactRequest non engagés) dans la
  séquence globale (CadenceStep).
- Fait avancer chaque plan à l'échéance : étape « courriel » → envoi
  AUTOMATIQUE du gabarit ; étape « appel »/« sms » → tâche + notification
  au staff.
- Arrête la cadence dès que le lead RÉPOND (communication entrante) ou
  est engagé/clos (statut won/lost/qualified/quoted/rdv_prevu/spam).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.cadence_step import CadenceStep
from app.models.contact_request import ContactRequest
from app.models.email_log import EmailLog
from app.models.email_template import EmailTemplate
from app.models.follow_up import FollowUp
from app.models.relance_plan import RelancePlan
from app.models.voice import Call, VoiceSms

log = logging.getLogger(__name__)

# Lead « engagé » / clos → on arrête la cadence.
_STOP_STATUSES = {"rdv_prevu", "qualified", "quoted", "won", "lost", "spam"}
# On n'enrôle que les leads récents pour éviter un afflux massif au 1er run.
_ENROLL_LOOKBACK_DAYS = 2


def _valid_external_email(email: str | None) -> bool:
    e = (email or "").strip().lower()
    if "@" not in e:
        return False
    if e.endswith("@telephonie.local") or e.endswith("@horizon.placeholder"):
        return False
    return True


async def _active_steps(db: AsyncSession) -> list[CadenceStep]:
    return list(
        (
            await db.execute(
                select(CadenceStep)
                .where(CadenceStep.active.is_(True))
                .order_by(CadenceStep.position.asc(), CadenceStep.id.asc())
            )
        )
        .scalars()
        .all()
    )


async def _lead_responded(
    db: AsyncSession, lead_id: int, since: datetime
) -> bool:
    em = (
        await db.execute(
            select(EmailLog.id)
            .where(
                EmailLog.entity_type == "contact_request",
                EmailLog.entity_id == lead_id,
                EmailLog.direction == "inbound",
                EmailLog.created_at >= since,
            )
            .limit(1)
        )
    ).first()
    if em:
        return True
    sms = (
        await db.execute(
            select(VoiceSms.id)
            .where(
                VoiceSms.entity_type == "contact_request",
                VoiceSms.entity_id == lead_id,
                VoiceSms.direction == "inbound",
                VoiceSms.received_at >= since,
            )
            .limit(1)
        )
    ).first()
    if sms:
        return True
    call = (
        await db.execute(
            select(Call.id)
            .where(
                Call.entity_type == "contact_request",
                Call.entity_id == lead_id,
                Call.direction == "inbound",
                Call.started_at >= since,
            )
            .limit(1)
        )
    ).first()
    return bool(call)


async def _send_cadence_email(
    db: AsyncSession, lead: ContactRequest, step: CadenceStep
) -> bool:
    if step.email_template_id is None:
        return False
    if not _valid_external_email(lead.email):
        return False
    tpl = (
        await db.execute(
            select(EmailTemplate).where(
                EmailTemplate.id == step.email_template_id
            )
        )
    ).scalar_one_or_none()
    if tpl is None:
        return False

    from app.api.v1.endpoints.email_templates import render_template
    from app.integrations.email_graph import get_mailer

    mailer = get_mailer()
    if not mailer.ready:
        return False
    name = (lead.name or "").strip()
    variables = {
        "nom": name,
        "prenom": name.split(" ")[0] if name else "",
        "adresse": lead.address or "",
        "horizon_url": settings.frontend_url,
        "horizon_phone": "",
    }
    subject = render_template(tpl.subject, variables)
    body_html = render_template(tpl.body_html, variables)
    try:
        await mailer.send(
            to=[lead.email],
            subject=subject,
            html_body=body_html,
            reply_to=mailer.sender,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("relance email failed for lead %s: %s", lead.id, exc)
        return False
    now = datetime.now(timezone.utc)
    db.add(
        EmailLog(
            direction="outbound",
            status="sent",
            from_email=mailer.sender,
            to_email=lead.email,
            subject=subject,
            body_preview=(body_html or "")[:2000],
            entity_type="contact_request",
            entity_id=lead.id,
            sent_at=now,
        )
    )
    db.add(
        FollowUp(
            subject_type="prospect",
            subject_id=lead.id,
            kind="email",
            direction="outbound",
            outcome="sent",
            notes=f"[relance auto] {step.label}",
            performed_at=now,
        )
    )
    return True


async def _run_cadence(db: AsyncSession) -> dict:
    from app.services.notifications import notify_role

    now = datetime.now(timezone.utc)
    steps = await _active_steps(db)
    if not steps:
        return {"skipped": "no_active_steps"}

    stats = {
        "enrolled": 0,
        "advanced": 0,
        "emails_sent": 0,
        "tasks": 0,
        "stopped": 0,
        "done": 0,
    }

    # 1) Enrôlement des nouveaux leads récents.
    enrolled_ids = {
        r[0]
        for r in (
            await db.execute(select(RelancePlan.contact_request_id))
        ).all()
    }
    cutoff = now - timedelta(days=_ENROLL_LOOKBACK_DAYS)
    new_leads = (
        await db.execute(
            select(ContactRequest)
            .where(
                ContactRequest.status.in_(["new", "contacted"]),
                ContactRequest.created_at >= cutoff,
            )
            .limit(500)
        )
    ).scalars().all()
    for lead in new_leads:
        if lead.id in enrolled_ids:
            continue
        base = lead.created_at or now
        db.add(
            RelancePlan(
                contact_request_id=lead.id,
                step_index=0,
                next_at=base + timedelta(days=steps[0].delay_days),
                status="active",
            )
        )
        stats["enrolled"] += 1
    await db.flush()

    # 2) Traitement des plans actifs.
    plans = (
        await db.execute(
            select(RelancePlan)
            .where(RelancePlan.status == "active")
            .limit(1000)
        )
    ).scalars().all()
    for plan in plans:
        lead = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == plan.contact_request_id
                )
            )
        ).scalar_one_or_none()
        if lead is None:
            plan.status = "stopped"
            continue
        if lead.status in _STOP_STATUSES:
            plan.status = "stopped"
            stats["stopped"] += 1
            continue
        if await _lead_responded(db, lead.id, plan.created_at):
            plan.status = "stopped"
            stats["stopped"] += 1
            continue
        if plan.next_at is None or plan.next_at > now:
            continue
        if plan.step_index >= len(steps):
            plan.status = "done"
            stats["done"] += 1
            continue

        step = steps[plan.step_index]
        if step.channel == "email":
            if await _send_cadence_email(db, lead, step):
                stats["emails_sent"] += 1
        else:
            db.add(
                FollowUp(
                    subject_type="prospect",
                    subject_id=lead.id,
                    kind=step.channel,
                    direction="outbound",
                    outcome="scheduled",
                    notes=f"[relance auto] {step.label}",
                    next_action_at=now,
                    next_action_label=step.label,
                    overdue_notified=True,
                    performed_at=now,
                )
            )
            stats["tasks"] += 1
            try:
                await notify_role(
                    db,
                    min_role="manager",
                    kind="relance.todo",
                    title=f"Relance à faire — {lead.name}",
                    body=(
                        f"{step.label} "
                        f"({'appel' if step.channel == 'call' else 'SMS'})"
                    ),
                    href=f"/app/crm/{lead.id}",
                )
            except Exception:  # noqa: BLE001
                pass

        # Avancement vers l'étape suivante (ou fin de cadence).
        nxt = plan.step_index + 1
        if nxt < len(steps):
            plan.step_index = nxt
            plan.next_at = now + timedelta(days=steps[nxt].delay_days)
            stats["advanced"] += 1
        else:
            plan.status = "done"
            stats["done"] += 1

    await db.flush()
    return stats


async def run_relance_cadence() -> dict:
    """Point d'entrée cron : session + commit propres. Respecte le flag
    d'automatisation `construction_relances` (activé par défaut)."""
    from app.services.automation_state import is_automation_enabled

    if not await is_automation_enabled("construction_relances"):
        return {"skipped": "disabled"}
    async with AsyncSessionLocal() as db:
        try:
            stats = await _run_cadence(db)
            await db.commit()
            return stats
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.warning("relance cadence run failed: %s", exc)
            return {"error": str(exc)}
