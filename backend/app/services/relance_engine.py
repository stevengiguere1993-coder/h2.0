"""Moteur de relances (cadence) — exécuté par le cron horaire.

À l'entrée en cadence, la séquence GLOBALE (CadenceStep) est copiée en
relances par lead (RelanceItem) avec des dates planifiées — chacune
modifiable ensuite sur la fiche prospect. Le moteur exécute à l'échéance :
étape « courriel » → envoi AUTOMATIQUE du gabarit ; étape « appel »/« sms »
→ tâche + notification. Il s'arrête (annule les relances restantes) dès
que le lead RÉPOND (communication entrante) ou est engagé/clos.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.cadence_step import CadenceStep
from app.models.contact_request import ContactRequest
from app.models.email_log import EmailLog
from app.models.email_template import EmailTemplate
from app.models.follow_up import FollowUp
from app.models.relance_item import RelanceItem
from app.models.voice import Call, VoiceSms

log = logging.getLogger(__name__)

_STOP_STATUSES = {"rdv_prevu", "qualified", "quoted", "won", "lost", "spam"}
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
    for stmt in (
        select(EmailLog.id).where(
            EmailLog.entity_type == "contact_request",
            EmailLog.entity_id == lead_id,
            EmailLog.direction == "inbound",
            EmailLog.created_at >= since,
        ),
        select(VoiceSms.id).where(
            VoiceSms.entity_type == "contact_request",
            VoiceSms.entity_id == lead_id,
            VoiceSms.direction == "inbound",
            VoiceSms.received_at >= since,
        ),
        select(Call.id).where(
            Call.entity_type == "contact_request",
            Call.entity_id == lead_id,
            Call.direction == "inbound",
            Call.started_at >= since,
        ),
    ):
        if (await db.execute(stmt.limit(1))).first():
            return True
    return False


async def _send_cadence_email(
    db: AsyncSession, lead: ContactRequest, item: RelanceItem
) -> bool:
    if item.email_template_id is None:
        return False
    if not _valid_external_email(lead.email):
        return False
    tpl = (
        await db.execute(
            select(EmailTemplate).where(
                EmailTemplate.id == item.email_template_id
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
            notes=f"[relance auto] {item.label}",
            performed_at=now,
        )
    )
    return True


async def _enroll_new_leads(
    db: AsyncSession, steps: list[CadenceStep], now: datetime
) -> int:
    enrolled_ids = {
        r[0]
        for r in (
            await db.execute(select(RelanceItem.contact_request_id).distinct())
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
    count = 0
    for lead in new_leads:
        if lead.id in enrolled_ids:
            continue
        acc = lead.created_at or now
        for pos, s in enumerate(steps):
            acc = acc + timedelta(days=s.delay_days)
            db.add(
                RelanceItem(
                    contact_request_id=lead.id,
                    position=pos,
                    channel=s.channel,
                    label=s.label,
                    email_template_id=s.email_template_id,
                    scheduled_at=acc,
                    status="pending",
                )
            )
        count += 1
    await db.flush()
    return count


async def _run_cadence(db: AsyncSession) -> dict:
    from app.services.notifications import notify_role

    now = datetime.now(timezone.utc)
    steps = await _active_steps(db)
    if not steps:
        return {"skipped": "no_active_steps"}

    stats = {
        "enrolled": 0,
        "emails_sent": 0,
        "tasks": 0,
        "stopped": 0,
        "skipped": 0,
    }
    stats["enrolled"] = await _enroll_new_leads(db, steps, now)

    # Relances dues, triées par contact puis échéance ; on n'exécute
    # qu'UNE relance par contact et par passage (espacement naturel).
    due = (
        await db.execute(
            select(RelanceItem)
            .where(
                RelanceItem.status == "pending",
                RelanceItem.scheduled_at <= now,
            )
            .order_by(
                RelanceItem.contact_request_id.asc(),
                RelanceItem.scheduled_at.asc(),
                RelanceItem.position.asc(),
            )
            .limit(2000)
        )
    ).scalars().all()

    processed: set[int] = set()
    for item in due:
        cid = item.contact_request_id
        if cid in processed:
            continue
        lead = (
            await db.execute(
                select(ContactRequest).where(ContactRequest.id == cid)
            )
        ).scalar_one_or_none()
        if lead is None:
            item.status = "cancelled"
            continue
        # Arrêt : lead engagé/clos OU il a répondu depuis l'enrôlement.
        if lead.status in _STOP_STATUSES or await _lead_responded(
            db, cid, item.created_at
        ):
            await db.execute(
                update(RelanceItem)
                .where(
                    RelanceItem.contact_request_id == cid,
                    RelanceItem.status == "pending",
                )
                .values(status="cancelled")
            )
            processed.add(cid)
            stats["stopped"] += 1
            continue
        # Exécution de la relance due.
        if item.channel == "email":
            if await _send_cadence_email(db, lead, item):
                item.status = "sent"
                stats["emails_sent"] += 1
            else:
                # Pas de gabarit / adresse invalide → on saute pour ne
                # pas bloquer la suite de la séquence.
                item.status = "skipped"
                stats["skipped"] += 1
        else:
            db.add(
                FollowUp(
                    subject_type="prospect",
                    subject_id=lead.id,
                    kind=item.channel,
                    direction="outbound",
                    outcome="scheduled",
                    notes=f"[relance auto] {item.label}",
                    next_action_at=now,
                    next_action_label=item.label,
                    overdue_notified=True,
                    performed_at=now,
                )
            )
            item.status = "done"
            stats["tasks"] += 1
            try:
                await notify_role(
                    db,
                    min_role="manager",
                    kind="relance.todo",
                    title=f"Relance à faire — {lead.name}",
                    body=(
                        f"{item.label} "
                        f"({'appel' if item.channel == 'call' else 'SMS'})"
                    ),
                    href=f"/app/crm/{lead.id}",
                )
            except Exception:  # noqa: BLE001
                pass
        processed.add(cid)

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
