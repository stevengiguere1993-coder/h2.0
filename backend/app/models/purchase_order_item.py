"""PurchaseOrderItem — articles d'un bon de commande.

Liste « épicerie » que l'employé apporte chez le fournisseur. Pas de
taxes (un PO est interne, pas une facture). La somme des lignes
alimente le `amount_max` du PO.
"""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class PurchaseOrderItem(Base, TimestampUpdateMixin):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Ordre d'affichage (0-based)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # ex. "boîte", "pi", "h"
    quantity: Mapped[float] = mapped_column(
        Numeric(12, 3), nullable=False, default=1, server_default="1"
    )
    unit_price: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default="0"
    )
    total: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default="0"
    )
