"""BonItem — line item attached to a BonTravail (work order)."""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class BonItem(Base, TimestampUpdateMixin):
    __tablename__ = "bon_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bon_id: Mapped[int] = mapped_column(
        ForeignKey("bons_travail.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    # ── Refacturation (bon interne) ──────────────────────────────────────
    # "heure" (main-d'œuvre, quantity = nb d'heures) ou "materiel".
    item_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="materiel"
    )
    # Heures : taux coûtant (ex. 35 $) + taux facturé (ex. 55 $). Matériel :
    # cost_rate = coût d'achat. `marge_pct` s'ajoute par-dessus le facturé.
    cost_rate: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    bill_rate: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    marge_pct: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    # Coût total de la ligne (pour le profit — Construction seulement).
    cost_total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # Qui a fait les heures : un de nos employés OU un sous-traitant.
    employe_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sous_traitant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sous_traitants.id", ondelete="SET NULL"), nullable=True, index=True
    )
