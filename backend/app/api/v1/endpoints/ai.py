"""Endpoints utilitaires pour la couche IA.

- ``GET /ai/health`` : status du provider courant (configuré ou non,
  test ping optionnel).
- ``POST /ai/ping`` : appel test ``complete()`` qui retourne le texte
  généré + le provider utilisé. Sert de vérification de bout en bout.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.integrations.ai import (
    AIProviderError,
    AIProviderUnavailable,
    complete,
    current_provider,
    embed,
    is_configured,
)


log = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


class AIHealthResponse(BaseModel):
    configured: bool
    provider: str
    embedding_provider: Optional[str] = None
    note: Optional[str] = None


@router.get(
    "/health",
    response_model=AIHealthResponse,
    summary="État de la couche IA (provider configuré ou non)",
)
async def ai_health(_: CurrentUser) -> AIHealthResponse:
    if not is_configured():
        return AIHealthResponse(
            configured=False,
            provider="(aucun)",
            note=(
                "Aucun provider IA configuré. Définis GEMINI_API_KEY "
                "(gratuit, recommandé) sur Render."
            ),
        )
    try:
        from app.integrations.ai import embedding_provider

        emb = embedding_provider().name
    except AIProviderUnavailable:
        emb = None
    return AIHealthResponse(
        configured=True,
        provider=current_provider(),
        embedding_provider=emb,
    )


class AIPingRequest(BaseModel):
    prompt: str = Field(
        default="Réponds 'pong' en un seul mot.",
        max_length=500,
    )


class AIPingResponse(BaseModel):
    text: str
    provider: str
    model: str
    latency_ms: int
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


@router.post(
    "/ping",
    response_model=AIPingResponse,
    summary="Appel test bout-en-bout (1 requête de validation)",
)
async def ai_ping(body: AIPingRequest, _: CurrentUser) -> AIPingResponse:
    t0 = time.perf_counter()
    try:
        res = await complete(prompt=body.prompt, max_tokens=64)
    except AIProviderUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)
        )
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    latency = int((time.perf_counter() - t0) * 1000)
    return AIPingResponse(
        text=res.text,
        provider=res.provider,
        model=res.model,
        latency_ms=latency,
        input_tokens=res.input_tokens,
        output_tokens=res.output_tokens,
    )


class AIEmbedRequest(BaseModel):
    text: str = Field(..., max_length=10_000)


class AIEmbedResponse(BaseModel):
    dimension: int
    provider: str
    model: str
    # On ne renvoie que les 8 premières dimensions (debug visuel) +
    # la longueur — pas le vecteur complet pour ne pas bourrer le UI.
    preview: list[float]


@router.post(
    "/embed-test",
    response_model=AIEmbedResponse,
    summary="Test d'embedding (retourne dimension + 8 premières valeurs)",
)
async def ai_embed_test(
    body: AIEmbedRequest, _: CurrentUser
) -> AIEmbedResponse:
    try:
        res = await embed(body.text)
    except AIProviderUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)
        )
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    return AIEmbedResponse(
        dimension=res.dimension,
        provider=res.provider,
        model=res.model,
        preview=res.values[:8],
    )
