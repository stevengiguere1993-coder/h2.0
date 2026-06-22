"""Projet de développement — pôle Développement logiciel.

Une fois un client gagné (et souvent une soumission acceptée), le
travail de développement est suivi comme un projet : statut,
échéancier, description.
"""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    event,
)
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

    # --- Budget & heures importés de la soumission acceptée -----------
    # Snapshot posé à l'auto-import (refonte projet 2026-06). ``budget_cents``
    # = total de l'investissement initial (prix client one-shot), somme des
    # budgets de phase. Les heures prévues servent au suivi prévu vs réel.
    # ``taux_horaire_defaut`` = taux dev de la soumission, repère pour
    # valoriser les heures réelles (remplace le 75 $/h codé en dur).
    budget_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    heures_dev_prevues: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    heures_manager_prevues: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    taux_horaire_defaut: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Horodatage du démarrage effectif. Posé automatiquement par le
    # service ``devlog_project_provision.start_project_from_contract``
    # quand le contrat est signé ET le dépôt encaissé. NULL tant que
    # le projet n'est pas démarré.
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Horodatage du passage en status='livre'. Posé automatiquement par
    # l'event listener ci-dessous quand le status passe de tout autre
    # valeur à 'livre'. Sert au cron ``devlog_nps_dispatch`` qui envoie
    # un mini-formulaire NPS 7 jours après la livraison. NULL tant que
    # le projet n'a jamais été marqué livré.
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<DevlogProject(id={self.id}, name='{self.name}', status='{self.status}')>"


# Event listener : pose ``delivered_at`` automatiquement quand le status
# passe à 'livre'. Évite de toucher aux endpoints / services qui muent le
# status (PATCH /devlog/projects/{id}, kanban drag, automations).
# Idempotent : si delivered_at est déjà posé, on ne l'écrase pas.
@event.listens_for(DevlogProject.status, "set", propagate=True)
def _devlog_project_status_set(target, value, oldvalue, initiator):
    try:
        if value == "livre" and oldvalue != "livre":
            if getattr(target, "delivered_at", None) is None:
                target.delivered_at = datetime.now(timezone.utc)
    except Exception:  # pragma: no cover - never break the write path
        pass
