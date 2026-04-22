"""Notification — in-app inbox entry for a user.

Utilisé par la cloche 🔔 du topbar admin. Les notifications sont créées
par le code applicatif (ex. `service.create_notification(db, user_id=...,
kind="soumission_signed", ...)`) et marquées lues quand l'utilisateur
les ouvre.

On garde le modèle minimal — pas de fan-out complexe, pas de push temps
réel. Le frontend poll toutes les 60s.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # e.g. "soumission_accepted", "facture_paid", "leave_requested",
    # "punch_pending", "appointment_assigned"
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Deep link to open when the user clicks the notification
    href: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Denormalized for fast unread-count queries
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
