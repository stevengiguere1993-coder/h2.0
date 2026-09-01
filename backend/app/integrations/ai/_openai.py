"""Provider OpenAI (GPT) — chantier « IA personnelle » (sept. 2026).

Activé par ``OPENAI_API_KEY`` (env) ou par la clé PERSONNELLE d'un
utilisateur (services/user_ai.py). Même contrat que les autres
providers ; pas d'embedding (le factory route vers Gemini).
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

OPENAI_BASE = "https://api.openai.com/v1"


class OpenAIProvider:
    name = "openai"
    default_completion_model = "gpt-4o"
    default_embedding_model = ""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()

    def _check_key(self) -> None:
        if not self.api_key:
            raise AIProviderUnavailable("OPENAI_API_KEY non configurée.")

    async def complete(
        self,
        *,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
        **_kwargs: object,
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
        **_kwargs: object,
    ) -> CompletionResult:
        self._check_key()
        model = model or os.getenv("AI_MODEL") or self.default_completion_model

        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant", "system")
        )
        body: dict = {
            "model": model,
            "messages": msgs,
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(
                    f"{OPENAI_BASE}/chat/completions",
                    json=body,
                    headers=headers,
                )
                if resp.status_code == 400 and "max_completion_tokens" in (
                    resp.text or ""
                ):
                    # Anciens modèles : le paramètre s'appelle max_tokens.
                    body.pop("max_completion_tokens", None)
                    body["max_tokens"] = max_tokens
                    resp = await client.post(
                        f"{OPENAI_BASE}/chat/completions",
                        json=body,
                        headers=headers,
                    )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                raise AIProviderError(
                    f"OpenAI HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:300]}"
                ) from exc
            except httpx.HTTPError as exc:
                raise AIProviderError(f"OpenAI réseau : {exc}") from exc

        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                f"OpenAI : réponse inattendue → {data}"
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

    async def embed(
        self, *, text: str, model: Optional[str] = None
    ) -> EmbeddingResult:
        raise AIProviderUnavailable(
            "Embeddings non branchés pour OpenAI — le factory route "
            "vers Gemini."
        )
