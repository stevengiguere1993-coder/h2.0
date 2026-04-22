"""AuditLog — journal d'activité « qui a fait quoi et quand ».

Ajouté au passage sur des actions sensibles (suppression, envoi de
courriel, signature, paiement). Consultable par les rôles admin+ pour
tracer qui a modifié un devis, qui a envoyé une facture, etc.

On garde le modèle volontairement souple : `entity_type` et
`entity_id` pointent sur n'importe quelle table, `details` est un
petit JSON libre pour les champs modifiés.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Which user performed the action. Nullable so system-generated
    # entries (cron, webhooks) can still be logged.
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True, index=True
    )

    # e.g. "soumission.created", "facture.sent", "client.deleted",
    # "punch.approved", "login.failure"
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    entity_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    entity_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )

    # Small JSON blob for "what changed" — we don't force a structure
    # because the caller might store before/after values, a price diff,
    # or just a free-form note.
    details_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
