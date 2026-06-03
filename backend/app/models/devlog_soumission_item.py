"""Ligne (item) d'une soumission du pôle Développement logiciel.

Une soumission est composée de N lignes. Deux usages coexistent :

1. **Legacy** (``is_devis_dev = False``) — lignes regroupées par
   ``DevlogSoumissionSection`` avec un markup interne. Les colonnes
   ``description``, ``unit``, ``quantity``, ``cost_per_unit``,
   ``unit_price``, ``total`` sont alors significatives. Pour ces
   soumissions ``item_kind`` reste à la valeur par défaut.

2. **Devis_dev** (``is_devis_dev = True``) — lignes typées par
   ``item_kind`` :

   * ``recurring_cost`` : un coût mensuel récurrent (label +
     ``cost_per_unit`` = coût mensuel interne).
   * ``feature``        : une fonctionnalité du livrable initial
     (label + ``heures`` = nombre d'heures dev).
   * ``manager_task``   : une tâche de chargé de projet (refonte
     2026-06). Vue interne uniquement (label + ``heures`` = heures de
     « manager »). Rattachable à un module via ``module_id`` ; son
     coût = ``heures × taux_manager_horaire`` et remplace, quand au
     moins une tâche existe, le scalaire ``heures_manager`` global de
     la soumission (cf. ``devlog_devis_calc``).
   * ``fixed_cost``     : un frais fixe one-shot (domaine, hosting
     initial, etc.) (label + ``cost_per_unit`` = coût fixe interne).

   Le service ``devlog_devis_calc`` se charge du calcul de la part
   client ; ``section_id`` n'est pas utilisé dans ce mode.
"""

from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


#: Types d'items reconnus en mode « devis_dev ». ``feature`` reste la
#: valeur par défaut (compatible avec les rows existantes qui n'ont pas
#: encore de kind explicite).
ITEM_KINDS = ("recurring_cost", "feature", "manager_task", "fixed_cost")


class DevlogSoumissionItem(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_soumission_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    soumission_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_soumissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Section parente (legacy — soumissions générées avant la refonte
    # devis_dev). Nullable et toujours NULL pour les nouvelles
    # soumissions devis_dev.
    section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_soumission_sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Module parent (refonte 2026-06). Une fonctionnalité rattachée à
    # un module appartient à ce module ; le prix du module = somme des
    # ``total`` de ses items. Nullable : un item legacy ou un item de
    # section récurrente reste valide sans module (ON DELETE SET NULL —
    # si le module est supprimé, l'item est détaché, pas effacé). La
    # colonne est ajoutée via ``additive_columns`` dans ``db/session``.
    module_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_soumission_modules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    # Unité libre : "h", "jour", "forfait", "mois", etc.
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    quantity: Mapped[float] = mapped_column(
        Float, nullable=False, default=1, server_default="1"
    )
    # Coût interne unitaire (admin only — JAMAIS exposé côté client).
    # Le prix client (unit_price) est dérivé de cost × (1 + markup/100)
    # où markup est porté par la section parente.
    cost_per_unit: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    unit_price: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    total: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Refonte « devis_dev » -----------------------------------------
    # Typage des lignes du nouveau format. Pour les rows legacy, la
    # valeur par défaut ``feature`` est inoffensive : l'endpoint de
    # listing ne discrimine que pour les soumissions ``is_devis_dev``.
    item_kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="feature",
        server_default="feature",
        index=True,
    )
    # Heures (pour les items de type ``feature`` = heures de dev et
    # ``manager_task`` = heures de chargé de projet). NULL pour les
    # autres kinds (``recurring_cost`` / ``fixed_cost``).
    heures: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 2), nullable=True
    )

    def __repr__(self) -> str:
        return f"<DevlogSoumissionItem(id={self.id}, soumission_id={self.soumission_id}, total={self.total})>"
