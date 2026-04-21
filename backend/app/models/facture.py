"""Facture client (client invoice) — linked to QuickBooks Online once issued."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class FactureStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class Facture(Base, TimestampUpdateMixin):
    __tablename__ = "factures"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )

    subtotal: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    tps: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    tvq: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    total: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    balance: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FactureStatus.DRAFT.value, index=True
    )
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # QuickBooks Online linkage
    qbo_invoice_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    qbo_doc_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    qbo_sync_token: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Automatic reminders (cron). last_reminder_at is null until a
    # first reminder fires; reminder_count lets us escalate the tone
    # at each step (polite / firm / final).
    last_reminder_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_count: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
