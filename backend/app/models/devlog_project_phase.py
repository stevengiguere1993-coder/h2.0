"""Phase d'un projet de developpement - pole Developpement logiciel.

Permet de decouper un DevlogProject en phases chronologiques
(planification, design, dev, recette, livraison...). Chaque phase
porte un statut, des dates start/end et une position pour
l'ordonnancement manuel.
"""

from datetime import date
from typing import Optional

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


PHASE_STATUSES = ("planifie", "en_cours", "termine")


class DevlogProjectPhase(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_project_phases"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="planifie",
        server_default="planifie",
        index=True,
    )

    # --- Snapshot du chiffrage (refonte projet 2026-06) ---------------
    # Une phase correspond souvent à un MODULE de la soumission acceptée :
    # on fige ici son budget (prix client) et ses heures prévues pour que
    # le projet porte l'info sans dépendre de la soumission (qui peut être
    # modifiée). NULL/0 pour une phase créée manuellement.
    source_module_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_soumission_modules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    budget_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    heures_dev_prevues: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    heures_manager_prevues: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )

    def __repr__(self) -> str:
        return (
            f"<DevlogProjectPhase(id={self.id}, "
            f"project_id={self.project_id}, name='{self.name}')>"
        )
