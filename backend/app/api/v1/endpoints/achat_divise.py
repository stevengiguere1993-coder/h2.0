"""Reçu DIVISÉ entre plusieurs projets (Steven 2026-10-30).

    POST /api/v1/achats/divise — un achat par projet, liés par groupe_id,
    poussés vers QuickBooks comme UNE transaction à une ligne par projet.

Voir services/achat_divise.py (répartition) et services/achat_qbo.py
(push de groupe).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel

from app.api.deps import DBSession, RequireManager
from app.schemas.business import AchatDiviseCreate, AchatRead
from app.services.achat_divise import DivisionErreur, creer_achat_divise


log = logging.getLogger(__name__)
router = APIRouter(prefix="/achats", tags=["achats-divise"])


class AchatDiviseRead(BaseModel):
    """Les parts créées (la tête en premier) et leur groupe."""

    groupe_id: int
    parts: list[AchatRead]


@router.post(
    "/divise",
    status_code=status.HTTP_201_CREATED,
    response_model=AchatDiviseRead,
    summary=(
        "Créer un reçu divisé entre plusieurs projets : un achat par projet "
        "(HT et taxes au prorata), une seule transaction QuickBooks à une "
        "ligne par projet"
    ),
)
async def creer_recu_divise(
    data: AchatDiviseCreate,
    db: DBSession,
    user: RequireManager,
    background: BackgroundTasks,
) -> AchatDiviseRead:
    try:
        parts = await creer_achat_divise(db, data, user_id=user.id)
    except DivisionErreur as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    tete = parts[0]
    # Push QuickBooks du GROUPE (une transaction, une ligne par part) dès
    # que le reçu est actif. On COMMITTE d'abord : la tâche de fond ouvre
    # sa propre session et doit voir les parts (sinon « achat introuvable »
    # et le reçu attendrait le filet horaire).
    await db.commit()
    if tete.status in ("received", "paid"):
        from app.api.v1.endpoints.achat_qbo import autopush_achat

        background.add_task(autopush_achat, int(tete.id))
    return AchatDiviseRead(
        groupe_id=int(tete.groupe_id or tete.id),
        parts=[AchatRead.model_validate(a) for a in parts],
    )
