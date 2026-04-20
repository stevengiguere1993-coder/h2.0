"""Soumission (quote / estimate sent to a prospect or client)."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class SoumissionStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Soumission(Base, TimestampUpdateMixin):
    __tablename__ = "soumissions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    # Target — either a ContactRequest or a Client
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Amounts (in CAD)
    subtotal: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    tps: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    tvq: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    total: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SoumissionStatus.DRAFT.value, index=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # QuickBooks Online linkage (populated by sync service)
    qbo_estimate_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    qbo_doc_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    qbo_sync_token: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
