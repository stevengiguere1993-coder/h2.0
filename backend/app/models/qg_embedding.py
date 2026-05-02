"""Index sémantique : un vecteur d'embedding par entité indexée.

Approche minimaliste : on stocke le vecteur en JSON dans une colonne
``Text`` (pas de dépendance pgvector). La recherche par similarité
cosine se fait côté Python dans le service. Suffisant pour ~10 000
documents — au-delà on migrera vers pgvector + index HNSW.

Une entrée = 1 vecteur pour 1 entité externe (source_type +
source_id). Idempotent via la contrainte UNIQUE.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Embedding(Base):
    __tablename__ = "qg_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id",
            name="uq_qg_embedding_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Type de l'entité indexée : 'tache' | 'summary' | 'insight' | …
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    # ID de l'entité dans sa table d'origine
    source_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )

    # Texte original embeddé (pour traçabilité + ré-indexation)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Vecteur JSON-encodé. Format : "[0.123, -0.456, ...]"
    # Dimension stockée séparément pour validation à la lecture.
    vector_json: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)

    # Provenance : modèle d'embedding utilisé (gemini text-embedding-004…)
    model: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    provider: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
