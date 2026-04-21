"""Payment — a single partial or full payment recorded against a Facture.

A facture can receive many payments over time. The facture is considered
fully paid when sum(payments.amount) >= facture.total.
"""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentMethod(str, Enum):
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    CHECK = "check"
    BANK_TRANSFER = "bank_transfer"
    OTHER = "other"


class Payment(Base):
    __tablename__ = "facture_payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    facture_id: Mapped[int] = mapped_column(
        ForeignKey("factures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PaymentMethod.OTHER.value
    )
    paid_at: Mapped[date] = mapped_column(Date, nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # QuickBooks linkage for optional sync
    qbo_payment_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
