"""Sous-traitant du pôle Développement logiciel.

Développeurs freelance, designers, QA, etc. Distinct du modèle
SousTraitant côté Construction : on garde les pôles étanches au niveau
des données (tarifs, notes, évaluations différentes par contexte).
"""

from typing import Optional

from sqlalchemy import Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class DevlogSousTraitant(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_sous_traitants"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True, index=True
    )
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Spécialité libre : "Frontend React", "Backend Python", "UI/UX",
    # "QA", "DevOps", etc.
    specialty: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Taux horaire convenu (CAD).
    hourly_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Statut actif (False = ne plus apparaître dans les pickers).
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Évaluation libre (étoiles 1-5).
    rating: Mapped[Optional[int]] = mapped_column(nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<DevlogSousTraitant(id={self.id}, name='{self.name}')>"
