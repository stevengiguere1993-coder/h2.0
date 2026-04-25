"""Achat / bon de commande (purchase order)."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, LargeBinary, Numeric, String, Text
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class AchatStatus(str, Enum):
    DRAFT = "draft"          # Planifié, pas encore envoyé
    ORDERED = "ordered"      # PO envoyé à un employé qui doit aller chercher
    RECEIVED = "received"    # Marchandise + facture en main
    CANCELLED = "cancelled"


class PaymentMethod(str, Enum):
    """Mode de paiement de l'achat → détermine le routage QB.

    Comptes Horizon réels (mappés dans /app/parametres → Comptes QB) :

    - bill_to_pay        Sur compte fournisseur, facture à payer plus
                         tard (net-30) → Bill QB (A/P).
    - cheque_horizon     Compte chèque Horizon (paiement immédiat) →
                         Purchase QB.
    - cc_steven          CC Horizon Steven Giguère → Purchase QB.
    - cc_michael         CC Horizon Michael Villiard → Purchase QB.
    - cc_olivier         CC Horizon Olivier Therrien → Purchase QB.
    - cc_christian       CC Horizon Christian Villiard → Purchase QB.
    """

    BILL_TO_PAY = "bill_to_pay"
    CHEQUE_HORIZON = "cheque_horizon"
    CC_STEVEN = "cc_steven"
    CC_MICHAEL = "cc_michael"
    CC_OLIVIER = "cc_olivier"
    CC_CHRISTIAN = "cc_christian"


class Achat(Base, TimestampUpdateMixin):
    __tablename__ = "achats"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    fournisseur_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("fournisseurs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)

    # Employé qui va chercher la marchandise (foreman habituellement).
    # Reçoit le PO par courriel lors de l'envoi.
    assigned_employe_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Mode de paiement — détermine le routage QB.
    payment_method: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AchatStatus.DRAFT.value, index=True
    )
    ordered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    receipt_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Scanned / uploaded receipt image stored in-DB. Blobs stay small
    # (receipts typically < 2 MB) so this is fine for our volume; if
    # we ever outgrow it we can swap in a cloud object store.
    receipt_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    receipt_image_content_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Liaison QuickBooks Online — l'achat est poussé comme un Bill
    # (facture fournisseur) qui charge le coût matériel sur le projet.
    # Le numéro PO interne reste dans Memo / PrivateNote du Bill.
    qbo_bill_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    qbo_doc_number: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    qbo_sync_token: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    @property
    def has_receipt_image(self) -> bool:
        # Cheap check: the blob itself is deferred from list queries;
        # content_type is set iff an image is attached.
        return self.receipt_image_content_type is not None
