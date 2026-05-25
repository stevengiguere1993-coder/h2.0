"""Projet de développement — pôle Développement logiciel.

Une fois un client gagné (et souvent une soumission acceptée), le
travail de développement est suivi comme un projet : statut,
échéancier, description.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin

#: Étapes de vie d'un projet de développement — alignées sur le pôle
#: Construction (5 colonnes du kanban).
PROJECT_STATUSES = (
    "planifie",
    "en_attente",
    "en_cours",
    "suspendu",
    "livre",
)


class DevlogProject(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Soumission acceptée à l'origine du projet (optionnel).
    soumission_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_soumissions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="planifie",
        server_default="planifie", index=True,
    )
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Horodatage du démarrage effectif. Posé automatiquement par le
    # service ``devlog_project_provision.start_project_from_contract``
    # quand le contrat est signé ET le dépôt encaissé. NULL tant que
    # le projet n'est pas démarré.
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<DevlogProject(id={self.id}, name='{self.name}', status='{self.status}')>"
