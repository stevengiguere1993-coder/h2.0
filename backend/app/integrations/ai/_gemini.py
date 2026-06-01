"""Provider Gemini (Google AI Studio) — défaut gratuit.

API REST directe via httpx — évite la dépendance lourde
``google-generativeai``. Endpoints utilisés :

- ``models/gemini-2.0-flash:generateContent`` pour completion / chat
- ``models/text-embedding-004:embedContent`` pour embeddings (768-dim)

Tier gratuit (au moment de l'écriture) :
- Gemini 2.0 Flash : 15 req/min, 1 M tokens/jour
- text-embedding-004 : illimité pour usage normal
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

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"
    default_completion_model = "gemini-2.5-flash"
    default_embedding_model = "text-embedding-004"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()

    def _check_key(self) -> None:
        if not self.api_key:
            raise AIProviderUnavailable(
                "GEMINI_API_KEY non configurée. Crée une clé sur "
                "https://aistudio.google.com/apikey et configure-la "
                "comme env var côté Render."
            )

    # ---------- completion (single-turn) ----------

    async def complete(
        self,
        *,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
        thinking_budget: Optional[int] = None,
    ) -> CompletionResult:
        return await self.chat(
            messages=[Message(role="user", content=prompt)],
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
            thinking_budget=thinking_budget,
        )

    # ---------- chat (multi-turn) ----------

    async def chat(
        self,
        *,
        messages: List[Message],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
        thinking_budget: Optional[int] = None,
    ) -> CompletionResult:
        self._check_key()
        model = model or os.getenv("AI_MODEL") or self.default_completion_model

        contents = []
        for m in messages:
            # Gemini distingue user/model (pas assistant)
            role = "model" if m.role == "assistant" else "user"
            contents.append(
                {"role": role, "parts": [{"text": m.content}]}
            )

        generation_config: dict = {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        }
        # Modèles « thinking » (gemini-2.5-*) : sans plafond, le
        # raisonnement interne mange le budget maxOutputTokens et la
        # réponse visible est tronquée. thinking_budget=0 le désactive
        # pour que tout le budget serve à la sortie. None = défaut du
        # modèle (inchangé). Champ ignoré par les modèles sans thinking.
        if thinking_budget is not None:
            generation_config["thinkingConfig"] = {
                "thinkingBudget": thinking_budget
            }

        payload = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system:
            payload["systemInstruction"] = {
                "parts": [{"text": system}]
            }

        url = (
            f"{GEMINI_BASE}/models/{model}:generateContent"
            f"?key={self.api_key}"
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                raise AIProviderError(
                    f"Gemini HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:300]}"
                ) from exc
            except httpx.HTTPError as exc:
                raise AIProviderError(f"Gemini réseau : {exc}") from exc

        try:
            text = (
                data["candidates"][0]["content"]["parts"][0]["text"]
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                f"Gemini : réponse inattendue → {data}"
            ) from exc

        usage = data.get("usageMetadata") or {}
        return CompletionResult(
            text=text.strip(),
            model=model,
            provider=self.name,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            raw=data,
        )

    # ---------- embeddings ----------

    async def embed(
        self,
        *,
        text: str,
        model: Optional[str] = None,
    ) -> EmbeddingResult:
        self._check_key()
        model = (
            model
            or os.getenv("AI_EMBEDDING_MODEL")
            or self.default_embedding_model
        )
        payload = {"content": {"parts": [{"text": text}]}}
        url = (
            f"{GEMINI_BASE}/models/{model}:embedContent"
            f"?key={self.api_key}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                raise AIProviderError(
                    f"Gemini embed HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:300]}"
                ) from exc
            except httpx.HTTPError as exc:
                raise AIProviderError(
                    f"Gemini embed réseau : {exc}"
                ) from exc

        try:
            values = data["embedding"]["values"]
        except (KeyError, TypeError) as exc:
            raise AIProviderError(
                f"Gemini embed : réponse inattendue → {data}"
            ) from exc

        return EmbeddingResult(
            values=values,
            dimension=len(values),
            model=model,
            provider=self.name,
        )
