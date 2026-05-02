"""Abstraction de la couche IA pour h2.0.

Module providers-agnostique : on choisit le moteur via la variable
d'environnement ``AI_PROVIDER`` (gemini par défaut). Tout le reste du
code applicatif appelle uniquement ``ai.complete()`` / ``ai.embed()``
sans connaître le fournisseur.

Usage minimal ::

    from app.integrations.ai import complete, embed

    res = await complete(
        prompt="Génère un résumé en 3 puces de :\\n" + corpus,
        system="Tu es un dirigeant chevronné, va droit au but.",
    )
    print(res.text)

    vec = await embed("Texte à indexer")
    print(len(vec.values))  # 768 pour Gemini text-embedding-004

Variables d'environnement supportées
------------------------------------
- ``AI_PROVIDER``     : ``gemini`` (défaut) | ``anthropic`` | ``groq``
- ``GEMINI_API_KEY``  : clé Google AI Studio (gratuite)
- ``ANTHROPIC_API_KEY``: clé Anthropic (payante, optionnelle)
- ``GROQ_API_KEY``    : clé Groq (gratuite, fallback)
- ``AI_MODEL``        : surcharge le modèle par défaut du provider
"""

from __future__ import annotations

from app.integrations.ai._base import (
    AIProviderError,
    AIProviderUnavailable,
    CompletionResult,
    EmbeddingResult,
    Message,
)
from app.integrations.ai._factory import (
    chat,
    chat_provider,
    complete,
    current_provider,
    embed,
    embedding_provider,
    is_configured,
)


__all__ = [
    "AIProviderError",
    "AIProviderUnavailable",
    "CompletionResult",
    "EmbeddingResult",
    "Message",
    "chat",
    "chat_provider",
    "complete",
    "current_provider",
    "embed",
    "embedding_provider",
    "is_configured",
]
