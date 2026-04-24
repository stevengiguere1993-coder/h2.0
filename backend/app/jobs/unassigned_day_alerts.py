"""Cron: pour chaque employé actif (hors rôle admin/owner), vérifie
qu'il a bien au moins UNE assignation prévue demain (jour ouvré). Si
rien n'est planifié ET qu'il n'est pas en congé approuvé pour ce
jour-là, on notifie les managers+ pour qu'ils réorganisent ou
réassignent ses tâches.

Jours ouvrés uniquement — on ignore samedi/dimanche. Idempotent:
une seule notification par (employé, date cible) grâce à une clé
`#emp-{id}-{YYYY-MM-DD}` embarquée dans le corps de la notif, vérifiée
avant l'insertion.

Usage (Render cron, idéalement la veille en fin de journée) :
    python -m app.jobs.unassigned_day_alerts
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import and_, or_, select

from app.db.session import AsyncSessionLocal
from app.models.agenda_event import AgendaEvent
from app.models.employe import Employe
from app.models.leave_request import LeaveRequest, LeaveStatus
from app.models.notification import Notification
from app.models.project_assignees import (
    ProjectPhaseAssignee,
    ProjectTaskAssignee,
)
from app.models.project_phase import ProjectPhase
from app.models.project_task import ProjectTask
from app.models.user import User
from app.services.notifications import notify_role


log = logging.getLogger(__name__)


def _next_business_day(ref: date) -> date:
    """Retourne le prochain jour ouvré (lun-ven). Si la référence est
    samedi ou dimanche, saute au lundi suivant."""
    nxt = ref + timedelta(days=1)
    while nxt.weekday() >= 5:  # 5 = samedi, 6 = dimanche
        nxt += timedelta(days=1)
    return nxt


async def _has_phase_on(db, employe_id: int, target: date) -> bool:
    """Une phase couvre target si [start_date, start_date + duration - 1]
    contient target ET que l'employé y est assigné (legacy OU join)."""
    legacy = (
        await db.execute(
            select(ProjectPhase.id).where(
                ProjectPhase.assignee_employe_id == employe_id,
                ProjectPhase.start_date.is_not(None),
                ProjectPhase.duration_days.is_not(None),
            )
        )
    ).all()
    joined = (
        await db.execute(
            select(ProjectPhase)
            .join(
                ProjectPhaseAssignee,
                ProjectPhaseAssignee.phase_id == ProjectPhase.id,
            )
            .where(ProjectPhaseAssignee.employe_id == employe_id)
        )
    ).scalars().all()
    # Fetch all assigned phases' dates + durations
    phase_ids = {int(r[0]) for r in legacy} | {p.id for p in joined}
    if not phase_ids:
        return False
    rows = (
        await db.execute(
            select(ProjectPhase).where(ProjectPhase.id.in_(phase_ids))
        )
    ).scalars().all()
    for ph in rows:
        if ph.start_date is None or ph.duration_days is None:
            continue
        end = ph.start_date + timedelta(days=max(0, ph.duration_days - 1))
        if ph.start_date <= target <= end:
            return True
    return False


async def _has_task_on(db, employe_id: int, target: date) -> bool:
    """Tâche ouverte due ce jour-là."""
    # Legacy assignee_id
    legacy = (
        await db.execute(
            select(ProjectTask.id).where(
                ProjectTask.assignee_id == employe_id,
                ProjectTask.done.is_(False),
                ProjectTask.due_date == target,
            )
        )
    ).all()
    if legacy:
        return True
    # Join table
    joined = (
        await db.execute(
            select(ProjectTask.id)
            .join(
                ProjectTaskAssignee,
                ProjectTaskAssignee.task_id == ProjectTask.id,
            )
            .where(
                ProjectTaskAssignee.employe_id == employe_id,
                ProjectTask.done.is_(False),
                ProjectTask.due_date == target,
            )
        )
    ).all()
    return bool(joined)


async def _has_event_on(db, employe_id: int, target: date) -> bool:
    """Événement agenda qui chevauche ce jour-là."""
    day_start = datetime.combine(target, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    day_end = day_start + timedelta(days=1)
    rows = (
        await db.execute(
            select(AgendaEvent.id).where(
                AgendaEvent.assignee_id == employe_id,
                AgendaEvent.start_at < day_end,
                or_(
                    AgendaEvent.end_at.is_(None),
                    AgendaEvent.end_at > day_start,
                ),
            )
        )
    ).all()
    return bool(rows)


async def _is_on_leave(db, employe_id: int, target: date) -> bool:
    """Approved leave that overlaps target (start_at.date() <= target <= end_at.date())."""
    day_start = datetime.combine(target, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    day_end = day_start + timedelta(days=1)
    rows = (
        await db.execute(
            select(LeaveRequest.id).where(
                LeaveRequest.employe_id == employe_id,
                LeaveRequest.status == LeaveStatus.APPROVED.value,
                LeaveRequest.start_at < day_end,
                LeaveRequest.end_at >= day_start,
            )
        )
    ).all()
    return bool(rows)


def _dedup_marker(employe_id: int, target: date) -> str:
    return f"#unassigned-{employe_id}-{target.isoformat()}"


async def _already_notified(db, marker: str) -> bool:
    row = (
        await db.execute(
            select(Notification.id).where(
                Notification.kind == "employe.unassigned",
                Notification.body.contains(marker),
            ).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


def _active_non_admin_employes(rows: Iterable[Employe]) -> list[Employe]:
    out: list[Employe] = []
    for e in rows:
        if not e.is_active:
            continue
        if e.email:
            # On veut garder les employés de terrain (role "employee").
            # Les admins/owners organisent, pas besoin de les alerter.
            # Le test se fait côté User : si un User existe avec ce mail
            # et un rôle admin+, on skip.
            pass
        out.append(e)
    return out


async def _run() -> None:
    async with AsyncSessionLocal() as db:
        today = datetime.now(timezone.utc).date()
        target = _next_business_day(today)

        employes_rows = (
            await db.execute(select(Employe).where(Employe.is_active.is_(True)))
        ).scalars().all()

        # Map email → user role pour filtrer les admin/owner.
        user_rows = (
            await db.execute(select(User))
        ).scalars().all()
        role_by_email = {
            (u.email or "").lower(): (u.role or "employee") for u in user_rows
        }

        to_check: list[Employe] = []
        for e in employes_rows:
            email = (e.email or "").lower()
            role = role_by_email.get(email, "employee")
            if role in ("admin", "owner"):
                continue
            to_check.append(e)

        alerted = 0
        for e in to_check:
            if await _is_on_leave(db, e.id, target):
                continue
            if await _has_phase_on(db, e.id, target):
                continue
            if await _has_task_on(db, e.id, target):
                continue
            if await _has_event_on(db, e.id, target):
                continue
            marker = _dedup_marker(e.id, target)
            if await _already_notified(db, marker):
                continue
            # Alerte — on notifie les managers+ pour qu'ils
            # réorganisent / réassignent.
            date_label = target.strftime("%A %d %B %Y")
            await notify_role(
                db,
                min_role="manager",
                kind="employe.unassigned",
                title=f"{e.full_name} sans assignation — {date_label}",
                body=(
                    f"{e.full_name} n'a aucune phase, tâche ou événement "
                    f"prévu pour le {date_label}, et n'est pas en congé. "
                    f"Pense à réorganiser ses assignations ou à les "
                    f"réaffecter. {marker}"
                ),
                href="/app/assignations",
            )
            alerted += 1

        await db.commit()
        log.info(
            "unassigned_day_alerts: %d/%d employés alertés pour %s",
            alerted,
            len(to_check),
            target.isoformat(),
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
