"""Provider Anthropic (Claude) — payant, stub fonctionnel.

Active dès que ``ANTHROPIC_API_KEY`` est configurée. Modèle par défaut
Claude Sonnet 4.6 (rapport qualité/prix). Pour Opus, surcharge via
``AI_MODEL=claude-opus-4-7``.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

import httpx

from app.integrations.ai._base import (
    AIProviderError,
    AIProviderUnavailable,
    CompletionResult,
    EmbeddingResult,
    Message,
)

log = logging.getLogger(__name__)

ANTHROPIC_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"
    default_completion_model = "claude-sonnet-4-6"
    # Anthropic n'a pas d'API embedding native — on retombe sur le
    # provider Gemini pour les embeddings dans ce cas. Géré au niveau
    # du factory.
    default_embedding_model = ""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()

    def _check_key(self) -> None:
        if not self.api_key:
            raise AIProviderUnavailable(
                "ANTHROPIC_API_KEY non configurée."
            )

    async def complete(
        self,
        *,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> CompletionResult:
        return await self.chat(
            messages=[Message(role="user", content=prompt)],
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
        )

    async def chat(
        self,
        *,
        messages: List[Message],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> CompletionResult:
        self._check_key()
        model = model or os.getenv("AI_MODEL") or self.default_completion_model

        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in messages
                if m.role in ("user", "assistant")
            ],
        }
        if system:
            body["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(
                    f"{ANTHROPIC_BASE}/messages",
                    json=body,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                raise AIProviderError(
                    f"Anthropic HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:300]}"
                ) from exc
            except httpx.HTTPError as exc:
                raise AIProviderError(f"Anthropic réseau : {exc}") from exc

        try:
            text = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                f"Anthropic : réponse inattendue → {data}"
            ) from exc

        usage = data.get("usage") or {}
        return CompletionResult(
            text=text.strip(),
            model=model,
            provider=self.name,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            raw=data,
        )

    async def embed(self, *, text: str, model: Optional[str] = None) -> EmbeddingResult:
        # Pas d'embedding natif — le factory route ailleurs.
        raise AIProviderUnavailable(
            "Anthropic ne fournit pas d'API embedding native."
        )
