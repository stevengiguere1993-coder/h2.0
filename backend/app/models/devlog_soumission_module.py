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
les items sont purement organisationnelles.

Phase 2 (refonte 2026-06) : le moteur ``app.services.devlog_devis_calc``
prend désormais les modules en compte. Un module regroupe deux natures
d'items : des **fonctionnalités** (``item_kind = feature``, heures de
dev) et des **tâches de chargé de projet** (``item_kind =
manager_task``, heures de « manager »). Coût d'un module = (Σ heures
features × taux_dev) + (Σ heures tâches × taux_manager).

* ``selected`` filtre le total : un module non sélectionné voit ses
  features et tâches exclues du calcul (les items SANS module restent
  toujours comptés — rétrocompat).
* ``free_when_module_id`` porte la gratuité conditionnelle « module →
  module » : si le module déclencheur est sélectionné, ce module
  devient gratuit (0 côté client, heures visibles côté interne).

RÉTROCOMPAT : une soumission sans aucun module et sans aucun item
``manager_task`` se calcule EXACTEMENT comme avant (tous les items
comptés, coût manager = ``heures_manager`` scalaire × taux_manager).
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
    # Gratuité conditionnelle « module → module » (refonte 2026-06,
    # Phase 2). Si ``free_when_module_id`` pointe vers un autre module
    # de la même soumission ET que ce module déclencheur est
    # sélectionné, alors CE module devient gratuit : ses fonctionnalités
    # et tâches comptent 0 dans le total CLIENT (le travail/heures
    # restent visibles côté interne). NULL = pas de gratuité
    # conditionnelle (cas par défaut, rétrocompatible). ON DELETE SET
    # NULL : si le module déclencheur est supprimé, la règle disparaît
    # sans casser ce module. Colonne ajoutée via ``additive_columns``
    # dans ``db/session`` (la FK n'est pas matérialisée par l'ALTER —
    # même précédent que ``module_id`` sur les items).
    free_when_module_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_soumission_modules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<DevlogSoumissionModule(id={self.id}, "
            f"soumission_id={self.soumission_id}, name='{self.name}')>"
        )
