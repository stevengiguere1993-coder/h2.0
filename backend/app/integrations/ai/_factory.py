"""Factory : choisit le provider à utiliser selon ``AI_PROVIDER``.

Garantie : les fonctions publiques ``complete()`` / ``chat()`` /
``embed()`` ne lèvent jamais ``AIProviderUnavailable`` quand
l'utilisateur a configuré au moins un provider — elles basculent
automatiquement sur le suivant disponible.

Pour les embeddings : si le provider de chat ne supporte pas
nativement les embeddings (Anthropic, Groq), on retombe
automatiquement sur Gemini (qui les fait gratuitement).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import List, Optional

from app.integrations.ai._anthropic import AnthropicProvider
from app.integrations.ai._base import (
    AIProvider,
    AIProviderUnavailable,
    CompletionResult,
    EmbeddingResult,
    Message,
)
from app.integrations.ai._gemini import GeminiProvider
from app.integrations.ai._groq import GroqProvider

log = logging.getLogger(__name__)


_PROVIDERS = {
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "claude": AnthropicProvider,  # alias
    "groq": GroqProvider,
}


@lru_cache(maxsize=1)
def _build_chain() -> List[AIProvider]:
    """Construit la chaîne de providers à essayer dans l'ordre.

    Le premier = celui demandé par ``AI_PROVIDER`` (gemini par défaut).
    Les suivants = les autres providers configurés, comme fallback en
    cas d'erreur réseau / rate limit.
    """
    requested = (os.getenv("AI_PROVIDER") or "gemini").strip().lower()
    chain: List[AIProvider] = []
    seen: set[str] = set()

    # 1. Provider explicitement demandé
    cls = _PROVIDERS.get(requested)
    if cls is not None:
        inst = cls()
        chain.append(inst)
        seen.add(inst.name)

    # 2. Tous les autres configurés (clé d'env présente) comme fallback
    for name, cls in _PROVIDERS.items():
        if name in ("claude",):
            continue  # alias d'anthropic, déjà vu
        inst = cls()
        if inst.name in seen:
            continue
        try:
            inst._check_key()  # type: ignore[attr-defined]
        except AIProviderUnavailable:
            continue
        chain.append(inst)
        seen.add(inst.name)

    return chain


def chat_provider() -> AIProvider:
    """Retourne le provider principal de chat (le 1er configuré)."""
    chain = _build_chain()
    if not chain:
        raise AIProviderUnavailable(
            "Aucun provider IA configuré. Définis au moins une de :"
            " GEMINI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY."
        )
    for p in chain:
        try:
            p._check_key()  # type: ignore[attr-defined]
            return p
        except AIProviderUnavailable:
            continue
    raise AIProviderUnavailable(
        "Aucun provider IA configuré (toutes les clés manquent)."
    )


def embedding_provider() -> AIProvider:
    """Retourne le provider à utiliser pour les embeddings.

    Anthropic et Groq n'ont pas d'API embedding native — dans ce cas
    on tombe sur Gemini si configuré.
    """
    chain = _build_chain()
    for p in chain:
        if p.default_embedding_model:
            try:
                p._check_key()  # type: ignore[attr-defined]
                return p
            except AIProviderUnavailable:
                continue
    raise AIProviderUnavailable(
        "Aucun provider d'embeddings disponible. Configure GEMINI_API_KEY."
    )


def current_provider() -> str:
    """Nom du provider actif (utile pour le UI / health endpoint)."""
    try:
        return chat_provider().name
    except AIProviderUnavailable:
        return "(aucun)"


def is_configured() -> bool:
    try:
        chat_provider()
        return True
    except AIProviderUnavailable:
        return False


# ---------- Public API : complete / chat / embed ----------


async def complete(
    *,
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    model: Optional[str] = None,
    thinking_budget: Optional[int] = None,
) -> CompletionResult:
    """Single-turn completion. Bascule automatiquement sur le provider
    suivant en cas d'erreur réseau / rate-limit.

    ``thinking_budget`` : budget de raisonnement interne (tokens) pour
    les modèles « thinking » comme gemini-2.5-flash. ``0`` le désactive
    pour que tout ``max_tokens`` serve à la réponse visible. Ignoré par
    les providers sans thinking (Groq, Anthropic)."""
    chain = _build_chain()
    last_err: Optional[Exception] = None
    for p in chain:
        try:
            return await p.complete(
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
                thinking_budget=thinking_budget,
            )
        except AIProviderUnavailable:
            continue
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log.warning(
                "AI provider %s failed (%s) — fallback", p.name, exc
            )
            continue
    if last_err:
        raise last_err
    raise AIProviderUnavailable("Aucun provider IA disponible.")


async def chat(
    *,
    messages: List[Message],
    system: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    model: Optional[str] = None,
    prefer: Optional[str] = None,
    thinking_budget: Optional[int] = None,
) -> CompletionResult:
    """Multi-turn chat. Mêmes garanties de fallback que ``complete()``.

    ``prefer`` : nom d'un provider (``"groq"``, ``"gemini"``…) à placer
    EN TÊTE de la chaîne, devant l'ordre habituel. Les autres restent
    disponibles en fallback. Utile pour les usages sensibles à la
    latence et au quota — ex. la secrétaire téléphonique vise Groq
    (gratuit, ultra-rapide) plutôt que Gemini (quota gratuit serré).

    ``thinking_budget`` : voir ``complete()``. Ignoré hors Gemini.
    """
    chain = _build_chain()
    if prefer:
        chain = sorted(chain, key=lambda p: 0 if p.name == prefer else 1)
    last_err: Optional[Exception] = None
    for p in chain:
        try:
            return await p.chat(
                messages=messages,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
                thinking_budget=thinking_budget,
            )
        except AIProviderUnavailable:
            continue
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log.warning(
                "AI provider %s failed (%s) — fallback", p.name, exc
            )
            continue
    if last_err:
        raise last_err
    raise AIProviderUnavailable("Aucun provider IA disponible.")


async def embed(
    text: str,
    *,
    model: Optional[str] = None,
) -> EmbeddingResult:
    """Embedding d'un texte. Route vers le provider d'embedding
    disponible (Gemini par défaut, peu importe ``AI_PROVIDER``)."""
    p = embedding_provider()
    return await p.embed(text=text, model=model)
