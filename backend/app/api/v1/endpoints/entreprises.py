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
