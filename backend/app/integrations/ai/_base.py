"""Interface commune que tous les providers IA doivent implémenter.

Garde-fou contre le lock-in : tant que les providers concrets respectent
ces signatures, basculer de Gemini à Anthropic à Groq se fait via une
variable d'environnement, sans toucher au code applicatif.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol


@dataclass
class CompletionResult:
    """Résultat d'un appel ``complete()`` ou ``chat()``."""

    text: str
    model: str
    provider: str
    # Optionnel : nombre de tokens prompt + completion (None si le
    # provider ne le retourne pas). Sert à la facturation et au log.
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    # Métadonnées opaques (raw response du provider, debug only).
    raw: dict = field(default_factory=dict)


@dataclass
class EmbeddingResult:
    """Résultat d'un appel ``embed()``."""

    values: List[float]
    dimension: int
    model: str
    provider: str


@dataclass
class Message:
    """Message d'un échange chat (multi-tour)."""

    role: str  # 'user' | 'assistant' | 'system'
    content: str


class AIProviderError(Exception):
    """Erreur générique remontée par un provider (HTTP, parsing…)."""


class AIProviderUnavailable(AIProviderError):
    """Le provider n'est pas configuré (clé manquante, etc.).

    Levée pour distinguer le « pas de clé » d'une vraie erreur réseau,
    pour que le factory puisse basculer sur un fallback proprement.
    """


class AIProvider(Protocol):
    """Contrat des providers concrets.

    Les implémentations doivent être stateless / thread-safe et lever
    ``AIProviderUnavailable`` si la clé d'API n'est pas configurée
    (plutôt que de planter au premier appel).
    """

    name: str
    default_completion_model: str
    default_embedding_model: str

    async def complete(
        self,
        *,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> CompletionResult: ...

    async def chat(
        self,
        *,
        messages: List[Message],
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> CompletionResult: ...

    async def embed(
        self,
        *,
        text: str,
        model: Optional[str] = None,
    ) -> EmbeddingResult: ...
