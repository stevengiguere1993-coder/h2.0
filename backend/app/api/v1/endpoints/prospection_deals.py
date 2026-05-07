"""Pipeline des deals — CRUD pour les opportunités d'achat suivies
en mode Monday-like dans Prospection.

Endpoints :
  GET    /api/v1/prospection/deals      → liste triée par priorité
  POST   /api/v1/prospection/deals      → crée un deal (adresse + priorité)
  PATCH  /api/v1/prospection/deals/{id} → met à jour adresse / priorité
  DELETE /api/v1/prospection/deals/{id} → supprime
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, select

from app.api.deps import CurrentUser, DBSession
from app.models.prospection_deal import PRIORITY_ORDER, ProspectionDeal
from app.models.prospection_deal_task import (
    TASK_PRIORITIES,
    TASK_STATUSES,
    ProspectionDealTask,
)
from app.models.prospection_deal_task_assignee import (
    ProspectionDealTaskAssignee,
)
from app.models.prospection_deal_task_immeuble import (
    ProspectionDealTaskImmeuble,
)
from sqlalchemy import delete


router = APIRouter(prefix="/prospection/deals", tags=["prospection-deals"])


# Validation : on accepte uniquement les valeurs canoniques côté API
# pour ne pas se retrouver avec des typos en DB.
PRIORITY_PATTERN = r"^(urgent|eleve|moyenne|a_venir|termine|abandonne)$"


class DealCreate(BaseModel):
    address: str = Field(..., min_length=1, max_length=500)
    priority: str = Field(default="moyenne", pattern=PRIORITY_PATTERN)


class DealUpdate(BaseModel):
    address: Optional[str] = Field(default=None, min_length=1, max_length=500)
    priority: Optional[str] = Field(default=None, pattern=PRIORITY_PATTERN)


class DealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    address: str
    priority: str
    created_at: datetime
    updated_at: datetime


def _priority_rank_expr():
    """SQL CASE qui mappe priority → rang numérique (0 = plus urgent)
    pour qu'ORDER BY trie correctement urgent → a_venir."""
    whens = {p: i for i, p in enumerate(PRIORITY_ORDER)}
    return case(whens, value=ProspectionDeal.priority, else_=99)


@router.get("", response_model=List[DealRead])
async def list_deals(
    db: DBSession,
    _: CurrentUser,
) -> List[DealRead]:
    # Tri par `position` d'abord (modifiable via drag & drop dans la
    # sidebar Pipeline), puis adresse pour les deals jamais
    # repositionnés. La priorité legacy n'est plus utilisée pour le
    # tri — chaque deal a sa fiche maintenant, comme les entreprises.
    rows = (
        await db.execute(
            select(ProspectionDeal).order_by(
                ProspectionDeal.position.asc(),
                ProspectionDeal.address.asc(),
            )
        )
    ).scalars().all()
    return [DealRead.model_validate(r) for r in rows]


class ReorderDeals(BaseModel):
    """Liste ordonnée d'IDs de deals — détermine leur ordre dans
    la sidebar Pipeline."""
    ids: List[int]


@router.post(
    "/reorder",
    response_model=List[DealRead],
    summary="Réordonner les deals (drag & drop)",
)
async def reorder_deals(
    body: ReorderDeals,
    db: DBSession,
    _: CurrentUser,
) -> List[DealRead]:
    rows = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id.in_(body.ids))
        )
    ).scalars().all()
    by_id = {d.id: d for d in rows}
    for pos, did in enumerate(body.ids):
        d = by_id.get(did)
        if d is not None:
            d.position = (pos + 1) * 1000
    await db.flush()
    rows2 = (
        await db.execute(
            select(ProspectionDeal).order_by(
                ProspectionDeal.position.asc(),
                ProspectionDeal.address.asc(),
            )
        )
    ).scalars().all()
    return [DealRead.model_validate(d) for d in rows2]


@router.get("/{deal_id}", response_model=DealRead)
async def get_deal(
    deal_id: int,
    db: DBSession,
    _: CurrentUser,
) -> DealRead:
    deal = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal introuvable.")
    return DealRead.model_validate(deal)


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
async def create_deal(
    data: DealCreate,
    db: DBSession,
    _: CurrentUser,
) -> DealRead:
    deal = ProspectionDeal(
        address=data.address.strip(),
        priority=data.priority,
    )
    db.add(deal)
    await db.flush()
    await db.refresh(deal)
    return DealRead.model_validate(deal)


@router.patch("/{deal_id}", response_model=DealRead)
async def update_deal(
    deal_id: int,
    data: DealUpdate,
    db: DBSession,
    _: CurrentUser,
) -> DealRead:
    deal = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal introuvable.")
    if data.address is not None:
        deal.address = data.address.strip()
    if data.priority is not None:
        deal.priority = data.priority
    await db.flush()
    await db.refresh(deal)
    return DealRead.model_validate(deal)


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal(
    deal_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    deal = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal introuvable.")
    await db.delete(deal)
    await db.flush()


# ============================================================
# Tâches d'un deal
# ============================================================

TASK_STATUS_PATTERN = r"^(todo|a_faire|in_progress|done)$"
TASK_PRIORITY_PATTERN = r"^(non_assigne|urgent|eleve|moyenne|faible)$"


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=10_000)
    # Source de vérité : liste d'assignés. Le champ scalaire legacy
    # `assignee_user_id` reste accepté ; il est fusionné dans la liste
    # à la création / mise à jour.
    assignee_user_ids: Optional[List[int]] = None
    assignee_user_id: Optional[int] = Field(default=None, gt=0)
    # Démarre dans « À faire » par défaut — plus utile qu'« À venir »
    # car la tâche fraîchement créée est généralement déjà engagée.
    status: str = Field(default="a_faire", pattern=TASK_STATUS_PATTERN)
    # Défaut « non_assigne » : tant que l'utilisateur n'a pas
    # explicitement choisi une priorité, on ne suppose rien.
    priority: str = Field(default="non_assigne", pattern=TASK_PRIORITY_PATTERN)
    due_date: Optional[date] = None
    # Champs « riches » alignés sur EntrepriseTache.
    departement: Optional[str] = Field(default=None, max_length=64)
    recurrence: Optional[str] = Field(default=None, max_length=16)
    impact: Optional[int] = Field(default=None, ge=1, le=10)
    confidence: Optional[int] = Field(default=None, ge=1, le=10)
    effort: Optional[int] = Field(default=None, ge=1, le=10)
    # Immeubles concernés par la tâche (multi-select dans la fiche).
    immeuble_ids: Optional[List[int]] = None


class TaskUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=10_000)
    assignee_user_ids: Optional[List[int]] = None
    assignee_user_id: Optional[int] = None
    status: Optional[str] = Field(default=None, pattern=TASK_STATUS_PATTERN)
    priority: Optional[str] = Field(
        default=None, pattern=TASK_PRIORITY_PATTERN
    )
    due_date: Optional[date] = None
    position: Optional[int] = Field(default=None, ge=0)
    # Permet de déplacer une tâche vers un autre deal (bouton
    # « Déplacer » du kanban). Le deal cible doit exister.
    deal_id: Optional[int] = Field(default=None, gt=0)
    immeuble_ids: Optional[List[int]] = None
    departement: Optional[str] = Field(default=None, max_length=64)
    recurrence: Optional[str] = Field(default=None, max_length=16)
    impact: Optional[int] = Field(default=None, ge=1, le=10)
    confidence: Optional[int] = Field(default=None, ge=1, le=10)
    effort: Optional[int] = Field(default=None, ge=1, le=10)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    deal_id: int
    name: str
    notes: Optional[str]
    # Champ legacy = primary (premier de la liste). Conservé pour les
    # vieux clients qui n'auraient pas migré vers la liste.
    assignee_user_id: Optional[int]
    # Source de vérité — liste d'utilisateurs assignés.
    assignee_user_ids: List[int] = Field(default_factory=list)
    status: str
    priority: str
    due_date: Optional[date]
    position: int
    departement: Optional[str] = None
    recurrence: Optional[str] = None
    impact: Optional[int] = None
    confidence: Optional[int] = None
    effort: Optional[int] = None
    # Score ICE × urgence (calculé serveur-side, identique à
    # l'entreprise). None si l'un des trois champs ICE est absent.
    score: Optional[float] = None
    # Immeubles liés à la tâche.
    immeuble_ids: List[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


def _default_impact_from_priority(priority: str) -> int:
    """Mappe la priorité manuelle sur un impact ICE par défaut, pour
    les tâches créées sans valeur explicite. Le score reste éditable
    par l'utilisateur dans la fiche détaillée."""
    return {"urgent": 9, "eleve": 7, "faible": 3}.get(priority, 5)


def _compute_task_score(task: ProspectionDealTask) -> Optional[float]:
    """Même formule que les tâches d'entreprise : ICE × urgence."""
    if task.impact is None or task.confidence is None or task.effort is None:
        return None
    base = (task.impact * task.confidence) / max(task.effort, 1)
    if task.due_date:
        delta = (task.due_date - date.today()).days
        if delta < 0:
            urgency = 5.0
        elif delta <= 7:
            urgency = 3.0
        elif delta <= 14:
            urgency = 2.0
        elif delta <= 30:
            urgency = 1.5
        else:
            urgency = 1.0
    else:
        urgency = 1.0
    return round(base * urgency, 2)


def _task_status_rank_expr():
    whens = {s: i for i, s in enumerate(TASK_STATUSES)}
    return case(whens, value=ProspectionDealTask.status, else_=99)


async def _ensure_deal_exists(db, deal_id: int) -> ProspectionDeal:
    deal = (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal introuvable.")
    return deal


async def _load_task_assignees(
    db, task_ids: List[int]
) -> dict[int, List[int]]:
    """Retourne {task_id: [user_id, …]} pour les tâches données."""
    if not task_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ProspectionDealTaskAssignee.task_id,
                ProspectionDealTaskAssignee.user_id,
            ).where(ProspectionDealTaskAssignee.task_id.in_(task_ids))
        )
    ).all()
    out: dict[int, List[int]] = {tid: [] for tid in task_ids}
    for tid, uid in rows:
        out[int(tid)].append(int(uid))
    for k in out:
        out[k].sort()
    return out


def _resolve_assignee_ids(
    legacy_uid: Optional[int],
    list_uids: Optional[List[int]],
) -> Optional[List[int]]:
    """Combine champ legacy + liste pour produire la liste finale.
    None signifie « ne pas toucher » ; liste vide = retirer tous."""
    if list_uids is not None:
        return [int(u) for u in dict.fromkeys(list_uids) if u]
    if legacy_uid is not None:
        return [int(legacy_uid)] if legacy_uid else []
    return None


async def _replace_assignees(
    db, task: ProspectionDealTask, user_ids: Optional[List[int]]
) -> None:
    """Remplace les assignations de la tâche. None = on ne touche pas.
    Maintient `task.assignee_user_id` (= primary, premier du list)."""
    if user_ids is None:
        return
    await db.execute(
        delete(ProspectionDealTaskAssignee).where(
            ProspectionDealTaskAssignee.task_id == task.id
        )
    )
    for uid in user_ids:
        db.add(
            ProspectionDealTaskAssignee(task_id=task.id, user_id=uid)
        )
    task.assignee_user_id = user_ids[0] if user_ids else None


async def _load_task_immeubles(
    db, task_ids: List[int]
) -> dict[int, List[int]]:
    """Retourne {task_id: [immeuble_id, …]} pour les tâches données."""
    if not task_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ProspectionDealTaskImmeuble.task_id,
                ProspectionDealTaskImmeuble.immeuble_id,
            ).where(ProspectionDealTaskImmeuble.task_id.in_(task_ids))
        )
    ).all()
    out: dict[int, List[int]] = {tid: [] for tid in task_ids}
    for tid, iid in rows:
        out[int(tid)].append(int(iid))
    for k in out:
        out[k].sort()
    return out


async def _replace_immeubles(
    db, task: ProspectionDealTask, immeuble_ids: Optional[List[int]]
) -> None:
    """Remplace les liens immeuble de la tâche. None = on ne touche pas."""
    if immeuble_ids is None:
        return
    await db.execute(
        delete(ProspectionDealTaskImmeuble).where(
            ProspectionDealTaskImmeuble.task_id == task.id
        )
    )
    seen: set[int] = set()
    for iid in immeuble_ids:
        if iid and iid not in seen:
            seen.add(iid)
            db.add(
                ProspectionDealTaskImmeuble(
                    task_id=task.id, immeuble_id=iid
                )
            )


def _task_to_read(
    task: ProspectionDealTask,
    assignee_ids: List[int],
    immeuble_ids: List[int],
) -> TaskRead:
    return TaskRead(
        id=task.id,
        deal_id=task.deal_id,
        name=task.name,
        notes=task.notes,
        assignee_user_id=task.assignee_user_id,
        assignee_user_ids=assignee_ids,
        status=task.status,
        priority=task.priority,
        due_date=task.due_date,
        position=task.position,
        departement=task.departement,
        recurrence=task.recurrence,
        impact=task.impact,
        confidence=task.confidence,
        effort=task.effort,
        score=_compute_task_score(task),
        immeuble_ids=immeuble_ids,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("/{deal_id}/tasks", response_model=List[TaskRead])
async def list_tasks(
    deal_id: int,
    db: DBSession,
    _: CurrentUser,
) -> List[TaskRead]:
    await _ensure_deal_exists(db, deal_id)
    rows = (
        await db.execute(
            select(ProspectionDealTask)
            .where(ProspectionDealTask.deal_id == deal_id)
            .order_by(
                _task_status_rank_expr(),
                ProspectionDealTask.position.asc(),
                ProspectionDealTask.created_at.asc(),
            )
        )
    ).scalars().all()
    task_ids = [t.id for t in rows]
    assignees = await _load_task_assignees(db, task_ids)
    immeubles = await _load_task_immeubles(db, task_ids)
    return [
        _task_to_read(
            t, assignees.get(t.id, []), immeubles.get(t.id, [])
        )
        for t in rows
    ]


@router.post(
    "/{deal_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    deal_id: int,
    data: TaskCreate,
    db: DBSession,
    _: CurrentUser,
) -> TaskRead:
    await _ensure_deal_exists(db, deal_id)

    # Position : par défaut, après la dernière tâche du même statut.
    last_pos = (
        await db.execute(
            select(ProspectionDealTask.position)
            .where(
                ProspectionDealTask.deal_id == deal_id,
                ProspectionDealTask.status == data.status,
            )
            .order_by(ProspectionDealTask.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    next_pos = (int(last_pos) + 1000) if last_pos is not None else 1000

    uids = _resolve_assignee_ids(
        data.assignee_user_id, data.assignee_user_ids
    )
    primary = uids[0] if uids else None

    # Auto-remplit l'ICE si manquant : l'impact dérive de la priorité
    # manuelle (urgent=9, eleve=7, faible=3, autres=5), confiance et
    # effort = 5 par défaut. Garantit que toute nouvelle tâche a un
    # score (donc une pastille P1-P4) dès la création.
    auto_impact = data.impact if data.impact is not None else _default_impact_from_priority(data.priority)
    auto_conf = data.confidence if data.confidence is not None else 5
    auto_effort = data.effort if data.effort is not None else 5

    task = ProspectionDealTask(
        deal_id=deal_id,
        name=data.name.strip(),
        notes=data.notes,
        assignee_user_id=primary,
        status=data.status,
        priority=data.priority,
        due_date=data.due_date,
        position=next_pos,
        departement=data.departement,
        recurrence=data.recurrence,
        impact=auto_impact,
        confidence=auto_conf,
        effort=auto_effort,
    )
    db.add(task)
    await db.flush()
    if uids is not None:
        await _replace_assignees(db, task, uids)
    if data.immeuble_ids is not None:
        await _replace_immeubles(db, task, data.immeuble_ids)
    await db.flush()
    await db.refresh(task)
    final_a = await _load_task_assignees(db, [task.id])
    final_i = await _load_task_immeubles(db, [task.id])
    return _task_to_read(
        task, final_a.get(task.id, []), final_i.get(task.id, [])
    )


@router.patch("/{deal_id}/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    deal_id: int,
    task_id: int,
    data: TaskUpdate,
    db: DBSession,
    _: CurrentUser,
) -> TaskRead:
    task = (
        await db.execute(
            select(ProspectionDealTask).where(
                ProspectionDealTask.id == task_id,
                ProspectionDealTask.deal_id == deal_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tâche introuvable.")

    fields = data.model_dump(exclude_unset=True)
    # On traite les assignés séparément via _replace_assignees pour
    # ne pas écraser le scalar avec un legacy id intermédiaire.
    fields.pop("assignee_user_ids", None)
    legacy_uid_set = "assignee_user_id" in data.model_fields_set
    list_uids_set = "assignee_user_ids" in data.model_fields_set
    legacy_uid = fields.pop("assignee_user_id", None)

    # Idem pour les immeubles : on les retire des `fields` génériques
    # pour les remplacer via _replace_immeubles.
    fields.pop("immeuble_ids", None)
    imm_set = "immeuble_ids" in data.model_fields_set

    # Déplacement vers un autre deal — valider que la cible existe
    # avant d'écraser deal_id.
    target_deal_id = fields.get("deal_id")
    if target_deal_id is not None and target_deal_id != task.deal_id:
        await _ensure_deal_exists(db, target_deal_id)

    for field, value in fields.items():
        if field == "name" and value is not None:
            value = value.strip()
        setattr(task, field, value)
    await db.flush()

    if list_uids_set or legacy_uid_set:
        uids = _resolve_assignee_ids(
            legacy_uid if legacy_uid_set else None,
            data.assignee_user_ids if list_uids_set else None,
        )
        await _replace_assignees(db, task, uids)
        await db.flush()

    if imm_set:
        await _replace_immeubles(db, task, data.immeuble_ids)
        await db.flush()

    await db.refresh(task)
    final_a = await _load_task_assignees(db, [task.id])
    final_i = await _load_task_immeubles(db, [task.id])
    return _task_to_read(
        task, final_a.get(task.id, []), final_i.get(task.id, [])
    )


@router.delete(
    "/{deal_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_task(
    deal_id: int,
    task_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    task = (
        await db.execute(
            select(ProspectionDealTask).where(
                ProspectionDealTask.id == task_id,
                ProspectionDealTask.deal_id == deal_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tâche introuvable.")
    await db.delete(task)
    await db.flush()
