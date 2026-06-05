"""Activité du compte (auth par clé d'API) + création de tâche par pôle.

  GET  /api/v1/activity/me?date=YYYY-MM-DD
  GET  /api/v1/activity/me?from=YYYY-MM-DD&to=YYYY-MM-DD
  GET  /api/v1/activity/me/summary?date=...
  POST /api/v1/activity/tasks            (écriture : créer une tâche d'un pôle)

LECTURE : retourne l'activité de l'utilisateur PROPRIÉTAIRE DE LA CLÉ sur
une période (par défaut : aujourd'hui, fuseau America/Toronto). Scope
strict : on ne voit jamais l'activité d'un autre utilisateur. L'activité
n'est renvoyée QUE pour les pôles dont la clé porte ``<pole>:activity:read``
(rétrocompat : clé sans scopes = tous les pôles).

ÉCRITURE : ``POST /activity/tasks`` crée une tâche dans un pôle donné, à
condition que la clé porte ``<pole>:tasks:create``. La tâche est créée
par / assignée à l'utilisateur de la clé. Audité (mention « via clé API »).

Agrégé en lecture :
  - tasks  : tâches complétées / créées / modifiées (pôles autorisés).
  - audit  : entrées du journal d'audit où user_id = l'utilisateur.
  - summary: résumé en langage naturel (français) prêt à lire.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, time, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.api_key_deps import ApiKeyContext
from app.api.deps import DBSession
from app.models.audit_log import AuditLog
from app.models.devlog_project_task import DevlogProjectTask
from app.models.devlog_project import DevlogProject
from app.models.employe import Employe
from app.models.entreprise import Entreprise, EntreprisePartner
from app.models.entreprise_tache import EntrepriseTache
from app.models.project import Project
from app.models.project_task import ProjectTask
from app.models.prospection_deal import ProspectionDeal
from app.models.prospection_deal_task import ProspectionDealTask
from app.models.sales_task import SalesTask, sales_task_assignees
from app.models.user import User
from app.services.api_capabilities import POLE_LABELS, readable_poles
from app.services.audit import log_action
from app.services.entity_serializers import serialize_entity

# Modèles supplémentaires chargés UNIQUEMENT pour la lecture détaillée
# (endpoints /activity/entities/...). Importés en tête : ces imports sont
# déjà tirés ailleurs dans l'app, donc sûrs au démarrage.
from app.models.devlog_soumission import DevlogSoumission
from app.models.devlog_soumission_module import DevlogSoumissionModule
from app.models.devlog_soumission_item import DevlogSoumissionItem
from app.models.devlog_client import DevlogClient
from app.models.devlog_lead import DevlogLead


TORONTO = ZoneInfo("America/Toronto")


router = APIRouter(prefix="/activity", tags=["activity"])


# Mapping « pôle interne du collecteur » → slug du catalogue de capacités.
# Les libellés internes (devlog/entreprise/prospection/sales/project) sont
# conservés dans la réponse pour ne rien casser, mais le FILTRAGE de
# lecture se fait sur les slugs du catalogue (prospection/devlog/
# construction/entreprise/...). Sales (CRM/prospects) → prospection ;
# Project (chantier) → construction.
_INTERNAL_POLE_TO_SLUG = {
    "devlog": "devlog",
    "entreprise": "entreprise",
    "prospection": "prospection",
    "sales": "prospection",
    "project": "construction",
}

# Préfixes d'audit (entity_type / action) → slug de pôle, pour filtrer le
# journal d'audit par pôle quand c'est possible.
_AUDIT_ENTITY_TO_SLUG = {
    "soumission": "devlog",
    "facture": "devlog",
    "devlog": "devlog",
    "entreprise": "entreprise",
    "prospection": "prospection",
    "deal": "prospection",
    "lead": "prospection",
    "client": "prospection",
    "project": "construction",
    "chantier": "construction",
    "achat": "comptabilite",
    "bon": "comptabilite",
    "fournisseur": "comptabilite",
    "immeuble": "immobilier",
    "imm": "immobilier",
    "bail": "immobilier",
}


def _audit_slug(entry: AuditLog) -> Optional[str]:
    """Devine le slug de pôle d'une entrée d'audit (best-effort), ou None
    si indéterminable. On regarde l'entity_type puis l'action."""
    haystacks = [entry.entity_type or "", entry.action or ""]
    for h in haystacks:
        low = h.lower()
        for key, slug in _AUDIT_ENTITY_TO_SLUG.items():
            if low.startswith(key) or f"{key}." in low or f"{key}_" in low:
                return slug
    return None


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
    # Objet métier enrichi (niveau « summary ») de la tâche : titre lisible,
    # statut, assigné, pôle, échéance… Ajouté SANS remplacer les champs
    # ci-dessus (rétrocompat consommateurs). Best-effort : None si la
    # sérialisation échoue. Voir app.services.entity_serializers.
    entity: Optional[dict] = None


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


class TaskCreate(BaseModel):
    """Création d'une tâche via clé d'API. ``pole`` détermine le modèle
    cible et l'identifiant parent requis."""

    pole: str = Field(..., description="Slug du pôle : prospection / devlog / construction / entreprise.")
    # Identifiant de l'entité parente, selon le pôle :
    #   devlog        → parent_id = devlog_projects.id
    #   entreprise    → parent_id = entreprises.id
    #   prospection   → parent_id = prospection_deals.id
    #   construction  → parent_id = projects.id
    parent_id: int = Field(..., description="ID de l'entité parente (projet / entreprise / deal selon le pôle).")
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    due_date: Optional[date_cls] = None


class TaskCreated(BaseModel):
    pole: str
    entity_type: str
    entity_id: int
    title: str
    status: str


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
    db,
    user: User,
    start: datetime,
    end: datetime,
    allowed_poles: Optional[set[str]] = None,
) -> List[TaskActivity]:
    """Collecte les tâches de l'utilisateur sur la période. Si
    ``allowed_poles`` est fourni (set de slugs du catalogue), on ne
    collecte QUE les modèles dont le slug est autorisé. None = tous
    (rétrocompat / usage interne sans filtrage)."""
    out: List[TaskActivity] = []
    employe_ids = await _employe_ids_for_user(db, user)

    def _allowed(internal_pole: str) -> bool:
        if allowed_poles is None:
            return True
        return _INTERNAL_POLE_TO_SLUG.get(internal_pole) in allowed_poles

    # ── Devlog (assignee_user_id ; status « termine » ; pas de
    #    completed_at → on prend updated_at comme proxy de complétion). ──
    if _allowed("devlog"):
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
                        entity=serialize_entity("devlog_project_task", t),
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
    if _allowed("entreprise"):
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
                        entity=serialize_entity("entreprise_tache", t),
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
    if _allowed("prospection"):
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
                        entity=serialize_entity("prospection_deal_task", t),
                        title=t.name,
                        status=t.status,
                        is_completed=is_done,
                        completed_at=completed_at,
                        created_at=t.created_at,
                        updated_at=t.updated_at,
                        reasons=reasons,
                    )
                )

    # ── Sales (assignation via employes ; done/done_at). → prospection ──
    if employe_ids and _allowed("sales"):
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
                        entity=serialize_entity("sales_task", t),
                        title=t.title,
                        status="done" if t.done else "open",
                        is_completed=t.done,
                        completed_at=completed_at,
                        created_at=t.created_at,
                        updated_at=t.updated_at,
                        reasons=reasons,
                    )
                )

    # ── Project (assignee_id via employes ; done/done_at). → construction ──
    if employe_ids and _allowed("project"):
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
                        entity=serialize_entity("project_task", t),
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
    db,
    user: User,
    start: datetime,
    end: datetime,
    allowed_poles: Optional[set[str]] = None,
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
    out: List[AuditActivity] = []
    for e in rows:
        if allowed_poles is not None:
            slug = _audit_slug(e)
            # Si on devine le pôle et qu'il n'est pas autorisé → on cache.
            # Si on ne devine pas (slug None), on inclut (best-effort) tant
            # qu'au moins un pôle est en lecture (allowed_poles non vide).
            if slug is not None and slug not in allowed_poles:
                continue
            if slug is None and not allowed_poles:
                continue
        out.append(
            AuditActivity(
                id=e.id,
                action=e.action,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                timestamp=e.created_at,
                summary=_humanize_audit(e),
            )
        )
    return out


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


# ── Création de tâche par pôle (réutilisé par l'endpoint + le MCP) ──


async def create_task_for_pole(
    db,
    user: User,
    *,
    pole: str,
    parent_id: int,
    title: str,
    description: Optional[str] = None,
    due_date: Optional[date_cls] = None,
    via: str = "api_key",
) -> TaskCreated:
    """Crée une tâche dans le pôle ``pole`` (slug du catalogue), rattachée
    à ``parent_id``, assignée à ``user``. Audité.

    Lève ValueError (→ 4xx côté appelant) si le pôle ne supporte pas la
    création de tâche ou si l'entité parente est introuvable. L'appelant
    DOIT déjà avoir vérifié la capacité ``<pole>:tasks:create``."""
    title = (title or "").strip()
    if not title:
        raise ValueError("Le titre de la tâche est requis.")

    pole = (pole or "").strip().lower()

    if pole == "devlog":
        parent = await db.get(DevlogProject, parent_id)
        if parent is None:
            raise ValueError(f"Projet devlog #{parent_id} introuvable.")
        task = DevlogProjectTask(
            project_id=parent_id,
            title=title,
            description=description or None,
            assignee_user_id=user.id,
            status="a_faire",
            priority="moyenne",
            due_date=due_date,
        )
        db.add(task)
        await db.flush()
        entity_type, entity_id, st = "devlog_project_task", task.id, task.status

    elif pole == "entreprise":
        parent = await db.get(Entreprise, parent_id)
        if parent is None:
            raise ValueError(f"Entreprise #{parent_id} introuvable.")
        task = EntrepriseTache(
            entreprise_id=parent_id,
            title=title,
            description=description or None,
            assignee_user_id=user.id,
            status="a_faire",
            due_date=due_date,
        )
        db.add(task)
        await db.flush()
        entity_type, entity_id, st = "entreprise_tache", task.id, task.status

    elif pole == "prospection":
        parent = await db.get(ProspectionDeal, parent_id)
        if parent is None:
            raise ValueError(f"Deal de prospection #{parent_id} introuvable.")
        task = ProspectionDealTask(
            deal_id=parent_id,
            name=title,
            notes=description or None,
            assignee_user_id=user.id,
            status="a_faire",
            due_date=due_date,
        )
        db.add(task)
        await db.flush()
        entity_type, entity_id, st = "prospection_deal_task", task.id, task.status

    elif pole == "construction":
        parent = await db.get(Project, parent_id)
        if parent is None:
            raise ValueError(f"Projet (chantier) #{parent_id} introuvable.")
        # Le pôle Construction assigne via employe_id : on relie
        # l'utilisateur à sa fiche Employe (par courriel) si elle existe.
        emp_ids = await _employe_ids_for_user(db, user)
        task = ProjectTask(
            project_id=parent_id,
            title=title,
            description=description or None,
            assignee_id=emp_ids[0] if emp_ids else None,
            due_date=due_date,
            done=False,
        )
        db.add(task)
        await db.flush()
        entity_type, entity_id, st = "project_task", task.id, "open"

    else:
        raise ValueError(
            f"Le pôle « {pole} » ne supporte pas la création de tâche par clé d'API."
        )

    await log_action(
        db,
        user=user,
        action="task.created",
        entity_type=entity_type,
        entity_id=entity_id,
        details={
            "pole": pole,
            "parent_id": parent_id,
            "title": title,
            "via": via,
        },
    )

    return TaskCreated(
        pole=pole,
        entity_type=entity_type,
        entity_id=entity_id,
        title=title,
        status=st,
    )


# ── Endpoints ──────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=ActivityResponse,
    summary="Activité de mon compte (clé d'API, pôles autorisés)",
)
async def my_activity(
    ctx: ApiKeyContext,
    db: DBSession,
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD (défaut: aujourd'hui)"),
    date_from: Optional[str] = Query(default=None, alias="from"),
    date_to: Optional[str] = Query(default=None, alias="to"),
) -> ActivityResponse:
    user = ctx.user
    poles = readable_poles(ctx.scopes)
    start, end = _resolve_window(date, date_from, date_to)
    single_day = (end - start) <= timedelta(days=1)

    tasks = await _collect_tasks(db, user, start, end, allowed_poles=poles)
    audit = await _collect_audit(db, user, start, end, allowed_poles=poles)
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
    summary="Résumé texte de mon activité (clé d'API, pôles autorisés)",
)
async def my_activity_summary(
    ctx: ApiKeyContext,
    db: DBSession,
    date: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, alias="from"),
    date_to: Optional[str] = Query(default=None, alias="to"),
) -> SummaryResponse:
    user = ctx.user
    poles = readable_poles(ctx.scopes)
    start, end = _resolve_window(date, date_from, date_to)
    single_day = (end - start) <= timedelta(days=1)

    tasks = await _collect_tasks(db, user, start, end, allowed_poles=poles)
    audit = await _collect_audit(db, user, start, end, allowed_poles=poles)
    summary = _build_summary(tasks, audit, start, end, single_day)

    return SummaryResponse(
        user_id=user.id,
        period_start=start,
        period_end=end,
        summary=summary,
    )


@router.post(
    "/tasks",
    response_model=TaskCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une tâche dans un pôle (clé d'API, capacité requise)",
)
async def create_task(
    payload: TaskCreate,
    ctx: ApiKeyContext,
    db: DBSession,
) -> TaskCreated:
    """Crée une tâche dans le pôle ``payload.pole``. Requiert la capacité
    ``<pole>:tasks:create`` sur la clé d'API (sinon 403). La tâche est
    assignée au propriétaire de la clé et auditée.

    La capacité requise dépend du pôle (issu du corps de la requête), donc
    on ne peut pas l'exprimer comme dépendance statique : on vérifie
    explicitement ``ctx.has_scope`` sur le contexte déjà authentifié."""
    pole = (payload.pole or "").strip().lower()
    if pole not in POLE_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Pôle inconnu : « {payload.pole} ».",
        )

    required = f"{pole}:tasks:create"
    if not ctx.has_scope(required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Capacité « Créer une tâche » non activée pour le pôle "
                f"« {POLE_LABELS[pole]} » sur cette clé d'API."
            ),
        )

    try:
        return await create_task_for_pole(
            db,
            ctx.user,
            pole=pole,
            parent_id=payload.parent_id,
            title=payload.title,
            description=payload.description,
            due_date=payload.due_date,
            via="api_key",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


# ── Lecture détail d'une entité (JSON « full ») ────────────────────
#
# Renvoie le JSON complet d'une entité métier par son id, en respectant
# le scope de pôle de la clé. Réutilisé par les endpoints REST ci-dessous
# ET par les outils MCP (kratos_get_*). Aucune écriture ; lecture seule.
#
# Chaque type d'entité déclare : son modèle ORM, le slug de pôle qui
# gouverne le scope, le type de sérialisation, et la capacité de lecture
# détail dédiée. L'autorisation est accordée si la clé porte la capacité
# détail OU peut lire l'activité de ce pôle (``<pole>:activity:read``) —
# ce qui préserve la RÉTROCOMPAT (clé sans scopes = lecture tous pôles).


#: Type d'entité de détail → (modèle ORM, slug de pôle, entity_type de
#: sérialisation, capacité de lecture détail dédiée).
_DETAIL_ENTITIES: dict[str, tuple] = {
    "soumission": (
        DevlogSoumission, "devlog", "devlog_soumission",
        "devlog:soumissions:read",
    ),
    "devlog_soumission": (
        DevlogSoumission, "devlog", "devlog_soumission",
        "devlog:soumissions:read",
    ),
    "deal": (
        ProspectionDeal, "prospection", "prospection_deal",
        "prospection:deals:read",
    ),
    "prospection_deal": (
        ProspectionDeal, "prospection", "prospection_deal",
        "prospection:deals:read",
    ),
    "entreprise": (
        Entreprise, "entreprise", "entreprise", "entreprise:read",
    ),
    # Tâches : chaque modèle a son slug de pôle et sa capacité <pole>:tasks:read.
    "devlog_project_task": (
        DevlogProjectTask, "devlog", "devlog_project_task",
        "devlog:tasks:read",
    ),
    "entreprise_tache": (
        EntrepriseTache, "entreprise", "entreprise_tache",
        "entreprise:tasks:read",
    ),
    "prospection_deal_task": (
        ProspectionDealTask, "prospection", "prospection_deal_task",
        "prospection:tasks:read",
    ),
    "sales_task": (
        SalesTask, "prospection", "sales_task", "prospection:tasks:read",
    ),
    "project_task": (
        ProjectTask, "construction", "project_task",
        "construction:tasks:read",
    ),
}


def _can_read_entity(ctx, pole: str, detail_cap: str) -> bool:
    """La clé peut-elle lire le détail d'une entité de ce pôle ?

    Vrai si elle porte la capacité de lecture détail dédiée OU si elle peut
    lire l'activité du pôle (``<pole>:activity:read``). Ce second test
    couvre la RÉTROCOMPAT : une clé sans scopes lit tous les pôles."""
    return ctx.has_scope(detail_cap) or ctx.has_scope(f"{pole}:activity:read")


async def _enrich_soumission(db, obj: DevlogSoumission) -> None:
    """Précharge (best-effort, sans casser) lead/client/modules/items sur
    une soumission devlog pour que le serializer « full » les expose. Les
    attributs sont posés en clair sur l'instance (pas des relations ORM)."""
    try:
        if getattr(obj, "lead_id", None) is not None:
            obj.lead = await db.get(DevlogLead, obj.lead_id)
        if getattr(obj, "client_id", None) is not None:
            obj.client = await db.get(DevlogClient, obj.client_id)
        mods = (
            await db.execute(
                select(DevlogSoumissionModule)
                .where(DevlogSoumissionModule.soumission_id == obj.id)
                .order_by(DevlogSoumissionModule.position)
            )
        ).scalars().all()
        obj.modules = list(mods)
        items = (
            await db.execute(
                select(DevlogSoumissionItem)
                .where(DevlogSoumissionItem.soumission_id == obj.id)
                .order_by(DevlogSoumissionItem.position)
            )
        ).scalars().all()
        obj.items = list(items)
    except Exception:
        # L'enrichissement est best-effort : le détail de base reste servi.
        pass


async def _enrich_entreprise(db, obj: Entreprise) -> None:
    """Précharge les partenaires d'une entreprise (best-effort)."""
    try:
        partners = (
            await db.execute(
                select(EntreprisePartner)
                .where(EntreprisePartner.entreprise_id == obj.id)
            )
        ).scalars().all()
        obj.partners = list(partners)
    except Exception:
        pass


async def load_entity_full(
    db,
    ctx,
    entity_type: str,
    entity_id: int,
) -> dict:
    """Charge une entité par son id et retourne son JSON « full » sérialisé,
    après vérification du scope de pôle. Réutilisé par REST et MCP.

    Lève :
      - ValueError("unknown") si ``entity_type`` n'est pas reconnu ;
      - PermissionError(message) si la clé n'a pas le scope requis ;
      - LookupError(message) si l'entité est introuvable.
    """
    spec = _DETAIL_ENTITIES.get(entity_type)
    if spec is None:
        raise ValueError("unknown")
    model, pole, ser_type, detail_cap = spec

    if not _can_read_entity(ctx, pole, detail_cap):
        raise PermissionError(
            f"Lecture du détail non autorisée pour le pôle "
            f"« {POLE_LABELS.get(pole, pole)} » sur cette clé d'API."
        )

    obj = await db.get(model, entity_id)
    if obj is None:
        raise LookupError(f"{entity_type} #{entity_id} introuvable.")

    # Préchargement spécifique selon le type (best-effort).
    if ser_type == "devlog_soumission":
        await _enrich_soumission(db, obj)
    elif ser_type == "entreprise":
        await _enrich_entreprise(db, obj)

    return serialize_entity(ser_type, obj, level="full")


@router.get(
    "/entities/{entity_type}/{entity_id}",
    summary="Lire le JSON détaillé d'une entité par son id (clé d'API)",
)
async def get_entity_detail(
    ctx: ApiKeyContext,
    db: DBSession,
    entity_type: str = Path(
        ...,
        description=(
            "Type d'entité : soumission, deal, entreprise, ou un type de "
            "tâche (devlog_project_task, entreprise_tache, "
            "prospection_deal_task, sales_task, project_task)."
        ),
    ),
    entity_id: int = Path(..., description="Identifiant de l'entité."),
) -> dict:
    """Renvoie le JSON « full » d'une entité métier (lecture seule),
    en respectant le scope de pôle de la clé.

    404 si le type est inconnu ou l'entité introuvable ; 403 si la clé n'a
    pas le scope de lecture du pôle correspondant."""
    try:
        return await load_entity_full(db, ctx, entity_type, entity_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Type d'entité inconnu : « {entity_type} ».",
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )


@router.get(
    "/entities/soumission/{entity_id}",
    summary="Détail d'une soumission devlog (clé d'API)",
)
async def get_soumission_detail(
    ctx: ApiKeyContext, db: DBSession,
    entity_id: int = Path(..., description="Id de la soumission devlog."),
) -> dict:
    try:
        return await load_entity_full(db, ctx, "devlog_soumission", entity_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/entities/deal/{entity_id}",
    summary="Détail d'un deal de prospection (clé d'API)",
)
async def get_deal_detail(
    ctx: ApiKeyContext, db: DBSession,
    entity_id: int = Path(..., description="Id du deal de prospection."),
) -> dict:
    try:
        return await load_entity_full(db, ctx, "prospection_deal", entity_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/entities/entreprise/{entity_id}",
    summary="Détail d'une entreprise (clé d'API)",
)
async def get_entreprise_detail(
    ctx: ApiKeyContext, db: DBSession,
    entity_id: int = Path(..., description="Id de l'entreprise."),
) -> dict:
    try:
        return await load_entity_full(db, ctx, "entreprise", entity_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
