"""Ligne (item) d'une facture du pôle Développement logiciel.

Mirror du DevlogSoumissionItem, mais rattaché à une facture. Permet
d'importer des heures, soumissions, ou items personnalisés sur une
facture.
"""

from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class DevlogInvoiceItem(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    quantity: Mapped[float] = mapped_column(
        Float, nullable=False, default=1, server_default="1"
    )
    unit_price: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    total: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    # Source (heures / soumission / manuel) pour traçabilité d'import.
    source_kind: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<DevlogInvoiceItem(id={self.id}, invoice_id={self.invoice_id}, total={self.total})>"
