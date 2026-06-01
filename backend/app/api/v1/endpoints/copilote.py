"""Copilote Kratos — endpoint de l'assistant interne (phase 1, lecture
seule). Le user connecté pose une question en langage naturel ; le
service `copilote` rassemble ses données (RDV + prospects) et l'IA
gratuite répond.

Accessible à tout utilisateur authentifié (`CurrentUser`). Le périmètre
des données est appliqué dans le service selon le rôle.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBSession
from app.services import copilote as copilote_service
from app.services.copilote import AIProviderError, AIProviderUnavailable

router = APIRouter(prefix="/copilote", tags=["copilote"])


class CopiloteAsk(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class CopiloteAnswer(BaseModel):
    answer: str
    provider: str
    model: str


@router.post(
    "/ask",
    response_model=CopiloteAnswer,
    summary="Pose une question au Copilote (répond depuis tes données)",
)
async def ask(
    payload: CopiloteAsk, user: CurrentUser, db: DBSession
) -> CopiloteAnswer:
    try:
        result = await copilote_service.answer_question(
            db, user=user, question=payload.question
        )
    except AIProviderUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Copilote indisponible : aucune IA configurée.",
        ) from exc
    except AIProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Copilote : erreur du fournisseur IA ({exc}).",
        ) from exc
    return CopiloteAnswer(**result)
