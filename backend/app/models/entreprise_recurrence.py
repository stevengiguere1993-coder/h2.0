"""Templates de tâches récurrentes pour le volet Gestion d'entreprises.

Permet de définir une tâche-modèle (ex. « Faire la TPS/TVQ trimestrielle »)
qui est matérialisée automatiquement dans `entreprise_taches` chaque mois
/ trimestre / année par un cron.

Format de fréquence : interval simple (`every_n_days`, `every_n_weeks`,
`every_n_months`) — suffisant pour 99% des cas comptables/admin.
Pas besoin de cron syntax pour ce volet.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class FrequenceUnit(str, Enum):
    JOUR = "jour"        # tous les N jours
    SEMAINE = "semaine"  # toutes les N semaines
    MOIS = "mois"        # tous les N mois
    ANNEE = "annee"      # tous les N ans


class TacheTemplate(Base, TimestampUpdateMixin):
    """Modèle de tâche récurrente sur une entreprise.

    Le cron `materialize_recurring_tasks` lit cette table chaque jour ;
    si `next_due` ≤ aujourd'hui, il crée une instance dans
    `entreprise_taches` (avec un lien vers ce template via tags), puis
    avance `next_due` selon la fréquence.
    """

    __tablename__ = "entreprise_tache_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    departement: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    # ICE par défaut hérité par chaque instance créée.
    impact: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    effort: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Fréquence : every_n unités. Ex. (3, "mois") = tous les 3 mois.
    every_n: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    unit: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=FrequenceUnit.MOIS.value,
        server_default=FrequenceUnit.MOIS.value,
    )

    # Combien de jours avant `next_due` on matérialise (ex. 7 = créer
    # la tâche 7 jours en avance pour que l'assignee la voie).
    lead_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7, server_default="7"
    )

    next_due: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )

    # Désactivable sans suppression.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Stats (mis à jour par le cron).
    last_materialized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    nb_materialized: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
