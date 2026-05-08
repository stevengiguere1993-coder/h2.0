"""Volet Gestion d'entreprises — CRUD entreprises + tâches.

Restreint au volet `entreprises` (whitelist côté User.volets).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DBSession
from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.schemas.entreprise import (
    EntrepriseCreate,
    EntrepriseRead,
    EntrepriseTacheCreate,
    EntrepriseTacheRead,
    EntrepriseTacheUpdate,
    EntrepriseUpdate,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/entreprises", tags=["entreprises"])


# ── Helpers ─────────────────────────────────────────────────────────────


def _require_volet(user: CurrentUser) -> None:
    """Refuse l'accès si l'utilisateur n'a pas le volet entreprises."""
    volets = getattr(user, "volets", None)
    if volets is None or "entreprises" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion d'entreprises » non autorisé pour cet utilisateur.",
        )


def _compute_score(t: EntrepriseTache) -> Optional[float]:
    """ICE × multiplicateur d'urgence basé sur la deadline.

    score = (impact × confidence / max(effort, 1)) × urgency
    urgency = 5 si en retard, 3 si <= 7j, 2 si 7-14j, 1.5 si 14-30j, 1 sinon.

    Retourne None si l'un des trois champs ICE est absent — la tâche
    n'est pas encore évaluée.
    """
    if t.impact is None or t.confidence is None or t.effort is None:
        return None
    base = (t.impact * t.confidence) / max(t.effort, 1)
    if t.due_date:
        delta = (t.due_date - date.today()).days
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


def _to_tache_read(
    t: EntrepriseTache,
    assignee_user_ids: Optional[List[int]] = None,
    immeuble_ids: Optional[List[int]] = None,
) -> EntrepriseTacheRead:
    out = EntrepriseTacheRead.model_validate(t)
    out.score = _compute_score(t)
    if assignee_user_ids is not None:
        out.assignee_user_ids = assignee_user_ids
    elif t.assignee_user_id is not None:
        # Pas de pré-fetch fourni → on retombe au moins sur le legacy.
        out.assignee_user_ids = [t.assignee_user_id]
    else:
        out.assignee_user_ids = []
    out.immeuble_ids = list(immeuble_ids or [])
    return out


async def _load_tache_assignees(
    db, tache_ids: List[int]
) -> dict[int, List[int]]:
    """Retourne {tache_id: [user_id, ...]} pour les tâches données."""
    if not tache_ids:
        return {}
    from app.models.entreprise_tache_assignee import (
        EntrepriseTacheAssignee,
    )
    rows = (
        await db.execute(
            select(
                EntrepriseTacheAssignee.tache_id,
                EntrepriseTacheAssignee.user_id,
            ).where(EntrepriseTacheAssignee.tache_id.in_(tache_ids))
        )
    ).all()
    out: dict[int, List[int]] = {tid: [] for tid in tache_ids}
    for tid, uid in rows:
        out[int(tid)].append(int(uid))
    for k in out:
        out[k].sort()
    return out


def _resolve_tache_assignee_ids(
    legacy_uid: Optional[int],
    list_uids: Optional[List[int]],
) -> Optional[List[int]]:
    """Combine champ legacy + liste : None = ne pas toucher,
    liste vide = retire tous, sinon dédupe + ordre conservé."""
    if list_uids is not None:
        return [int(u) for u in dict.fromkeys(list_uids) if u]
    if legacy_uid is not None:
        return [int(legacy_uid)] if legacy_uid else []
    return None


async def _replace_tache_assignees(
    db, tache: EntrepriseTache, user_ids: Optional[List[int]]
) -> None:
    """Remplace les assignations en bloc. None = on ne touche pas.
    Met aussi à jour le scalaire `assignee_user_id` au primary."""
    if user_ids is None:
        return
    from app.models.entreprise_tache_assignee import (
        EntrepriseTacheAssignee,
    )
    from sqlalchemy import delete as _delete
    await db.execute(
        _delete(EntrepriseTacheAssignee).where(
            EntrepriseTacheAssignee.tache_id == tache.id
        )
    )
    for uid in user_ids:
        db.add(EntrepriseTacheAssignee(tache_id=tache.id, user_id=uid))
    tache.assignee_user_id = user_ids[0] if user_ids else None


async def _load_tache_immeubles(
    db, tache_ids: List[int]
) -> dict[int, List[int]]:
    """Retourne {tache_id: [immeuble_id, ...]} pour les tâches données."""
    if not tache_ids:
        return {}
    from app.models.entreprise_tache_immeuble import (
        EntrepriseTacheImmeuble,
    )
    rows = (
        await db.execute(
            select(
                EntrepriseTacheImmeuble.tache_id,
                EntrepriseTacheImmeuble.immeuble_id,
            ).where(EntrepriseTacheImmeuble.tache_id.in_(tache_ids))
        )
    ).all()
    out: dict[int, List[int]] = {tid: [] for tid in tache_ids}
    for tid, iid in rows:
        out[int(tid)].append(int(iid))
    for k in out:
        out[k].sort()
    return out


async def _replace_tache_immeubles(
    db, tache: EntrepriseTache, immeuble_ids: Optional[List[int]]
) -> None:
    """Remplace les liens immeuble en bloc. None = on ne touche pas."""
    if immeuble_ids is None:
        return
    from app.models.entreprise_tache_immeuble import (
        EntrepriseTacheImmeuble,
    )
    from sqlalchemy import delete as _delete
    await db.execute(
        _delete(EntrepriseTacheImmeuble).where(
            EntrepriseTacheImmeuble.tache_id == tache.id
        )
    )
    seen: set[int] = set()
    for iid in immeuble_ids:
        if iid and iid not in seen:
            seen.add(iid)
            db.add(
                EntrepriseTacheImmeuble(tache_id=tache.id, immeuble_id=iid)
            )


# ── Entreprises CRUD ────────────────────────────────────────────────────


@router.get("", response_model=List[EntrepriseRead])
async def list_entreprises(
    db: DBSession, user: CurrentUser
) -> List[EntrepriseRead]:
    _require_volet(user)
    # Tri par `position` (modifiable via drag & drop dans la sidebar),
    # puis par nom en fallback. Position 0 = entreprises jamais
    # repositionnées (les nouvelles + le legacy avant migration) ;
    # leur sous-tri par nom garde l'ordre stable.
    rows = (
        await db.execute(
            select(Entreprise).order_by(
                Entreprise.position.asc(),
                Entreprise.name.asc(),
            )
        )
    ).scalars().all()
    return [EntrepriseRead.model_validate(e) for e in rows]


class ReorderEntreprises(BaseModel):
    """Liste ordonnée d'IDs d'entreprises — détermine leur ordre
    d'affichage dans la sidebar."""
    ids: List[int]


@router.post(
    "/reorder",
    response_model=List[EntrepriseRead],
    summary="Réordonner les entreprises (drag & drop)",
)
async def reorder_entreprises(
    body: ReorderEntreprises,
    db: DBSession,
    user: CurrentUser,
) -> List[EntrepriseRead]:
    _require_volet(user)
    # Réassigne les positions par pas de 1000 (idem ProjectPhase) pour
    # pouvoir insérer entre deux items à l'avenir sans renuméroter.
    rows = (
        await db.execute(select(Entreprise).where(Entreprise.id.in_(body.ids)))
    ).scalars().all()
    by_id = {e.id: e for e in rows}
    for pos, eid in enumerate(body.ids):
        ent = by_id.get(eid)
        if ent is not None:
            ent.position = (pos + 1) * 1000
    await db.flush()
    # Retourne la liste re-triée pour confirmation.
    rows2 = (
        await db.execute(
            select(Entreprise).order_by(
                Entreprise.position.asc(),
                Entreprise.name.asc(),
            )
        )
    ).scalars().all()
    return [EntrepriseRead.model_validate(e) for e in rows2]


@router.post(
    "",
    response_model=EntrepriseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_entreprise(
    body: EntrepriseCreate, db: DBSession, user: CurrentUser
) -> EntrepriseRead:
    _require_volet(user)
    e = Entreprise(**body.model_dump())
    db.add(e)
    await db.flush()
    await db.refresh(e)
    return EntrepriseRead.model_validate(e)


@router.patch("/{entreprise_id}", response_model=EntrepriseRead)
async def update_entreprise(
    entreprise_id: int,
    body: EntrepriseUpdate,
    db: DBSession,
    user: CurrentUser,
) -> EntrepriseRead:
    _require_volet(user)
    e = (
        await db.execute(
            select(Entreprise).where(Entreprise.id == entreprise_id)
        )
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(404, "Entreprise non trouvée")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(e, k, v)
    await db.flush()
    await db.refresh(e)
    return EntrepriseRead.model_validate(e)


@router.delete(
    "/{entreprise_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_entreprise(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> None:
    """Supprime définitivement une entreprise et toutes ses données liées
    (tâches, templates, snapshots financiers, plans de valeur, ownerships
    immeubles, investissements...). Cascade géré par les ON DELETE des FK.
    """
    _require_volet(user)
    e = await db.get(Entreprise, entreprise_id)
    if e is None:
        raise HTTPException(404, "Entreprise non trouvée")
    await db.delete(e)
    await db.commit()


# ── Tâches CRUD ─────────────────────────────────────────────────────────


@router.get("/taches", response_model=List[EntrepriseTacheRead])
async def list_taches(
    db: DBSession,
    user: CurrentUser,
    entreprise_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    assignee_user_id: Optional[int] = None,
    mine: bool = False,
) -> List[EntrepriseTacheRead]:
    """Liste des tâches du QG.

    Filtres :
    - `entreprise_id` : restreint à une entreprise.
    - `status_filter` : restreint à un statut kanban.
    - `assignee_user_id` : restreint à un assignee précis.
    - `mine=true` : raccourci, filtre sur l'utilisateur connecté
      (équivalent à passer `assignee_user_id=<mon id>`).
    """
    _require_volet(user)
    stmt = select(EntrepriseTache)
    if entreprise_id is not None:
        stmt = stmt.where(EntrepriseTache.entreprise_id == entreprise_id)
    if status_filter:
        stmt = stmt.where(EntrepriseTache.status == status_filter)
    if mine:
        stmt = stmt.where(EntrepriseTache.assignee_user_id == user.id)
    elif assignee_user_id is not None:
        stmt = stmt.where(
            EntrepriseTache.assignee_user_id == assignee_user_id
        )
    stmt = stmt.order_by(
        EntrepriseTache.due_date.asc().nullslast(),
        EntrepriseTache.id.desc(),
    )
    rows = (await db.execute(stmt)).scalars().all()
    tache_ids = [r.id for r in rows]
    assignees = await _load_tache_assignees(db, tache_ids)
    immeubles = await _load_tache_immeubles(db, tache_ids)
    return [
        _to_tache_read(
            t, assignees.get(t.id, []), immeubles.get(t.id, [])
        )
        for t in rows
    ]


@router.get(
    "/users/with-volet",
    response_model=List[dict],
)
async def list_users_with_volet(
    db: DBSession, user: CurrentUser
) -> List[dict]:
    """Liste les utilisateurs ayant accès au volet `entreprises`,
    pour alimenter le picker d'assignation côté UI."""
    _require_volet(user)
    from app.models.user import User

    rows = (
        await db.execute(
            select(User).order_by(User.email.asc())
        )
    ).scalars().all()
    out: List[dict] = []
    for u in rows:
        volets = getattr(u, "volets", None) or []
        if "entreprises" not in volets:
            continue
        out.append(
            {
                "id": u.id,
                "email": u.email,
                "full_name": getattr(u, "full_name", None) or u.email,
            }
        )
    return out


@router.get(
    "/taches/{tache_id}/suggest-assignees",
    response_model=List[dict],
)
async def suggest_tache_assignees(
    tache_id: int,
    db: DBSession,
    user: CurrentUser,
    top_n: int = 3,
) -> List[dict]:
    """Top N utilisateurs proposés pour assignation d'une tâche, en
    fonction de leur charge actuelle de tâches ouvertes et de leur
    disponibilité dans les calendriers ICS (7 prochains jours)."""
    _require_volet(user)
    from app.models.user import User
    from app.services.qg_smart_assign import suggest_assignees

    t = await db.get(EntrepriseTache, tache_id)
    if t is None:
        raise HTTPException(404, "Tâche introuvable.")

    # Candidats = users avec volet entreprises
    candidates = []
    rows = (await db.execute(select(User))).scalars().all()
    for u in rows:
        volets = getattr(u, "volets", None) or []
        if "entreprises" in volets:
            candidates.append(u)

    suggestions = await suggest_assignees(db, candidates, top_n=top_n)
    return [s.__dict__ for s in suggestions]


@router.post(
    "/taches",
    response_model=EntrepriseTacheRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_tache(
    body: EntrepriseTacheCreate, db: DBSession, user: CurrentUser
) -> EntrepriseTacheRead:
    _require_volet(user)
    payload = body.model_dump()
    # Sépare les assignés de la création principale.
    legacy_uid = payload.pop("assignee_user_id", None)
    list_uids = payload.pop("assignee_user_ids", None)
    immeuble_ids = payload.pop("immeuble_ids", None)
    uids = _resolve_tache_assignee_ids(legacy_uid, list_uids)
    primary = uids[0] if uids else None

    # Pas d'auto-remplissage des ICE à la création — la tâche
    # démarre en P4 « Non évaluée » côté UI, puis l'IA en
    # background remplit les valeurs et la pastille se met à jour
    # au prochain refetch.
    t = EntrepriseTache(**payload, assignee_user_id=primary)
    db.add(t)
    await db.flush()
    if uids is not None:
        await _replace_tache_assignees(db, t, uids)
    if immeuble_ids is not None:
        await _replace_tache_immeubles(db, t, immeuble_ids)
    await db.flush()
    await db.refresh(t)
    # Fire-and-forget : scoring IA asynchrone. N'attend pas la
    # réponse pour ne pas ralentir la création côté UI.
    if t.impact is None and t.confidence is None and t.effort is None:
        import asyncio

        from app.services.task_auto_score import autoscore_entreprise_tache

        asyncio.create_task(autoscore_entreprise_tache(int(t.id)))
    final_a = await _load_tache_assignees(db, [t.id])
    final_i = await _load_tache_immeubles(db, [t.id])
    return _to_tache_read(
        t, final_a.get(t.id, []), final_i.get(t.id, [])
    )


@router.patch("/taches/{tache_id}", response_model=EntrepriseTacheRead)
async def update_tache(
    tache_id: int,
    body: EntrepriseTacheUpdate,
    db: DBSession,
    user: CurrentUser,
) -> EntrepriseTacheRead:
    _require_volet(user)
    t = (
        await db.execute(
            select(EntrepriseTache).where(EntrepriseTache.id == tache_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "Tâche non trouvée")
    payload = body.model_dump(exclude_unset=True)
    # Auto-set completed_at quand la tâche passe à done
    if (
        payload.get("status") == TacheStatus.DONE.value
        and t.status != TacheStatus.DONE.value
        and t.completed_at is None
    ):
        payload.setdefault("completed_at", datetime.now(timezone.utc))
    # Assignés : on les traite à part pour ne pas se faire écraser
    # par le simple setattr qui ne gère pas la table de jointure.
    legacy_uid_set = "assignee_user_id" in body.model_fields_set
    list_uids_set = "assignee_user_ids" in body.model_fields_set
    legacy_uid = payload.pop("assignee_user_id", None)
    payload.pop("assignee_user_ids", None)

    # Idem pour les immeubles — table de jointure dédiée.
    imm_set = "immeuble_ids" in body.model_fields_set
    payload.pop("immeuble_ids", None)

    for k, v in payload.items():
        setattr(t, k, v)
    await db.flush()

    if list_uids_set or legacy_uid_set:
        uids = _resolve_tache_assignee_ids(
            legacy_uid if legacy_uid_set else None,
            body.assignee_user_ids if list_uids_set else None,
        )
        await _replace_tache_assignees(db, t, uids)
        await db.flush()

    if imm_set:
        await _replace_tache_immeubles(db, t, body.immeuble_ids)
        await db.flush()

    await db.refresh(t)
    final_a = await _load_tache_assignees(db, [t.id])
    final_i = await _load_tache_immeubles(db, [t.id])
    return _to_tache_read(
        t, final_a.get(t.id, []), final_i.get(t.id, [])
    )


@router.delete(
    "/taches/{tache_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_tache(
    tache_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    t = (
        await db.execute(
            select(EntrepriseTache).where(EntrepriseTache.id == tache_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "Tâche non trouvée")
    await db.delete(t)
    await db.flush()


def _map_status_label(label: Optional[str]) -> Optional[str]:
    """Mappe un libellé de statut (legacy Monday) sur un TacheStatus.
    Retourne None si rien ne matche — laisse l'appelant décider du
    fallback (backlog ou autre).

    Utilisé par la reclassification des tâches importées de Monday qui
    sont restées en backlog : on regarde leur ancien nom de groupe
    Monday pour deviner le statut courant."""
    if not label:
        return None
    s = label.lower().strip()
    if any(k in s for k in ("done", "termin", "complet", "fait", "résolu", "resolu", "closed", "clos", "fini")):
        return TacheStatus.DONE.value
    if any(
        k in s
        for k in (
            "in progress", "in_progress", "progress", "working",
            "working on it", "en cours", "doing", "actif", "wip", "ongoing",
        )
    ):
        return TacheStatus.IN_PROGRESS.value
    if any(
        k in s
        for k in (
            "attente", "wait", "block", "stuck", "on hold", "hold",
            "pause", "bloqu", "pending review",
        )
    ):
        return TacheStatus.TODO.value
    if any(
        k in s
        for k in (
            "todo", "to do", "to-do", "à faire", "a faire", "next",
            "ready", "planifié", "planifie", "this week", "semaine",
            "scheduled", "open",
        )
    ):
        return TacheStatus.TODO.value
    if any(k in s for k in ("backlog", "icebox", "later", "someday", "idea", "idée", "idee")):
        return TacheStatus.BACKLOG.value
    return None


# ── Reclassification batch ──────────────────────────────────────────────


class ReclassifyOut(BaseModel):
    done: int
    in_progress: int
    waiting: int
    todo: int
    untouched_backlog: int


@router.post(
    "/taches/reclassify",
    response_model=ReclassifyOut,
    summary="Re-classe toutes les tâches encore en backlog",
)
async def reclassify_taches(
    db: DBSession, user: CurrentUser
) -> ReclassifyOut:
    """Ventile les tâches encore en backlog dans les 4 colonnes
    cibles (todo, in_progress, waiting, done) en se basant sur leur
    `monday_group_title`. Aussi déclenché automatiquement au boot
    via `init_db` ; cet endpoint permet de re-jouer la passe à la
    main après un nouvel import."""
    _require_volet(user)

    rows = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.status == TacheStatus.BACKLOG.value
            )
        )
    ).scalars().all()

    counts = {"done": 0, "in_progress": 0, "waiting": 0, "todo": 0, "left": 0}
    for t in rows:
        # Si la tâche a déjà une date de complétion, c'est terminé
        # peu importe ce que dit le groupe Monday.
        if t.completed_at is not None:
            t.status = TacheStatus.DONE.value
            counts["done"] += 1
            continue
        guess = _map_status_label(t.monday_group_title)
        if guess == TacheStatus.BACKLOG.value:
            guess = None  # backlog = pas de signal → fallback TODO
        if guess is None and t.monday_item_id:
            # Importée de Monday sans signal clair → À faire par défaut.
            guess = TacheStatus.TODO.value
        if guess is None:
            counts["left"] += 1
            continue
        t.status = guess
        if guess == TacheStatus.DONE.value:
            counts["done"] += 1
        elif guess == TacheStatus.IN_PROGRESS.value:
            counts["in_progress"] += 1
        elif guess == TacheStatus.WAITING.value:
            counts["waiting"] += 1
        elif guess == TacheStatus.TODO.value:
            counts["todo"] += 1
    await db.flush()

    return ReclassifyOut(
        done=counts["done"],
        in_progress=counts["in_progress"],
        waiting=counts["waiting"],
        todo=counts["todo"],
        untouched_backlog=counts["left"],
    )


# ── Insights (alertes IA) ───────────────────────────────────────────────


class InsightOut(BaseModel):
    id: int
    entreprise_id: int
    type: str
    status: str
    title: str
    body: str
    confidence: Optional[float] = None
    suggested_actions: List[str] = Field(default_factory=list)
    estimated_impact_label: Optional[str] = None
    estimated_impact_currency: Optional[float] = None
    created_at: datetime

    @classmethod
    def from_model(cls, i: "Insight") -> "InsightOut":
        import json as _json
        try:
            actions = _json.loads(i.suggested_actions_json or "[]")
            if not isinstance(actions, list):
                actions = []
        except Exception:
            actions = []
        return cls(
            id=i.id,
            entreprise_id=i.entreprise_id,
            type=i.type,
            status=i.status,
            title=i.title,
            body=i.body,
            confidence=float(i.confidence) if i.confidence is not None else None,
            suggested_actions=[str(a) for a in actions],
            estimated_impact_label=i.estimated_impact_label,
            estimated_impact_currency=(
                float(i.estimated_impact_currency)
                if i.estimated_impact_currency is not None
                else None
            ),
            created_at=i.created_at,
        )


@router.get(
    "/{entreprise_id}/insights",
    response_model=List[InsightOut],
    summary="Liste les insights IA d'une entreprise",
)
async def list_insights(
    entreprise_id: int,
    db: DBSession,
    user: CurrentUser,
    open_only: bool = True,
) -> List[InsightOut]:
    _require_volet(user)
    from app.models.qg_strategic import Insight, InsightStatus

    stmt = select(Insight).where(Insight.entreprise_id == entreprise_id)
    if open_only:
        stmt = stmt.where(
            Insight.status.in_([
                InsightStatus.NEW.value,
                InsightStatus.ACKNOWLEDGED.value,
                InsightStatus.IN_ACTION.value,
            ])
        )
    rows = (
        await db.execute(stmt.order_by(Insight.created_at.desc()).limit(50))
    ).scalars().all()
    return [InsightOut.from_model(i) for i in rows]


@router.post(
    "/{entreprise_id}/insights/generate",
    summary="Génère de nouveaux insights pour une entreprise",
)
async def generate_insights(
    entreprise_id: int,
    db: DBSession,
    user: CurrentUser,
    force: bool = False,
) -> dict:
    _require_volet(user)
    from app.services.qg_insights import generate_for_entreprise

    res = await generate_for_entreprise(db, entreprise_id, force=force)
    await db.commit()
    return res


class InsightStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(new|acknowledged|in_action|dismissed|resolved)$")


@router.patch(
    "/insights/{insight_id}",
    response_model=InsightOut,
    summary="Change le statut d'un insight (acknowledge/dismiss/resolve)",
)
async def update_insight_status(
    insight_id: int,
    body: InsightStatusUpdate,
    db: DBSession,
    user: CurrentUser,
) -> InsightOut:
    _require_volet(user)
    from app.models.qg_strategic import Insight, InsightStatus

    i = (
        await db.execute(select(Insight).where(Insight.id == insight_id))
    ).scalar_one_or_none()
    if i is None:
        raise HTTPException(404, "Insight introuvable")
    i.status = body.status
    if body.status == InsightStatus.RESOLVED.value and i.resolved_at is None:
        i.resolved_at = datetime.now(timezone.utc)
    if body.status in (
        InsightStatus.ACKNOWLEDGED.value,
        InsightStatus.IN_ACTION.value,
    ) and i.acknowledged_at is None:
        i.acknowledged_at = datetime.now(timezone.utc)
        i.acknowledged_by_user_id = user.id
    await db.flush()
    await db.refresh(i)
    return InsightOut.from_model(i)


# ── Visions (horizons stratégiques) ─────────────────────────────────────


class VisionOut(BaseModel):
    id: int
    entreprise_id: int
    horizon_label: str
    horizon_start: date
    horizon_end: date
    title: str
    narrative: str
    objectives: List[str] = Field(default_factory=list)
    key_actions: List[str] = Field(default_factory=list)
    generated_by_ai: bool
    approved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, v: "Vision") -> "VisionOut":
        import json as _json
        try:
            objs = _json.loads(v.objectives_json or "[]")
            if not isinstance(objs, list):
                objs = []
        except Exception:
            objs = []
        try:
            acts = _json.loads(v.key_actions_json or "[]")
            if not isinstance(acts, list):
                acts = []
        except Exception:
            acts = []
        return cls(
            id=v.id,
            entreprise_id=v.entreprise_id,
            horizon_label=v.horizon_label,
            horizon_start=v.horizon_start,
            horizon_end=v.horizon_end,
            title=v.title,
            narrative=v.narrative,
            objectives=[str(o) for o in objs],
            key_actions=[str(a) for a in acts],
            generated_by_ai=v.generated_by_ai,
            approved_at=v.approved_at,
            created_at=v.created_at,
            updated_at=v.updated_at,
        )


@router.get(
    "/{entreprise_id}/visions",
    response_model=List[VisionOut],
    summary="Visions stratégiques d'une entreprise (par horizon)",
)
async def list_visions(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> List[VisionOut]:
    _require_volet(user)
    from app.models.qg_strategic import Vision

    rows = (
        await db.execute(
            select(Vision)
            .where(Vision.entreprise_id == entreprise_id)
            .order_by(Vision.horizon_start.desc())
        )
    ).scalars().all()
    return [VisionOut.from_model(v) for v in rows]


class VisionGenerateRequest(BaseModel):
    horizon: str = Field(..., pattern="^(7j|30j|90j|12m)$")
    force: bool = False


@router.post(
    "/{entreprise_id}/visions/generate",
    response_model=Optional[VisionOut],
    summary="Génère une vision stratégique pour un horizon (7j/30j/90j/12m)",
)
async def generate_vision_endpoint(
    entreprise_id: int,
    body: VisionGenerateRequest,
    db: DBSession,
    user: CurrentUser,
) -> Optional[VisionOut]:
    _require_volet(user)
    from app.services.qg_visions import generate_vision

    try:
        v = await generate_vision(
            db,
            entreprise_id,
            horizon_key=body.horizon,
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if v is None:
        raise HTTPException(503, "IA indisponible ou entreprise introuvable.")
    await db.commit()
    return VisionOut.from_model(v)


# ── Stats overview (4 KPIs accueil volet) ───────────────────────────────


class StatsOverview(BaseModel):
    """Stats consolidées affichées sur l'accueil du volet."""

    entreprises_count: int
    taches_open: int      # toutes statuts != done/cancelled
    taches_in_progress: int
    taches_urgent: int    # due_date <= 7j et open
    taches_done_30d: int  # terminées dans les 30 derniers jours
    avg_score_open: Optional[float]  # score moyen des tâches ouvertes


@router.get(
    "/stats/overview",
    response_model=StatsOverview,
    summary="Stats consolidées du volet (KPI accueil)",
)
async def stats_overview(db: DBSession, user: CurrentUser) -> StatsOverview:
    _require_volet(user)
    from datetime import timedelta
    from sqlalchemy import func

    # Compte d'entreprises actives
    n_ent = (
        await db.execute(
            select(func.count())
            .select_from(Entreprise)
            .where(Entreprise.is_active.is_(True))
        )
    ).scalar() or 0

    # Tâches ouvertes (tous statuts != done)
    open_taches = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.status != TacheStatus.DONE.value
            )
        )
    ).scalars().all()

    today = date.today()
    soon = today + timedelta(days=7)

    in_progress = sum(
        1 for t in open_taches
        if t.status == TacheStatus.IN_PROGRESS.value
    )
    urgent = sum(
        1 for t in open_taches
        if t.due_date is not None
        and t.due_date <= soon
        and t.status not in (TacheStatus.DONE.value, "cancelled")
    )

    # Tâches terminées dans les 30 derniers jours
    cutoff = datetime.combine(
        today - timedelta(days=30),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    done_30d = (
        await db.execute(
            select(func.count())
            .select_from(EntrepriseTache)
            .where(
                EntrepriseTache.status == TacheStatus.DONE.value,
                EntrepriseTache.completed_at >= cutoff,
            )
        )
    ).scalar() or 0

    # Score moyen des tâches ouvertes scorées (3 champs ICE non-null)
    scored = []
    for t in open_taches:
        s = _compute_score(t)
        if s is not None:
            scored.append(s)
    avg_score = (sum(scored) / len(scored)) if scored else None

    return StatsOverview(
        entreprises_count=int(n_ent),
        taches_open=len(open_taches),
        taches_in_progress=in_progress,
        taches_urgent=urgent,
        taches_done_30d=int(done_30d),
        avg_score_open=round(avg_score, 1) if avg_score is not None else None,
    )


class EntrepriseHealth(BaseModel):
    entreprise_id: int
    name: str
    color_accent: str
    type: str
    description: Optional[str] = None
    is_active: bool = True
    health_score: int  # 0-100
    health_label: str  # 'good' | 'warn' | 'risk'
    taches_open: int
    taches_done: int
    taches_total: int
    taches_overdue: int
    taches_urgent: int
    last_briefing_headline: Optional[str] = None


@router.get(
    "/health",
    response_model=List[EntrepriseHealth],
    summary="Santé consolidée par entreprise (tableau « État des entreprises »)",
)
async def entreprises_health(
    db: DBSession,
    user: CurrentUser,
    include_archived: bool = False,
) -> List[EntrepriseHealth]:
    _require_volet(user)
    from app.models.qg_strategic import Summary, SummaryType

    q = select(Entreprise)
    if not include_archived:
        q = q.where(Entreprise.is_active.is_(True))
    ents = (
        await db.execute(
            q.order_by(
                Entreprise.position.asc(),
                Entreprise.name.asc(),
            )
        )
    ).scalars().all()

    today = date.today()
    # Borne de fenêtre pour la vélocité (tâches terminées récemment).
    velocity_window_days = 30
    velocity_floor = today - timedelta(days=velocity_window_days)

    out: List[EntrepriseHealth] = []
    for e in ents:
        all_taches = (
            await db.execute(
                select(EntrepriseTache).where(
                    EntrepriseTache.entreprise_id == e.id
                )
            )
        ).scalars().all()
        total = len(all_taches)
        done = sum(
            1 for t in all_taches if t.status == TacheStatus.DONE.value
        )
        open_t = total - done
        overdue = sum(
            1 for t in all_taches
            if t.status != TacheStatus.DONE.value
            and t.due_date is not None
            and t.due_date < today
        )
        urgent = sum(
            1 for t in all_taches
            if t.status != TacheStatus.DONE.value
            and t.due_date is not None
            and 0 <= (t.due_date - today).days <= 7
        )
        # Tâches terminées dans les `velocity_window_days` jours.
        # Donne une indication de vélocité actuelle, indépendante de
        # l'historique cumulé. `completed_at` peut être None pour les
        # vieux rows ; on tombe alors sur `updated_at` au pire.
        recent_done = sum(
            1 for t in all_taches
            if t.status == TacheStatus.DONE.value
            and (
                (t.completed_at is not None
                 and t.completed_at.date() >= velocity_floor)
                or (t.completed_at is None
                    and t.updated_at is not None
                    and t.updated_at.date() >= velocity_floor)
            )
        )

        # Score 0-100 — formule forward-looking :
        #   - Base : 100 si rien d'ouvert. Sinon dépend du ratio
        #     d'overdue parmi les ouvertes (pas du done_ratio cumulé,
        #     qui devient artificiellement haut au fil du temps —
        #     les tâches done s'accumulent en historique).
        #   - Pénalité de charge : > 30 ouvertes = pénalité douce.
        #   - Pénalité urgent : tâches dues dans les 7j.
        #   - Bonus vélocité : avoir terminé des tâches récemment
        #     compense légèrement les pénalités (témoigne d'activité).
        if open_t == 0:
            score = 100
        else:
            overdue_ratio = overdue / open_t
            base = 100 - 50 * overdue_ratio
            charge_penalty = max(0, (open_t - 30) * 0.5)
            urgent_penalty = min(15, urgent * 2)
            velocity_bonus = min(10, recent_done * 0.5)
            score = max(
                20,
                int(base - charge_penalty - urgent_penalty + velocity_bonus),
            )

        if score >= 80:
            label = "good"
        elif score >= 55:
            label = "warn"
        else:
            label = "risk"

        # Dernier briefing pour le tooltip / preview
        last_brief = (
            await db.execute(
                select(Summary)
                .where(
                    Summary.entreprise_id == e.id,
                    Summary.type == SummaryType.DAILY_BRIEFING.value,
                )
                .order_by(Summary.period_start.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        out.append(EntrepriseHealth(
            entreprise_id=e.id,
            name=e.name,
            color_accent=e.color_accent,
            type=e.type,
            description=e.description,
            is_active=bool(e.is_active),
            health_score=int(score),
            health_label=label,
            taches_open=int(open_t),
            taches_done=int(done),
            taches_total=int(total),
            taches_overdue=int(overdue),
            taches_urgent=int(urgent),
            last_briefing_headline=last_brief.headline if last_brief else None,
        ))
    return out


# ── Daily Pulse (briefing IA quotidien) ─────────────────────────────────


class DailyBriefingOut(BaseModel):
    id: int
    entreprise_id: int
    period_start: datetime
    period_end: datetime
    headline: str
    summary_text: str
    highlights: List[str] = Field(default_factory=list)
    model_used: Optional[str] = None
    provider: Optional[str] = None
    created_at: datetime

    @classmethod
    def from_summary(cls, s: "Summary") -> "DailyBriefingOut":
        import json as _json

        try:
            highlights = _json.loads(s.highlights_json or "[]")
            if not isinstance(highlights, list):
                highlights = []
        except Exception:
            highlights = []
        return cls(
            id=s.id,
            entreprise_id=s.entreprise_id,
            period_start=s.period_start,
            period_end=s.period_end,
            headline=s.headline,
            summary_text=s.summary_text,
            highlights=[str(h) for h in highlights],
            model_used=s.model_used,
            provider=s.provider,
            created_at=s.created_at,
        )


@router.get(
    "/{entreprise_id}/daily-pulse",
    response_model=Optional[DailyBriefingOut],
    summary="Dernier daily briefing IA d'une entreprise (None si aucun)",
)
async def get_daily_pulse(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> Optional[DailyBriefingOut]:
    _require_volet(user)
    from app.models.qg_strategic import Summary, SummaryType

    s = (
        await db.execute(
            select(Summary)
            .where(
                Summary.entreprise_id == entreprise_id,
                Summary.type == SummaryType.DAILY_BRIEFING.value,
            )
            .order_by(Summary.period_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if s is None:
        return None
    return DailyBriefingOut.from_summary(s)


@router.post(
    "/{entreprise_id}/daily-pulse",
    response_model=Optional[DailyBriefingOut],
    summary="Génère (ou retourne celui du jour) le daily briefing IA",
)
async def generate_daily_pulse(
    entreprise_id: int,
    db: DBSession,
    user: CurrentUser,
    force: bool = False,
) -> Optional[DailyBriefingOut]:
    """Génération manuelle. Idempotent : un briefing par jour. Avec
    `?force=true`, écrase celui du jour pour régénération à la demande."""
    _require_volet(user)
    from app.services.qg_daily_pulse import generate_for_entreprise

    s = await generate_for_entreprise(db, entreprise_id, force=force)
    if s is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "IA indisponible ou entreprise introuvable.",
        )
    await db.commit()
    return DailyBriefingOut.from_summary(s)


# ── Scoring proactif IA ─────────────────────────────────────────────────


# ── Global pulse — briefing IA cross-entreprise ─────────────────


class GlobalBriefingOut(BaseModel):
    headline: str
    summary_text: str
    highlights: List[str] = Field(default_factory=list)
    model_used: Optional[str] = None
    provider: Optional[str] = None
    created_at: datetime
    period_start: datetime
    period_end: datetime


@router.get(
    "/global-pulse",
    response_model=Optional[GlobalBriefingOut],
    summary="Briefing IA global toutes entreprises + deals (cache jour)",
)
async def get_global_pulse(
    db: DBSession,
    user: CurrentUser,
    force: bool = False,
    scope: str = "all",
) -> Optional[GlobalBriefingOut]:
    """`scope=all` (défaut) : briefing global cross-entreprise.
    `scope=mine` : briefing filtré aux tâches assignées au user
    connecté — utilisé par le bouton « Mes tâches » de la page
    Tâches agrégée."""
    _require_volet(user)
    from app.services.qg_global_pulse import get_or_generate_global_pulse

    user_filter: Optional[int] = None
    if scope == "mine":
        user_filter = getattr(user, "id", None)

    g = await get_or_generate_global_pulse(
        db, force=force, user_id=user_filter
    )
    if g is None:
        return None
    return GlobalBriefingOut(
        headline=g.headline,
        summary_text=g.summary_text,
        highlights=g.highlights,
        model_used=g.model_used,
        provider=g.provider,
        created_at=g.created_at,
        period_start=g.period_start,
        period_end=g.period_end,
    )


class TacheScoreSuggestion(BaseModel):
    impact: int = Field(..., ge=1, le=10)
    confidence: int = Field(..., ge=1, le=10)
    effort: int = Field(..., ge=1, le=10)
    rationale: str
    score: float
    provider: Optional[str] = None
    model: Optional[str] = None


class TacheScoreSuggestRequest(BaseModel):
    """Variante preview — pour les tâches qui n'existent pas encore.
    Permet d'appeler l'IA depuis le modal de création avant de saver."""

    entreprise_id: int
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    departement: Optional[str] = None
    due_date: Optional[date] = None


async def _build_score_suggestion(
    *,
    title: str,
    description: Optional[str],
    departement: Optional[str],
    due_date: Optional[date],
    entreprise_name: Optional[str],
    entreprise_description: Optional[str],
) -> TacheScoreSuggestion:
    import json as _json

    from app.integrations.ai import (
        AIProviderError,
        AIProviderUnavailable,
        complete,
    )

    parts = []
    if entreprise_name:
        parts.append(f"Entreprise : {entreprise_name}")
    if entreprise_description:
        parts.append(f"Contexte entreprise : {entreprise_description}")
    if departement:
        parts.append(f"Département : {departement}")
    if due_date:
        parts.append(f"Échéance prévue : {due_date.isoformat()}")
    parts.append(f"Titre de la tâche : {title}")
    if description:
        parts.append(f"Description : {description}")

    prompt = (
        "\n".join(parts)
        + "\n\nÉvalue cette tâche selon le framework ICE puis renvoie "
        "STRICTEMENT un JSON avec :\n"
        '  "impact" (entier 1-10) : effet sur revenu / risque / '
        "conformité (10 = critique pour l'entreprise)\n"
        '  "confidence" (entier 1-10) : à quel point on est sûr du '
        "résultat (10 = quasi-garanti)\n"
        '  "effort" (entier 1-10) : temps/ressources requis (10 = '
        "très lourd)\n"
        '  "rationale" (string, 2-3 phrases en français québécois) : '
        "pourquoi ces scores.\n\n"
        "Réponds UNIQUEMENT avec le JSON, sans markdown."
    )
    system = (
        "Tu es un consultant stratégique. Tu évalues la priorité des "
        "tâches d'entreprise de façon factuelle, sans flatterie. "
        "Conservateur sur la confiance ; rigoureux sur l'effort."
    )

    try:
        res = await complete(
            prompt=prompt, system=system, max_tokens=350, temperature=0.3
        )
    except AIProviderUnavailable as exc:
        raise HTTPException(503, str(exc))
    except AIProviderError as exc:
        raise HTTPException(502, str(exc))

    raw = res.text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
    raw = raw.strip()

    try:
        parsed = _json.loads(raw)
        impact = max(1, min(10, int(parsed["impact"])))
        confidence = max(1, min(10, int(parsed["confidence"])))
        effort = max(1, min(10, int(parsed["effort"])))
        rationale = str(parsed.get("rationale") or "").strip()[:1000]
    except Exception as exc:
        raise HTTPException(
            502,
            f"Réponse IA non parsable : {exc}. Brut : {res.text[:200]}",
        )

    score = round((impact * confidence) / max(effort, 1), 2)
    return TacheScoreSuggestion(
        impact=impact,
        confidence=confidence,
        effort=effort,
        rationale=rationale,
        score=score,
        provider=res.provider,
        model=res.model,
    )


@router.post(
    "/taches/suggest-score",
    response_model=TacheScoreSuggestion,
    summary="Suggère un score ICE depuis un draft de tâche (preview, sans DB)",
)
async def suggest_score_preview(
    body: TacheScoreSuggestRequest,
    db: DBSession,
    user: CurrentUser,
) -> TacheScoreSuggestion:
    _require_volet(user)
    ent = (
        await db.execute(
            select(Entreprise).where(Entreprise.id == body.entreprise_id)
        )
    ).scalar_one_or_none()
    return await _build_score_suggestion(
        title=body.title,
        description=body.description,
        departement=body.departement,
        due_date=body.due_date,
        entreprise_name=ent.name if ent else None,
        entreprise_description=ent.description if ent else None,
    )


@router.post(
    "/taches/{tache_id}/suggest-score",
    response_model=TacheScoreSuggestion,
    summary="Suggère un score ICE pour une tâche existante (par id)",
)
async def suggest_score_by_id(
    tache_id: int, db: DBSession, user: CurrentUser
) -> TacheScoreSuggestion:
    _require_volet(user)
    t = (
        await db.execute(
            select(EntrepriseTache).where(EntrepriseTache.id == tache_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "Tâche non trouvée")
    ent = (
        await db.execute(
            select(Entreprise).where(Entreprise.id == t.entreprise_id)
        )
    ).scalar_one_or_none()
    return await _build_score_suggestion(
        title=t.title,
        description=t.description,
        departement=t.departement,
        due_date=t.due_date,
        entreprise_name=ent.name if ent else None,
        entreprise_description=ent.description if ent else None,
    )


# ── Index sémantique (recherche IA) ─────────────────────────────────────


class ReindexResponse(BaseModel):
    indexed: int
    skipped: int


@router.post(
    "/{entreprise_id}/reindex",
    response_model=ReindexResponse,
    summary="(Re)indexe toutes les tâches d'une entreprise pour la recherche IA",
)
async def reindex_entreprise(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> ReindexResponse:
    _require_volet(user)
    from app.services.qg_embeddings import index_entity

    rows = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.entreprise_id == entreprise_id
            )
        )
    ).scalars().all()
    indexed = 0
    skipped = 0
    for t in rows:
        text = (t.title or "") + (
            "\n" + t.description if t.description else ""
        )
        e = await index_entity(
            db,
            entreprise_id=entreprise_id,
            source_type="tache",
            source_id=t.id,
            content=text,
        )
        if e is None:
            skipped += 1
        else:
            indexed += 1
    await db.commit()
    return ReindexResponse(indexed=indexed, skipped=skipped)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)


class SearchHitOut(BaseModel):
    source_type: str
    source_id: int
    content: str
    similarity: float


@router.post(
    "/{entreprise_id}/search",
    response_model=List[SearchHitOut],
    summary="Recherche sémantique dans les entités indexées d'une entreprise",
)
async def search_entreprise(
    entreprise_id: int,
    body: SearchRequest,
    db: DBSession,
    user: CurrentUser,
) -> List[SearchHitOut]:
    _require_volet(user)
    from app.services.qg_embeddings import search_similar

    hits = await search_similar(
        db,
        entreprise_id=entreprise_id,
        query=body.query,
        limit=body.limit,
    )
    return [SearchHitOut(**h.__dict__) for h in hits]


class GlobalSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=30)


class GlobalSearchHitOut(BaseModel):
    source_type: str
    source_id: int
    entreprise_id: Optional[int] = None
    entreprise_name: Optional[str] = None
    entreprise_color: Optional[str] = None
    title: str
    snippet: str
    similarity: float


@router.post(
    "/search",
    response_model=List[GlobalSearchHitOut],
    summary="Recherche sémantique cross-entreprises (command bar ⌘K)",
)
async def search_global(
    body: GlobalSearchRequest, db: DBSession, user: CurrentUser
) -> List[GlobalSearchHitOut]:
    """Sert la barre de commande ⌘K. Cherche dans toutes les
    entreprises, joint le nom + couleur + titre vrai depuis les
    tables d'origine pour un affichage propre dans l'overlay."""
    _require_volet(user)
    from app.services.qg_embeddings import search_similar

    hits = await search_similar(
        db,
        entreprise_id=None,  # global
        query=body.query,
        limit=body.limit,
    )
    if not hits:
        return []

    # Précharge les entités d'origine + entreprises pour un affichage
    # propre (titre court + nom entreprise + couleur).
    tache_ids = [h.source_id for h in hits if h.source_type == "tache"]
    summary_ids = [h.source_id for h in hits if h.source_type == "summary"]

    taches_by_id: dict[int, EntrepriseTache] = {}
    if tache_ids:
        rows = (
            await db.execute(
                select(EntrepriseTache).where(
                    EntrepriseTache.id.in_(tache_ids)
                )
            )
        ).scalars().all()
        taches_by_id = {t.id: t for t in rows}

    from app.models.qg_strategic import Summary

    summaries_by_id: dict[int, Summary] = {}
    if summary_ids:
        rows = (
            await db.execute(
                select(Summary).where(Summary.id.in_(summary_ids))
            )
        ).scalars().all()
        summaries_by_id = {s.id: s for s in rows}

    ent_ids = {
        t.entreprise_id for t in taches_by_id.values()
    } | {
        s.entreprise_id for s in summaries_by_id.values()
    }
    ents_by_id: dict[int, Entreprise] = {}
    if ent_ids:
        rows = (
            await db.execute(
                select(Entreprise).where(Entreprise.id.in_(ent_ids))
            )
        ).scalars().all()
        ents_by_id = {e.id: e for e in rows}

    out: List[GlobalSearchHitOut] = []
    for h in hits:
        title = h.content[:120]
        snippet = h.content[:200]
        ent_id: Optional[int] = None
        if h.source_type == "tache" and h.source_id in taches_by_id:
            t = taches_by_id[h.source_id]
            title = t.title
            snippet = t.description or t.title
            ent_id = t.entreprise_id
        elif h.source_type == "summary" and h.source_id in summaries_by_id:
            s = summaries_by_id[h.source_id]
            title = s.headline
            snippet = s.summary_text
            ent_id = s.entreprise_id
        ent = ents_by_id.get(ent_id) if ent_id else None
        out.append(GlobalSearchHitOut(
            source_type=h.source_type,
            source_id=h.source_id,
            entreprise_id=ent_id,
            entreprise_name=ent.name if ent else None,
            entreprise_color=ent.color_accent if ent else None,
            title=title,
            snippet=snippet,
            similarity=round(h.similarity, 3),
        ))
    return out


