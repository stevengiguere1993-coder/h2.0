"""Module d'une soumission « devis_dev » (pôle Développement logiciel).

Refonte 2026-06 — niveau MODULE introduit dans la section
« investissement initial » d'une soumission devis_dev. Un module
regroupe des fonctionnalités (``DevlogSoumissionItem`` de type
``feature``). Le prix d'un module est, par définition, la somme des
``total`` de ses items.

Portée volontairement limitée à l'**investissement initial** : les
sections de frais mensuels récurrents ne sont pas concernées par les
modules. Un module est rattaché (optionnellement) à la section
initiale via ``section_id`` (NULL si la section est supprimée — d'où
le ``ON DELETE SET NULL``).

Phase 1 (socle de données) : la table et la colonne ``module_id`` sur
les items sont purement organisationnelles. Le calcul des totaux de la
soumission (``app.services.devlog_devis_calc``) n'est PAS modifié : le
regroupement par module est une couche d'affichage, la sommation des
items reste identique. Les soumissions existantes (sans aucun module)
restent valides et se calculent exactement comme avant.

``selected`` (default True) anticipe les phases suivantes (sélection
cochée/décochée par le client + gratuité conditionnelle) mais n'a
aucun effet sur le calcul en Phase 1.
"""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class DevlogSoumissionModule(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_soumission_modules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    soumission_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_soumissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Section de regroupement parente (typiquement « investissement
    # initial »). Nullable : si la section est supprimée, le module
    # survit avec section_id = NULL (ON DELETE SET NULL).
    section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_soumission_sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # État de sélection — servira aux phases suivantes (sélection client
    # + gratuité conditionnelle). Sans effet sur le calcul en Phase 1.
    selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return (
            f"<DevlogSoumissionModule(id={self.id}, "
            f"soumission_id={self.soumission_id}, name='{self.name}')>"
        )
