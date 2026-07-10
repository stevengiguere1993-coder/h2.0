"""Valeurs par defaut de cout et de refacturation des bons de travail (Construction).

Phil regle depuis Parametres -> Bons de travail, SANS toucher au code, les trois
valeurs appliquees par defaut a CHAQUE nouvelle ligne d'un bon de travail interne :
  - cout horaire par defaut des « nos hommes »   (ex. 35 $/h)
  - taux de refacturation horaire par defaut      (ex. 55 $/h)
  - marge par defaut appliquee aux lignes         (ex. 10 %)

Avant, 35 etait code en dur (``cockpit.DEFAULT_HOURLY_COST``) et 55/10 venaient du
frontend (fiche bon / formulaire de creation). Desormais ces defauts vivent dans
cette ligne SINGLETON (id=1), lue par les formulaires et par le moteur de
refacturation en filet de securite.

RETROCOMPAT : les bons/lignes existants ne changent JAMAIS. Modifier un defaut ne
change QUE le pre-remplissage et le fallback des FUTURES lignes.

Table SINGLETON (id=1), creee par ``create_all`` et seedee au boot (``init_db``)
avec les valeurs historiques si absente. Endpoints :
    GET /api/v1/construction/bon-defaults
    PUT /api/v1/construction/bon-defaults
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Identifiant fixe de la ligne singleton (une seule ligne dans la table).
CONSTRUCTION_BON_DEFAULTS_ID = 1

#: Valeurs historiques codees en dur avant ce reglage. Servent de seed et de
#: fallback ultime si la table est absente / vide / un champ NULL (retrocompat).
CONSTRUCTION_BON_DEFAULT_VALUES = {
    "default_cost_rate": 35.0,
    "default_bill_rate": 55.0,
    "default_marge_pct": 10.0,
}


class ConstructionBonDefaults(Base):
    """Ligne unique (id=1) des defauts cout/refac/marge des bons de travail."""

    __tablename__ = "construction_bon_defaults"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Tous nullable : un None retombe sur le fallback historique (35/55/10).
    default_cost_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    default_bill_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    default_marge_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<ConstructionBonDefaults(id={self.id})>"
