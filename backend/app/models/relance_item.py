"""Relance planifiée POUR UN lead précis (instance éditable).

À l'entrée en cadence, les étapes de la séquence globale (CadenceStep)
sont COPIÉES en `RelanceItem` pour le lead, avec une date planifiée. Le
staff peut ensuite modifier/échelonner/sauter chacune indépendamment sur
la fiche prospect, sans toucher la séquence globale.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class RelanceItem(Base, TimestampUpdateMixin):
    __tablename__ = "relance_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    contact_request_id: Mapped[int] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False, default="call"
    )  # call | email | sms
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    email_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("email_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # pending | sent | done | skipped | cancelled
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
