"""Activité du compte (lecture seule, auth par clé d'API).

  GET /api/v1/activity/me?date=YYYY-MM-DD
  GET /api/v1/activity/me?from=YYYY-MM-DD&to=YYYY-MM-DD
  GET /api/v1/activity/me/summary?date=...

Retourne l'activité de l'utilisateur PROPRIÉTAIRE DE LA CLÉ sur une
période (par défaut : aujourd'hui, fuseau America/Toronto). Scope strict :
on ne voit jamais l'activité d'un autre utilisateur.

Agrégé :
  - tasks  : tâches complétées / créées / modifiées sur tous les pôles
             (devlog, entreprise, prospection, sales, project), filtrées
             sur celles assignées à OU créées par l'utilisateur.
  - audit  : entrées du journal d'audit où user_id = l'utilisateur.
  - summary: résumé en langage naturel (français) prêt à lire pour un
             assistant.

LECTURE SEULE : aucun écriture business ici (la clé d'API ne donne accès
qu'à ces endpoints).
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, time, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.api_key_deps import ApiKeyUser
from app.api.deps import DBSession
from app.models.audit_log import AuditLog
from app.models.devlog_project_task import DevlogProjectTask
from app.models.employe import Employe
from app.models.entreprise_tache import EntrepriseTache
from app.models.project_task import ProjectTask
from app.models.prospection_deal_task import ProspectionDealTask
from app.models.sales_task import SalesTask, sales_task_assignees
from app.models.user import User


TORONTO = ZoneInfo("America/Toronto")


router = APIRouter(prefix="/activity", tags=["activity"])


# ── Schémas ────────────────────────────────────────────────────────


class TaskActivity(BaseModel):
    pole: str                       # devlog / entreprise / prospection / sales / project
    entity_type: str                # type logique (pour reconstruire un lien)
    entity_id: int                  # id de la tâche
    title: str
    status: str                     # statut brut du pôle
    is_completed: bool
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Pourquoi la tâche apparaît dans la période : completed / created / updated.
    reasons: List[str]


class AuditActivity(BaseModel):
    id: int
    action: str
    entity_type: Optional[str]
    entity_id: Optional[int]
    timestamp: datetime
    summary: str


class ActivityResponse(BaseModel):
    user_id: int
    user_email: str
    timezone: str
    period_start: datetime
    period_end: datetime
    tasks: List[TaskActivity]
    audit: List[AuditActivity]
    summary: str


class SummaryResponse(BaseModel):
    user_id: int
    period_start: datetime
    period_end: datetime
    summary: str


# ── Fenêtre temporelle (America/Toronto) ───────────────────────────


def _resolve_window(
    date: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> tuple[datetime, datetime]:
    """Retourne (start, end) en datetimes timezone-aware America/Toronto.

    - Si from/to fournis : du minuit de `from` au minuit (exclu) du
      lendemain de `to`.
    - Sinon `date` (ou aujourd'hui) : journée minuit→minuit (exclu).
    """
    def _parse(d: str) -> date_cls:
        try:
            return date_cls.fromisoformat(d)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Date invalide : « {d} » (format attendu YYYY-MM-DD).",
            )

    if date_from or date_to:
        start_day = _parse(date_from) if date_from else _parse(date_to)
        end_day = _parse(date_to) if date_to else _parse(date_from)
        if end_day < start_day:
            start_day, end_day = end_day, start_day
    else:
        target = _parse(date) if date else datetime.now(TORONTO).date()
        start_day = target
        end_day = target

    start = datetime.combine(start_day, time.min, tzinfo=TORONTO)
    # Fin exclusive = minuit du lendemain du dernier jour.
    end = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=TORONTO)
    return start, end


def _in_window(dt: Optional[datetime], start: datetime, end: datetime) -> bool:
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TORONTO)
    return start <= dt < end


# ── Collecte des tâches par pôle ───────────────────────────────────


async def _employe_ids_for_user(db, user: User) -> List[int]:
    """Les pôles `sales` et `project` assignent via `employe_id`, pas via
    user_id. On relie l'utilisateur à ses fiches Employe par courriel."""
    if not user.email:
        return []
    stmt = select(Employe.id).where(Employe.email.ilike(user.email))
    return [row for row in (await db.execute(stmt)).scalars().all()]


def _reasons(
    is_completed: bool,
    completed_at: Optional[datetime],
    created_at: Optional[datetime],
    updated_at: Optional[datetime],
    start: datetime,
    end: datetime,
) -> List[str]:
    reasons: List[str] = []
    if is_completed and _in_window(completed_at, start, end):
        reasons.append("completed")
    if _in_window(created_at, start, end):
        reasons.append("created")
    if _in_window(updated_at, start, end) and "created" not in reasons:
        reasons.append("updated")
    return reasons


async def _collect_tasks(
    db, user: User, start: datetime, end: datetime
) -> List[TaskActivity]:
    out: List[TaskActivity] = []
    employe_ids = await _employe_ids_for_user(db, user)

    # ── Devlog (assignee_user_id ; status « termine » ; pas de
    #    completed_at → on prend updated_at comme proxy de complétion). ──
    rows = (
        await db.execute(
            select(DevlogProjectTask).where(
                DevlogProjectTask.assignee_user_id == user.id
            )
        )
    ).scalars().all()
    for t in rows:
        is_done = t.status == "termine"
        completed_at = t.updated_at if is_done else None
        reasons = _reasons(
            is_done, completed_at, t.created_at, t.updated_at, start, end
        )
        if reasons:
            out.append(
                TaskActivity(
                    pole="devlog",
                    entity_type="devlog_project_task",
                    entity_id=t.id,
                    title=t.title,
                    status=t.status,
                    is_completed=is_done,
                    completed_at=completed_at,
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                    reasons=reasons,
                )
            )

    # ── Entreprise (assignee_user_id ; status « done » ; completed_at). ──
    rows = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.assignee_user_id == user.id
            )
        )
    ).scalars().all()
    for t in rows:
        is_done = t.status == "done"
        completed_at = t.completed_at or (t.updated_at if is_done else None)
        reasons = _reasons(
            is_done, completed_at, t.created_at, t.updated_at, start, end
        )
        if reasons:
            out.append(
                TaskActivity(
                    pole="entreprise",
                    entity_type="entreprise_tache",
                    entity_id=t.id,
                    title=t.title,
                    status=t.status,
                    is_completed=is_done,
                    completed_at=completed_at,
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                    reasons=reasons,
                )
            )

    # ── Prospection (assignee_user_id ; status « done » ; pas de
    #    completed_at → updated_at comme proxy). ──
    rows = (
        await db.execute(
            select(ProspectionDealTask).where(
                ProspectionDealTask.assignee_user_id == user.id
            )
        )
    ).scalars().all()
    for t in rows:
        is_done = t.status == "done"
        completed_at = t.updated_at if is_done else None
        reasons = _reasons(
            is_done, completed_at, t.created_at, t.updated_at, start, end
        )
        if reasons:
            out.append(
                TaskActivity(
                    pole="prospection",
                    entity_type="prospection_deal_task",
                    entity_id=t.id,
                    title=t.name,
                    status=t.status,
                    is_completed=is_done,
                    completed_at=completed_at,
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                    reasons=reasons,
                )
            )

    # ── Sales (assignation via employes ; done/done_at). ──
    if employe_ids:
        rows = (
            await db.execute(
                select(SalesTask)
                .join(
                    sales_task_assignees,
                    sales_task_assignees.c.task_id == SalesTask.id,
                )
                .where(
                    sales_task_assignees.c.employe_id.in_(employe_ids)
                )
                .distinct()
            )
        ).scalars().all()
        for t in rows:
            completed_at = t.done_at or (t.updated_at if t.done else None)
            reasons = _reasons(
                t.done, completed_at, t.created_at, t.updated_at, start, end
            )
            if reasons:
                out.append(
                    TaskActivity(
                        pole="sales",
                        entity_type="sales_task",
                        entity_id=t.id,
                        title=t.title,
                        status="done" if t.done else "open",
                        is_completed=t.done,
                        completed_at=completed_at,
                        created_at=t.created_at,
                        updated_at=t.updated_at,
                        reasons=reasons,
                    )
                )

        # ── Project (assignee_id via employes ; done/done_at). ──
        rows = (
            await db.execute(
                select(ProjectTask).where(
                    ProjectTask.assignee_id.in_(employe_ids)
                )
            )
        ).scalars().all()
        for t in rows:
            completed_at = t.done_at or (t.updated_at if t.done else None)
            reasons = _reasons(
                t.done, completed_at, t.created_at, t.updated_at, start, end
            )
            if reasons:
                out.append(
                    TaskActivity(
                        pole="project",
                        entity_type="project_task",
                        entity_id=t.id,
                        title=t.title,
                        status="done" if t.done else "open",
                        is_completed=t.done,
                        completed_at=completed_at,
                        created_at=t.created_at,
                        updated_at=t.updated_at,
                        reasons=reasons,
                    )
                )

    # Tri : les plus récents d'abord (par date d'événement la plus parlante).
    def _sort_key(ta: TaskActivity) -> datetime:
        return ta.completed_at or ta.updated_at or ta.created_at or start

    out.sort(key=_sort_key, reverse=True)
    return out


# ── Collecte de l'audit ────────────────────────────────────────────


def _humanize_audit(entry: AuditLog) -> str:
    """Résumé lisible d'une entrée d'audit (français), best-effort."""
    label_map = {
        "soumission.sent": "Soumission envoyée",
        "soumission.created": "Soumission créée",
        "facture.sent": "Facture envoyée",
        "facture.created": "Facture créée",
        "facture.paid": "Facture payée",
        "client.deleted": "Client supprimé",
        "api_key.created": "Clé d'API créée",
        "api_key.revoked": "Clé d'API révoquée",
    }
    base = label_map.get(entry.action)
    if base is None:
        # Repli générique « entité.verbe » → « Verbe sur entité #id ».
        base = entry.action.replace(".", " ").replace("_", " ").capitalize()
    if entry.entity_type and entry.entity_id is not None:
        return f"{base} ({entry.entity_type} #{entry.entity_id})"
    return base


async def _collect_audit(
    db, user: User, start: datetime, end: datetime
) -> List[AuditActivity]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.user_id == user.id,
            AuditLog.created_at >= start,
            AuditLog.created_at < end,
        )
        .order_by(AuditLog.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        AuditActivity(
            id=e.id,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            timestamp=e.created_at,
            summary=_humanize_audit(e),
        )
        for e in rows
    ]


# ── Résumé en langage naturel ──────────────────────────────────────

_POLE_LABELS = {
    "devlog": "devlog",
    "entreprise": "entreprise",
    "prospection": "prospection",
    "sales": "ventes",
    "project": "chantier",
}


def _build_summary(
    tasks: List[TaskActivity],
    audit: List[AuditActivity],
    start: datetime,
    end: datetime,
    single_day: bool,
) -> str:
    if single_day:
        prefix = f"Le {start.date().isoformat()}"
    else:
        last_day = (end - timedelta(days=1)).date().isoformat()
        prefix = f"Du {start.date().isoformat()} au {last_day}"

    if not tasks and not audit:
        return f"{prefix} : aucune activité enregistrée."

    parts: List[str] = []

    # Tâches complétées, par pôle.
    completed = [t for t in tasks if "completed" in t.reasons]
    if completed:
        by_pole: dict[str, int] = {}
        for t in completed:
            by_pole[t.pole] = by_pole.get(t.pole, 0) + 1
        detail = ", ".join(
            f"{n} {_POLE_LABELS.get(p, p)}" for p, n in by_pole.items()
        )
        n = len(completed)
        word = "tâche complétée" if n == 1 else "tâches complétées"
        parts.append(f"{n} {word} ({detail})")

    created = [t for t in tasks if "created" in t.reasons]
    if created:
        n = len(created)
        word = "tâche créée" if n == 1 else "tâches créées"
        parts.append(f"{n} {word}")

    updated = [
        t for t in tasks
        if "updated" in t.reasons
        and "completed" not in t.reasons
        and "created" not in t.reasons
    ]
    if updated:
        n = len(updated)
        word = "tâche modifiée" if n == 1 else "tâches modifiées"
        parts.append(f"{n} {word}")

    # Audit : on met en avant quelques actions parlantes.
    audit_counts: dict[str, int] = {}
    for a in audit:
        audit_counts[a.action] = audit_counts.get(a.action, 0) + 1
    audit_phrases = {
        "soumission.sent": ("soumission envoyée", "soumissions envoyées"),
        "facture.sent": ("facture envoyée", "factures envoyées"),
        "facture.created": ("facture créée", "factures créées"),
        "facture.paid": ("facture payée", "factures payées"),
    }
    for action, (singular, plural) in audit_phrases.items():
        c = audit_counts.get(action, 0)
        if c:
            parts.append(f"{c} {singular if c == 1 else plural}")

    if not parts:
        # Activité présente mais sans catégorie « vedette » (ex. audit
        # divers uniquement).
        n = len(audit)
        word = "action enregistrée" if n == 1 else "actions enregistrées"
        parts.append(f"{n} {word} au journal d'audit")

    return f"{prefix} : " + ", ".join(parts) + "."


# ── Endpoints ──────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=ActivityResponse,
    summary="Activité de mon compte (clé d'API, lecture seule)",
)
async def my_activity(
    user: ApiKeyUser,
    db: DBSession,
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD (défaut: aujourd'hui)"),
    date_from: Optional[str] = Query(default=None, alias="from"),
    date_to: Optional[str] = Query(default=None, alias="to"),
) -> ActivityResponse:
    start, end = _resolve_window(date, date_from, date_to)
    single_day = (end - start) <= timedelta(days=1)

    tasks = await _collect_tasks(db, user, start, end)
    audit = await _collect_audit(db, user, start, end)
    summary = _build_summary(tasks, audit, start, end, single_day)

    return ActivityResponse(
        user_id=user.id,
        user_email=user.email,
        timezone="America/Toronto",
        period_start=start,
        period_end=end,
        tasks=tasks,
        audit=audit,
        summary=summary,
    )


@router.get(
    "/me/summary",
    response_model=SummaryResponse,
    summary="Résumé texte de mon activité (clé d'API, lecture seule)",
)
async def my_activity_summary(
    user: ApiKeyUser,
    db: DBSession,
    date: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, alias="from"),
    date_to: Optional[str] = Query(default=None, alias="to"),
) -> SummaryResponse:
    start, end = _resolve_window(date, date_from, date_to)
    single_day = (end - start) <= timedelta(days=1)

    tasks = await _collect_tasks(db, user, start, end)
    audit = await _collect_audit(db, user, start, end)
    summary = _build_summary(tasks, audit, start, end, single_day)

    return SummaryResponse(
        user_id=user.id,
        period_start=start,
        period_end=end,
        summary=summary,
    )
