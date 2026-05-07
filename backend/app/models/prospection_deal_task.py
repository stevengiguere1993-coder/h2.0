"""Tâches attachées à un deal (Pipeline Prospection).

Chaque deal porte une liste de tâches que les prospecteurs cochent
au fil de l'avancement. Les tâches sont groupées par statut dans la
carte du deal — vocabulaire **partagé** avec les tâches d'entreprise
pour que la même UI fonctionne sur les deux volets :

  À venir       → todo
  À faire       → a_faire
  En traitement → in_progress
  Terminé       → done

Les tâches portent leur propre priorité (urgent, eleve, moyenne,
faible) — distincte de la priorité du deal lui-même. `position`
gère l'ordre d'affichage dans son groupe de statut, modifiable par
drag & drop côté frontend.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


TASK_STATUSES = ("todo", "a_faire", "in_progress", "done")
TASK_PRIORITIES = ("urgent", "eleve", "moyenne", "faible")


class ProspectionDealTask(Base):
    __tablename__ = "prospection_deal_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deal_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_deals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        # Démarre dans « À faire » par défaut — plus utile qu'« À venir ».
        default="a_faire",
        server_default="a_faire",
        index=True,
    )
    priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="moyenne",
        server_default="moyenne",
    )
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Champs « riches » alignés sur EntrepriseTache pour que la fiche
    # détaillée des tâches soit identique entre Pipeline et Entreprise.
    departement: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    recurrence: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    impact: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    effort: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Ordre dans le groupe de statut. Drag & drop met à jour ce
    # champ ; on alloue un grand pas (1000) pour pouvoir insérer
    # entre deux items sans renuméroter à chaque fois.
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
