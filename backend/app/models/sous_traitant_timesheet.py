"""Feuille de temps sous-traitant.

Suivi des heures effectuées par un sous-traitant sur un projet : on
saisit le sous-traitant, le projet, la date, le nombre de gars sur place
et le nombre d'heures TOTAL (tous les gars cumulés) pour la journée. Sert
de base au récap d'heures dans l'admin « gestion de temps » des punchs.
"""

from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class SousTraitantTimesheet(Base, TimestampUpdateMixin):
    __tablename__ = "sous_traitant_timesheets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    sous_traitant_id: Mapped[int] = mapped_column(
        ForeignKey("sous_traitants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Nombre de gars du sous-traitant présents sur le chantier ce jour-là.
    worker_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    # Heures TOTALES cumulées de tous les gars sur place (pas par gars).
    total_hours: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False)

    notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
