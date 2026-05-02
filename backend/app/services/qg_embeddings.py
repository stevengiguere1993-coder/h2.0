"""Indexation et recherche sémantique pour le volet Entreprises.

Approche minimaliste : vecteurs stockés en JSON, similarité cosine
calculée en Python. Suffisant pour ~10 000 documents par utilisateur.

Usage typique ::

    # Indexer / re-indexer une tâche
    await index_entity(
        db,
        entreprise_id=tache.entreprise_id,
        source_type="tache",
        source_id=tache.id,
        content=f"{tache.title}\\n{tache.description or ''}",
    )

    # Rechercher
    hits = await search_similar(
        db,
        entreprise_id=ent.id,
        query="démarcher fournisseurs avant le 30 mars",
        limit=5,
    )
    for h in hits:
        print(h.source_type, h.source_id, h.similarity, h.content[:80])
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.ai import AIProviderUnavailable, embed
from app.models.qg_embedding import Embedding


log = logging.getLogger(__name__)


@dataclass
class SearchHit:
    source_type: str
    source_id: int
    content: str
    similarity: float


async def index_entity(
    db: AsyncSession,
    *,
    entreprise_id: int,
    source_type: str,
    source_id: int,
    content: str,
) -> Optional[Embedding]:
    """Indexe ou met à jour le vecteur d'une entité. Idempotent.

    Si l'IA n'est pas configurée (AIProviderUnavailable), retourne
    None silencieusement — on n'arrête pas l'application juste parce
    que l'indexation a raté.
    """
    text = (content or "").strip()
    if not text:
        return None

    try:
        res = await embed(text)
    except AIProviderUnavailable:
        log.info(
            "Embed skipped (no AI provider) for %s#%d",
            source_type,
            source_id,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Embed failed for %s#%d: %s",
            source_type,
            source_id,
            exc,
        )
        return None

    existing = (
        await db.execute(
            select(Embedding).where(
                Embedding.source_type == source_type,
                Embedding.source_id == source_id,
            )
        )
    ).scalar_one_or_none()

    payload = {
        "entreprise_id": entreprise_id,
        "content": text[:10_000],  # garde-fou
        "vector_json": json.dumps(res.values),
        "dimension": res.dimension,
        "model": res.model,
        "provider": res.provider,
        "indexed_at": datetime.now(timezone.utc),
    }

    if existing is None:
        e = Embedding(
            source_type=source_type, source_id=source_id, **payload,
        )
        db.add(e)
        await db.flush()
        await db.refresh(e)
        return e

    for k, v in payload.items():
        setattr(existing, k, v)
    await db.flush()
    return existing


async def delete_index(
    db: AsyncSession,
    *,
    source_type: str,
    source_id: int,
) -> bool:
    e = (
        await db.execute(
            select(Embedding).where(
                Embedding.source_type == source_type,
                Embedding.source_id == source_id,
            )
        )
    ).scalar_one_or_none()
    if e is None:
        return False
    await db.delete(e)
    await db.flush()
    return True


def _cosine(a: List[float], b: List[float]) -> float:
    """Similarité cosine entre deux vecteurs de même dimension.
    Retourne -1.0 si une norme est nulle (sécurité)."""
    if len(a) != len(b):
        return -1.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return -1.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


async def search_similar(
    db: AsyncSession,
    *,
    entreprise_id: Optional[int],
    query: str,
    limit: int = 10,
    source_types: Optional[List[str]] = None,
) -> List[SearchHit]:
    """Recherche sémantique : embed la query puis classe les vecteurs
    indexés par similarité cosine décroissante.

    - ``entreprise_id`` : restreint à une entreprise. None = global.
    - ``source_types`` : restreint à un sous-ensemble de types
      ('tache' uniquement, par ex.). None = tous.

    Retourne les ``limit`` meilleurs hits, score >= -1.0 (rare).
    Liste vide si aucun vecteur indexé ou IA indisponible.
    """
    text = (query or "").strip()
    if not text:
        return []
    try:
        q = await embed(text)
    except AIProviderUnavailable:
        return []
    except Exception as exc:  # noqa: BLE001
        log.warning("Search embed failed: %s", exc)
        return []

    stmt = select(Embedding)
    if entreprise_id is not None:
        stmt = stmt.where(Embedding.entreprise_id == entreprise_id)
    if source_types:
        stmt = stmt.where(Embedding.source_type.in_(source_types))
    rows = (await db.execute(stmt)).scalars().all()

    scored: List[SearchHit] = []
    for r in rows:
        try:
            vec = json.loads(r.vector_json)
        except Exception:
            continue
        sim = _cosine(q.values, vec)
        scored.append(
            SearchHit(
                source_type=r.source_type,
                source_id=r.source_id,
                content=r.content,
                similarity=sim,
            )
        )

    scored.sort(key=lambda h: h.similarity, reverse=True)
    return scored[:limit]
