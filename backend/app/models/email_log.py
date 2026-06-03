"""Journal des courriels échangés avec une entité CRM (client, locataire,
prospect…), pour afficher l'email dans l'onglet Communications au même
titre que les appels et SMS.

- `direction="outbound"` : courriel envoyé depuis Kratos (via Graph).
- `direction="inbound"` : réponse du client (relevée depuis la boîte —
  Phase B, nécessite la permission Graph Mail.Read).

Nouvelle table → créée par `create_all` (pas de migration nécessaire).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EmailLog(Base, TimestampMixin):
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    direction: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # outbound | inbound
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="sent"
    )  # sent | failed | received

    from_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    to_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True, index=True
    )
    cc: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    body_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Lien CRM (mêmes conventions que voice_calls / voice_sms).
    entity_type: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )
    entity_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )

    sent_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Pour le rapprochement des réponses (Phase B) et la déduplication.
    provider_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    thread_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )

    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
