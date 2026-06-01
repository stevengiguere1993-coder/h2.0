"""Defaults globaux pour les inputs manuels d'analyse financière.

Table clé/valeur générique stockant les valeurs par défaut qu'on
applique à la création d'une nouvelle ``LeadAnalysis``. L'override
par fiche reste toujours possible : modifier un défaut ne change
QUE les valeurs pré-remplies des futurs deals, pas les analyses
existantes.

Exemples de clés (seedées au boot — voir ``app.db.session``) :
    - ``taux_interet_refi``                (Float, ex. 0.0375)
    - ``mdf_preteur_b_pct``                (Float, ex. 0.25)
    - ``taux_interet_preteur_b_projet``    (Float, ex. 0.08)

Accessible via les endpoints :
    GET   /api/v1/prospection/analysis-defaults
    PATCH /api/v1/prospection/analysis-defaults/{key}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProspectionAnalysisDefault(Base):
    """Une entrée clé/valeur dans la table des défauts d'analyse.

    Stockée en (Float|JSONB) selon le type — la plupart des défauts
    sont des floats (taux, pourcentages), mais on garde ``value_json``
    pour les cas plus complexes (listes, dicts) qu'on pourrait vouloir
    rendre configurables plus tard sans nouvelle migration.
    """

    __tablename__ = "prospection_analysis_defaults"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Clé technique unique (ex. ``"taux_interet_refi"``).
    key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    # Valeur si scalaire (la plupart des cas).
    value_float: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    # Valeur si structurée (liste, dict, etc.). Optionnel.
    value_json: Mapped[Optional[Any]] = mapped_column(
        JSONB, nullable=True
    )

    # Libellé français affiché dans l'UI du modal de modification.
    label_fr: Mapped[str] = mapped_column(String(255), nullable=False)

    # Description longue (tooltip / aide contextuelle).
    description_fr: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Bornes de validation (UI + endpoint PATCH).
    min_value: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    max_value: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    step: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.01, server_default="0.01"
    )

    # Tag pour regrouper les défauts par section UI (le bouton ⚙️ de
    # la section "Analyse financière — inputs manuels" filtre sur
    # group="refi", celui de "Composition MDF prêteur B" sur
    # group="mdf"). Optionnel — None = affiché partout.
    #
    # `group` est un mot-clé SQL réservé en Postgres, donc on force le
    # nom de colonne à `group_name` côté DB tout en gardant l'attribut
    # Python `group` (plus naturel à manipuler).
    group: Mapped[Optional[str]] = mapped_column(
        "group_name", String(32), nullable=True
    )

    # Statut "finançable par défaut" pour les items des groupes
    # ``mdf_frais`` et ``mdf_pct`` (mai 2026). True → la case
    # "Finançable" est pré-cochée à la création d'une nouvelle fiche
    # d'analyse. Nullable (les items du groupe ``inputs_manuels`` n'ont
    # pas de notion de "finançable" — colonne ignorée pour eux).
    # L'override par fiche reste prioritaire (via
    # ``LeadAnalysis.frais_demarrage_financables_json``).
    financable_par_defaut: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )

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

