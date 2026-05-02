"""Volet Gestion d'entreprises — CRUD entreprises + tâches + import Monday.

Restreint au volet `entreprises` (whitelist côté User.volets).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

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
    TacheImportResult,
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


def _to_tache_read(t: EntrepriseTache) -> EntrepriseTacheRead:
    out = EntrepriseTacheRead.model_validate(t)
    out.score = _compute_score(t)
    return out


# ── Entreprises CRUD ────────────────────────────────────────────────────


@router.get("", response_model=List[EntrepriseRead])
async def list_entreprises(
    db: DBSession, user: CurrentUser
) -> List[EntrepriseRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(Entreprise).order_by(Entreprise.name.asc())
        )
    ).scalars().all()
    return [EntrepriseRead.model_validate(e) for e in rows]


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


# ── Tâches CRUD ─────────────────────────────────────────────────────────


@router.get("/taches", response_model=List[EntrepriseTacheRead])
async def list_taches(
    db: DBSession,
    user: CurrentUser,
    entreprise_id: Optional[int] = None,
    status_filter: Optional[str] = None,
) -> List[EntrepriseTacheRead]:
    _require_volet(user)
    stmt = select(EntrepriseTache)
    if entreprise_id is not None:
        stmt = stmt.where(EntrepriseTache.entreprise_id == entreprise_id)
    if status_filter:
        stmt = stmt.where(EntrepriseTache.status == status_filter)
    stmt = stmt.order_by(
        EntrepriseTache.due_date.asc().nullslast(),
        EntrepriseTache.id.desc(),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_tache_read(t) for t in rows]


@router.post(
    "/taches",
    response_model=EntrepriseTacheRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_tache(
    body: EntrepriseTacheCreate, db: DBSession, user: CurrentUser
) -> EntrepriseTacheRead:
    _require_volet(user)
    t = EntrepriseTache(**body.model_dump())
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return _to_tache_read(t)


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
    for k, v in payload.items():
        setattr(t, k, v)
    await db.flush()
    await db.refresh(t)
    return _to_tache_read(t)


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


# ── Import Monday ───────────────────────────────────────────────────────


class MondayImportRequest(BaseModel):
    """Importe les boards d'un (ou plusieurs) workspace Monday comme
    entreprises + leurs items comme tâches."""

    workspace_id: Optional[int] = Field(
        default=None,
        description=(
            "ID du workspace Monday à importer. Si omis, importe tous "
            "les workspaces accessibles au token. Visible dans l'URL "
            "Monday : /workspace/123456789."
        ),
    )
    board_name_filter: Optional[str] = Field(
        default=None,
        description=(
            "Si fourni, ne traite que les boards dont le nom contient "
            "ce texte (insensible à la casse). Ex. 'Tâche' pour ne "
            "garder que les boards de tâches."
        ),
    )


@router.post(
    "/import-monday-tasks",
    response_model=TacheImportResult,
    summary="Importe les boards Monday en tant qu'entreprises + tâches",
)
async def import_monday_tasks(
    body: MondayImportRequest, db: DBSession, user: CurrentUser
) -> TacheImportResult:
    """Idempotent : ré-exécutable sans créer de doublons grâce à
    Entreprise.monday_board_id et EntrepriseTache.monday_item_id.

    Requiert MONDAY_API_TOKEN configuré côté serveur.
    """
    _require_volet(user)
    try:
        from app.integrations.monday_client import MondayClient
    except Exception as exc:
        raise HTTPException(500, f"Import indisponible : {exc}")

    workspace_ids = [body.workspace_id] if body.workspace_id else None
    name_filter = (body.board_name_filter or "").strip().lower()

    result = TacheImportResult(
        boards_processed=0,
        entreprises_created=0,
        entreprises_updated=0,
        taches_created=0,
        taches_updated=0,
    )

    try:
        async with MondayClient() as mc:
            boards = await mc.list_boards(workspace_ids=workspace_ids)
            if name_filter:
                boards = [
                    b for b in boards
                    if name_filter in (b.get("name") or "").lower()
                ]

            for b in boards:
                board_id = str(b.get("id"))
                board_name = b.get("name") or f"Board {board_id}"
                ws = b.get("workspace") or {}
                ws_name = ws.get("name") or ""

                # Upsert entreprise
                ent = (
                    await db.execute(
                        select(Entreprise).where(
                            Entreprise.monday_board_id == board_id
                        )
                    )
                ).scalar_one_or_none()
                if ent is None:
                    ent = Entreprise(
                        name=board_name,
                        monday_board_id=board_id,
                        monday_board_name=board_name,
                        description=(
                            f"Importée depuis Monday — workspace « {ws_name} »"
                            if ws_name else "Importée depuis Monday"
                        ),
                    )
                    db.add(ent)
                    await db.flush()
                    await db.refresh(ent)
                    result.entreprises_created += 1
                else:
                    # Met à jour le nom si modifié dans Monday
                    if ent.monday_board_name != board_name:
                        ent.monday_board_name = board_name
                        result.entreprises_updated += 1

                # Items du board
                try:
                    items = await mc.paged_items(int(board_id))
                except Exception as exc:
                    result.errors.append(
                        f"Board {board_name} : items inaccessibles ({exc})"
                    )
                    continue

                for it in items:
                    item_id = str(it.get("id"))
                    title = (it.get("name") or "").strip() or f"Item {item_id}"
                    group = (it.get("group") or {}).get("title") or None

                    existing = (
                        await db.execute(
                            select(EntrepriseTache).where(
                                EntrepriseTache.monday_item_id == item_id
                            )
                        )
                    ).scalar_one_or_none()

                    if existing is None:
                        t = EntrepriseTache(
                            entreprise_id=ent.id,
                            title=title[:255],
                            monday_item_id=item_id,
                            monday_board_id=board_id,
                            monday_group_title=group,
                            status=_guess_status_from_group(group),
                        )
                        db.add(t)
                        result.taches_created += 1
                    else:
                        # Mise à jour des champs qui peuvent bouger
                        if existing.title != title[:255]:
                            existing.title = title[:255]
                        if existing.monday_group_title != group:
                            existing.monday_group_title = group
                        # Si la tâche a été ré-attribuée à un autre board
                        if existing.entreprise_id != ent.id:
                            existing.entreprise_id = ent.id
                        result.taches_updated += 1

                result.boards_processed += 1

            await db.commit()
    except RuntimeError as exc:
        # Token absent ou erreur GraphQL non-récupérable
        raise HTTPException(502, str(exc))

    return result


def _guess_status_from_group(group: Optional[str]) -> str:
    """Heuristique : déduit un statut à partir du nom du groupe Monday.
    Conservateur : tout ce qui n'est pas évident → backlog."""
    if not group:
        return TacheStatus.BACKLOG.value
    g = group.lower()
    if any(k in g for k in ("done", "termin", "complet", "fait")):
        return TacheStatus.DONE.value
    if any(k in g for k in ("progress", "en cours", "doing")):
        return TacheStatus.IN_PROGRESS.value
    if any(k in g for k in ("attente", "wait", "block", "stuck")):
        return TacheStatus.WAITING.value
    if any(k in g for k in ("todo", "à faire", "a faire", "this week", "semaine")):
        return TacheStatus.TODO.value
    return TacheStatus.BACKLOG.value


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
    db: DBSession, user: CurrentUser
) -> List[EntrepriseHealth]:
    _require_volet(user)
    from app.models.qg_strategic import Summary, SummaryType

    ents = (
        await db.execute(
            select(Entreprise)
            .where(Entreprise.is_active.is_(True))
            .order_by(Entreprise.name.asc())
        )
    ).scalars().all()

    today = date.today()
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

        # Score 0-100 :
        # - 100 = aucune tâche, ou toutes faites à temps
        # - pénalités : -8 par overdue, -3 par urgent, plafonné à -60
        # - bonus si haut taux done/total
        if total == 0:
            score = 100
        else:
            done_ratio = done / total
            penalty = min(60, 8 * overdue + 3 * urgent)
            score = max(20, int(100 * done_ratio + (1 - done_ratio) * 70 - penalty))

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


@router.get(
    "/monday-workspaces",
    summary="Liste les workspaces Monday accessibles (debug import)",
)
async def list_monday_workspaces(user: CurrentUser) -> dict:
    """Outil de découverte : liste les workspaces visibles avec le
    token serveur courant. Utilisé pour identifier l'ID du workspace
    « Horizon services immobiliers » avant l'import."""
    _require_volet(user)
    try:
        from app.integrations.monday_client import MondayClient
    except Exception as exc:
        raise HTTPException(500, f"Indisponible : {exc}")
    try:
        async with MondayClient() as mc:
            ws = await mc.list_workspaces()
            boards = await mc.list_boards()
        return {
            "workspaces": ws,
            "boards": boards,
        }
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
