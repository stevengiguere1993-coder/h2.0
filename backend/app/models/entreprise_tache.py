"""Tâche du volet Gestion d'entreprises.

Modèle riche : scoring ICE × urgence, récurrence simple, tags,
assignation, tracking Monday pour les imports/sync.
"""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class TacheStatus(str, Enum):
    BACKLOG = "backlog"            # legacy, plus utilisé dans l'UI
    TODO = "todo"                  # « À venir » — leftmost, à classer
    A_FAIRE = "a_faire"            # « À faire » — engagée, à exécuter
    IN_PROGRESS = "in_progress"    # « En traitement » — actif
    WAITING = "waiting"            # legacy, migré vers todo au boot
    DONE = "done"                  # « Terminé »


class EntrepriseTache(Base, TimestampUpdateMixin):
    __tablename__ = "entreprise_taches"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Catégorisation libre. Suggestion d'UI : finance / operations /
    # rh / juridique / marketing / fiscalite / autre.
    departement: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=TacheStatus.BACKLOG.value,
        server_default=TacheStatus.BACKLOG.value,
        index=True,
    )

    # ── Scoring ICE × Urgence ────────────────────────────────────────
    # Impact (1-10) — effet sur revenu / risque / conformité
    impact: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Confiance (1-10) — à quel point on est sûr du résultat
    confidence: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    # Effort (1-10) — temps estimé. Score divisé par cet effort, donc
    # plus c'est haut, plus la tâche descend dans le classement.
    effort: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Assignation ───────────────────────────────────────────────────
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # ── Calendrier ────────────────────────────────────────────────────
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Récurrence simple ─────────────────────────────────────────────
    # NULL = tâche unique. Sinon : 'daily', 'weekly', 'biweekly',
    # 'monthly', 'quarterly', 'yearly'.
    recurrence: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    # Si récurrente : ID de la « série » (le 1er parent généré). Sert
    # à grouper les occurrences pour les vues maître/enfants.
    recurrence_parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("entreprise_taches.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Tags JSON-encodés (liste de strings). Utilisé pour la recherche
    # et le filtrage. Suggestion d'UI : autocomplete sur tags existants.
    tags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Liens externes ────────────────────────────────────────────────
    # Monday : pour la synchronisation idempotente avec un tableau
    # Monday existant. Permet de re-importer sans créer de doublons.
    monday_item_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    monday_board_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    monday_group_title: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
