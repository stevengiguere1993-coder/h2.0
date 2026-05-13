"""Endpoints Kratos — routeur d'intentions + inbox + problèmes proactifs.

Routage :
  POST /api/v1/kratos/route        — soumet un texte, route + inbox entry
  GET  /api/v1/kratos/inbox        — liste paginée des entrées récentes
  POST /api/v1/kratos/{id}/confirm — applique manuellement un routage
  POST /api/v1/kratos/{id}/discard — marque un message comme rejeté

Problèmes (Phase 4) :
  POST /api/v1/kratos/scan/{entreprise_id}   — lance un scan IA on-demand
  GET  /api/v1/kratos/problems               — liste les problèmes ouverts
  POST /api/v1/kratos/problems/{id}/apply    — applique la solution
  POST /api/v1/kratos/problems/{id}/dismiss  — rejette le problème
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.kratos_message import (
    KratosIntentKind,
    KratosMessage,
    KratosMessageStatus,
)
from app.models.kratos_problem import KratosProblem, KratosProblemStatus
from app.services.kratos_problem_detector import (
    apply_solution,
    detect_for_entreprise,
)
from app.services.kratos_router import route_text


log = logging.getLogger(__name__)

router = APIRouter(prefix="/kratos", tags=["kratos"])


class KratosRouteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000)


class KratosMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: Optional[int]
    original_text: str
    intent_kind: str
    summary: Optional[str]
    target_type: Optional[str]
    target_id: Optional[int]
    status: str
    intent_json: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]


@router.post(
    "/route",
    response_model=KratosMessageRead,
    summary="Route une entrée vers le bon endroit via Claude",
)
async def route(
    data: KratosRouteRequest,
    db: DBSession,
    user: CurrentUser,
) -> KratosMessageRead:
    try:
        msg = await route_text(db, user, data.text)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Kratos /route failed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"kratos_route_failed: {type(exc).__name__}",
        ) from exc
    await db.commit()
    return KratosMessageRead.model_validate(msg)


@router.get(
    "/inbox",
    response_model=List[KratosMessageRead],
    summary="Inbox Kratos — liste paginée des entrées récentes",
)
async def inbox(
    db: DBSession,
    user: CurrentUser,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> List[KratosMessageRead]:
    stmt = (
        select(KratosMessage)
        .order_by(KratosMessage.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(KratosMessage.status == status_filter)
    # Pour l'instant, chaque user voit ses propres messages OU les
    # messages système (user_id NULL). Les admins voient tout.
    if (getattr(user, "role", "") or "").lower() not in ("owner", "admin"):
        stmt = stmt.where(
            (KratosMessage.user_id == user.id)
            | (KratosMessage.user_id.is_(None))
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [KratosMessageRead.model_validate(r) for r in rows]


@router.post(
    "/{msg_id}/discard",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Rejeter un message (manual discard)",
)
async def discard(
    msg_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    msg = (
        await db.execute(
            select(KratosMessage).where(KratosMessage.id == msg_id)
        )
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message introuvable.")
    msg.status = KratosMessageStatus.DISCARDED.value
    await db.commit()


class ConfirmRequest(BaseModel):
    """Manual override d'un routage. Pour l'instant on supporte juste
    le ré-attachement à une entité explicite (entreprise_id, lead_id…).
    Phase 2+ : ré-router complètement."""

    target_type: str = Field(..., max_length=48)
    target_id: int


@router.post(
    "/{msg_id}/confirm",
    response_model=KratosMessageRead,
    summary="Confirmer manuellement le routage d'un message",
)
async def confirm(
    msg_id: int,
    data: ConfirmRequest,
    db: DBSession,
    _: CurrentUser,
) -> KratosMessageRead:
    msg = (
        await db.execute(
            select(KratosMessage).where(KratosMessage.id == msg_id)
        )
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message introuvable.")
    msg.target_type = data.target_type
    msg.target_id = data.target_id
    msg.status = KratosMessageStatus.ROUTED.value
    await db.commit()
    await db.refresh(msg)
    return KratosMessageRead.model_validate(msg)


# ─── Phase 4 — Problèmes proactifs ──────────────────────────────────


class KratosProblemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # entreprise_id devient OPTIONNEL : un problème peut être transverse.
    entreprise_id: Optional[int] = None
    problem_text: Optional[str] = None
    title: str
    description: Optional[str]
    severity: str
    solution_plan: Optional[str] = None
    solution_steps_json: Optional[str] = None
    suggested_action_kind: Optional[str]
    suggested_action_label: Optional[str]
    suggested_action_params: Optional[str]
    status: str
    applied_target_type: Optional[str]
    applied_target_id: Optional[int]
    created_at: datetime
    resolved_at: Optional[datetime]


@router.post(
    "/scan/{entreprise_id}",
    response_model=List[KratosProblemRead],
    summary="Détecte les problèmes pour une entreprise (on-demand)",
)
async def scan_entreprise(
    entreprise_id: int,
    db: DBSession,
    _: CurrentUser,
    force: bool = Query(default=False),
) -> List[KratosProblemRead]:
    try:
        created = await detect_for_entreprise(
            db, entreprise_id, force=force
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("Kratos scan failed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"kratos_scan_failed: {type(exc).__name__}",
        ) from exc
    return [KratosProblemRead.model_validate(p) for p in created]


@router.get(
    "/problems",
    response_model=List[KratosProblemRead],
    summary="Liste les problèmes Kratos (filtrable par entreprise/statut)",
)
async def list_problems(
    db: DBSession,
    _: CurrentUser,
    entreprise_id: Optional[int] = Query(default=None),
    status_filter: Optional[str] = Query(default="open", alias="status"),
    limit: int = Query(default=100, ge=1, le=300),
) -> List[KratosProblemRead]:
    stmt = (
        select(KratosProblem)
        .order_by(KratosProblem.created_at.desc())
        .limit(limit)
    )
    if entreprise_id is not None:
        stmt = stmt.where(KratosProblem.entreprise_id == entreprise_id)
    if status_filter and status_filter != "all":
        stmt = stmt.where(KratosProblem.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    return [KratosProblemRead.model_validate(r) for r in rows]


@router.post(
    "/problems/{problem_id}/apply",
    response_model=KratosProblemRead,
    summary="Applique la solution suggérée (ex. crée la tâche proposée)",
)
async def apply_problem(
    problem_id: int,
    db: DBSession,
    user: CurrentUser,
) -> KratosProblemRead:
    problem = await apply_solution(db, problem_id, user_id=user.id)
    if problem is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Problème introuvable."
        )
    await db.commit()
    return KratosProblemRead.model_validate(problem)


@router.post(
    "/problems/{problem_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Rejette un problème (manual dismiss)",
)
async def dismiss_problem(
    problem_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    problem = (
        await db.execute(
            select(KratosProblem).where(KratosProblem.id == problem_id)
        )
    ).scalar_one_or_none()
    if problem is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Problème introuvable."
        )
    problem.status = KratosProblemStatus.DISMISSED.value
    problem.resolved_at = datetime.utcnow()
    await db.commit()


# ─── Problèmes user-driven (Phase 4 réorientée) ──────────────────────


class SolveProblemRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)


class KratosProblemWithSolutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    entreprise_id: Optional[int]
    problem_text: Optional[str]
    title: str
    description: Optional[str]
    severity: str
    solution_plan: Optional[str]
    solution_steps_json: Optional[str]
    suggested_action_kind: Optional[str]
    suggested_action_label: Optional[str]
    suggested_action_params: Optional[str]
    status: str
    applied_target_type: Optional[str]
    applied_target_id: Optional[int]
    created_at: datetime
    resolved_at: Optional[datetime]


@router.post(
    "/solve",
    response_model=KratosProblemWithSolutionRead,
    summary="L'utilisateur décrit un problème, Kratos propose un plan",
)
async def solve(
    data: SolveProblemRequest,
    db: DBSession,
    _: CurrentUser,
) -> KratosProblemWithSolutionRead:
    from app.services.kratos_problem_detector import solve_problem

    try:
        problem = await solve_problem(db, data.text)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Kratos /solve failed")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"kratos_solve_failed: {type(exc).__name__}",
        ) from exc
    return KratosProblemWithSolutionRead.model_validate(problem)
