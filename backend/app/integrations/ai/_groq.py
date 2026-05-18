"""Provider Groq (Llama 3.3 70B) — fallback gratuit ultra-rapide.

Active dès que ``GROQ_API_KEY`` est configurée. Idéal en backup quand
Gemini rate-limit. Pas d'API embedding natif chez Groq — on retombe
sur Gemini pour les embeddings dans ce cas.
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

GROQ_BASE = "https://api.groq.com/openai/v1"


class GroqProvider:
    name = "groq"
    default_completion_model = "llama-3.3-70b-versatile"
    default_embedding_model = ""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = (api_key or os.getenv("GROQ_API_KEY") or "").strip()

    def _check_key(self) -> None:
        if not self.api_key:
            raise AIProviderUnavailable("GROQ_API_KEY non configurée.")

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

        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        for m in messages:
            if m.role in ("user", "assistant", "system"):
                msgs.append({"role": m.role, "content": m.content})

        body = {
            "model": model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(
                    f"{GROQ_BASE}/chat/completions",
                    json=body,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                raise AIProviderError(
                    f"Groq HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:300]}"
                ) from exc
            except httpx.HTTPError as exc:
                raise AIProviderError(f"Groq réseau : {exc}") from exc

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                f"Groq : réponse inattendue → {data}"
            ) from exc

        usage = data.get("usage") or {}
        return CompletionResult(
            text=text.strip(),
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            raw=data,
        )

    async def embed(self, *, text: str, model: Optional[str] = None) -> EmbeddingResult:
        raise AIProviderUnavailable(
            "Groq ne fournit pas d'API embedding native."
        )
