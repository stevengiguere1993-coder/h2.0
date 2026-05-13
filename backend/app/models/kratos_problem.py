"""Kratos — problèmes détectés et solutions proposées par l'IA.

Chaque entreprise a son flux de `KratosProblem` : Claude analyse
périodiquement (ou à la demande) ses tâches, activités, projets et
visions, puis sort 3-5 problèmes avec une suggestion d'action
exécutable (créer une tâche, planifier une revue, etc.).

Statuts :
  - open : le problème est encore actif
  - dismissed : l'utilisateur l'a rejeté
  - applied : la solution suggérée a été appliquée (objet créé)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KratosProblemStatus(str, Enum):
    OPEN = "open"
    DISMISSED = "dismissed"
    APPLIED = "applied"


class KratosProblemSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class KratosProblem(Base):
    __tablename__ = "kratos_problems"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # entreprise_id devient OPTIONNEL : un problème peut concerner
    # une entreprise précise OU être transverse (organisation globale,
    # ressources, stratégie). Quand null = problème cross-entreprise.
    entreprise_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Texte original du problème tel que tapé/dicté par l'utilisateur.
    # Avant : auto-extrait de l'analyse Claude.
    # Maintenant : c'est l'INPUT de l'utilisateur, conservé verbatim.
    problem_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=KratosProblemSeverity.MEDIUM.value,
    )

    # Plan de solution complet (markdown lisible) — narratif pour
    # l'utilisateur. Stocké en plus des solution_steps_json pour ne
    # pas perdre les nuances/contexte.
    solution_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Étapes structurées (JSON array de { title, description?,
    # entreprise_id?, action_kind?, action_params? }) — utilisé pour
    # afficher des boutons « créer la tâche » par étape.
    solution_steps_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Action suggérée par l'IA :
    #   suggested_action_kind = "create_task" | "schedule_review" |
    #                           "send_reminder" | "manual"
    #   suggested_action_params = JSON (titre tâche, etc.)
    suggested_action_kind: Mapped[Optional[str]] = mapped_column(
        String(48), nullable=True
    )
    suggested_action_params: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    suggested_action_label: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=KratosProblemStatus.OPEN.value,
        index=True,
    )

    # Lien vers l'objet créé quand la solution est appliquée.
    applied_target_type: Mapped[Optional[str]] = mapped_column(
        String(48), nullable=True
    )
    applied_target_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
