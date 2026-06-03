"""Valeurs par defaut globales des soumissions devis_dev (pole Dev logiciel).

Phase 6 (juin 2026) - Phil veut regler, SANS toucher au code, les valeurs
par defaut appliquees a CHAQUE nouvelle soumission devis_dev : taux horaires,
commission closer, marges, et un template optionnel de modules/fonctionnalites
de base. Avant cette phase, ces defauts etaient codes en dur (75/80/10/50/50)
cote frontend et en fallback dans ``app.services.devlog_devis_calc``.

Pattern aligne sur ``ProspectionAnalysisDefault`` (table de defauts editable
depuis l'UI), mais ici on prefere une table SINGLETON (id=1) car les cinq
parametres forment un bloc coherent et on y ajoute un template JSON.

Table SINGLETON (id=1) :
    - ``taux_dev_horaire``       (Float, ex. 75)
    - ``taux_manager_horaire``   (Float, ex. 80)
    - ``commission_closer_pct``  (Float, ex. 10)  - pourcentage humain
    - ``marge_initiale_pct``     (Float, ex. 50)  - pourcentage humain
    - ``marge_recurrente_pct``   (Float, ex. 50)  - pourcentage humain
    - ``base_modules_json``      (JSONB)          - template optionnel :
          liste de modules, chacun ``{"name": str,
          "features": [{"description": str, "heures": float}, ...]}``.
          Peut etre vide / null (ne pas en mettre).

Seedee au boot avec les valeurs historiques (75/80/10/50/50, template vide)
si la ligne id=1 est absente - voir ``app.db.session.init_db``.

RETROCOMPAT : les soumissions existantes ne changent jamais. Modifier un
defaut ne change QUE le pre-remplissage des FUTURES soumissions.

Accessible via les endpoints :
    GET /api/v1/devlog/soumission-defaults
    PUT /api/v1/devlog/soumission-defaults
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Identifiant fixe de la ligne singleton (une seule ligne dans la table).
DEVLOG_SOUMISSION_DEFAULTS_ID = 1

#: Valeurs historiques codees en dur avant la Phase 6. Servent de seed et de
#: fallback ultime si la table est absente / vide (retrocompat stricte).
DEVLOG_SOUMISSION_DEFAULT_VALUES = {
    "taux_dev_horaire": 75.0,
    "taux_manager_horaire": 80.0,
    "commission_closer_pct": 10.0,
    "marge_initiale_pct": 50.0,
    "marge_recurrente_pct": 50.0,
}


class DevlogSoumissionDefaults(Base):
    """Ligne unique (id=1) des valeurs par defaut des soumissions devis_dev."""

    __tablename__ = "devlog_soumission_defaults"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # --- Parametres numeriques (pourcentages stockes en valeurs humaines,
    #     50 = 50 %). Tous nullable : un None retombe sur le fallback historique.
    taux_dev_horaire: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    taux_manager_horaire: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    commission_closer_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    marge_initiale_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    marge_recurrente_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    # --- Template optionnel de modules/fonctionnalites de base.
    #     Liste JSON : [{"name": str, "features": [{"description", "heures"}]}].
    #     None / [] = aucun template (ne pas en mettre).
    base_modules_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

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
        return f"<DevlogSoumissionDefaults(id={self.id})>"
