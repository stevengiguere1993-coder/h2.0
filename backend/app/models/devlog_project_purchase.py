"""DevlogProjectPurchase — achat (depense) rattachee a un DevlogProject.

CRUD minimaliste pour suivre les achats engages dans le cadre d'un
projet : licences SaaS, materiel, frais de sous-traitance hors equipe,
etc. Pas branche QBO pour l'instant — vue interne de tracking, le
mapping comptable se fera dans une etape ulterieure.

Pour le recu, on inline le blob (BYTEA) comme pour les photos. Champs
``receipt_blob`` + ``receipt_content_type`` + ``receipt_filename`` ;
``receipt_blob`` deferred pour ne pas le charger en list.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class DevlogProjectPurchase(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_project_purchases"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    # Montant en cents (Decimal evite, comme dans les autres tables
    # financieres devlog).
    amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    supplier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    purchased_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Recu (facture fournisseur) : blob optionnel.
    receipt_blob: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    receipt_filename: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    receipt_content_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<DevlogProjectPurchase(id={self.id}, "
            f"project_id={self.project_id}, amount_cents={self.amount_cents})>"
        )
