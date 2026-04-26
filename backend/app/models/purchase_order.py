"""PurchaseOrder (Bon de commande) — document d'autorisation interne.

Sert à autoriser un employé à aller chercher du matériel chez un
fournisseur. Référence séquentielle PO-XXXX. Statuts:
  - draft     : en planification, pas encore envoyé
  - sent      : envoyé par courriel à l'employé assigné
  - fulfilled : un Achat a été créé à partir de ce PO (un ou plusieurs)
  - cancelled : annulé

Le PO en lui-même n'a pas d'impact comptable — il ne charge pas de
projet, ne crée pas de Bill QB. C'est l'Achat lié qui fait ça.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class PurchaseOrderStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class PurchaseOrder(Base, TimestampUpdateMixin):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    reference: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False
    )

    fournisseur_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("fournisseurs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_employe_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Montant maximum autorisé (cap budgétaire). L'Achat réel peut être
    # inférieur ou supérieur ; on stocke ici juste l'autorisation.
    amount_max: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # Mode de paiement planifié — pré-rempli sur l'Achat dérivé.
    payment_method: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PurchaseOrderStatus.DRAFT.value,
        index=True,
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
