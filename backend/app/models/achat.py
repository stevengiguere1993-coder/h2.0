"""Achat — la VRAIE transaction qui charge la comptabilité.

Représente un achat effectivement passé chez un fournisseur :
marchandise reçue, facture du fournisseur en main, prêt à être
poussé vers QuickBooks comme un Bill (sur compte) ou un Purchase
(payé immédiatement).

Peut être lié à un PurchaseOrder (workflow normal : tu crées un
PO, tu l'envoies à un employé, l'employé revient avec sa facture
fournisseur, tu crées un Achat lié au PO) ou être autonome (achat
on-the-fly, urgence, sans planification préalable).

NB : avant la refonte de Avril 2026, ce modèle représentait à la
fois les POs et les Achats. La distinction est maintenant faite
proprement entre PurchaseOrder (autorisation interne) et Achat
(transaction réelle, comptable).
"""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class AchatStatus(str, Enum):
    RECEIVED = "received"    # Marchandise reçue + facture en main, prêt à pousser QB
    PAID = "paid"            # Réconcilié dans QB (facture fournisseur payée)
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
    # `reference` n'est plus séquentiel — utilisé pour stocker un
    # libellé interne court (ex. « A-42 ») ou laissé vide. La vraie
    # identification se fait par `supplier_invoice_number` + PO source.
    reference: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )

    # PO source (optionnel) — quand l'achat est issu d'un bon de
    # commande préalable. Null pour les achats on-the-fly.
    purchase_order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Montant RÉEL de la transaction (le PO source avait amount_max).
    amount: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # Numéro de facture du fournisseur (ex. « INV-2026-12345 » sur la
    # facture papier de Rona). C'est ce qu'on met comme DocNumber sur
    # le Bill QB pour que le comptable puisse rapprocher.
    supplier_invoice_number: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    # Date de la facture fournisseur (= TxnDate du Bill QB).
    invoice_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )

    payment_method: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AchatStatus.RECEIVED.value,
        index=True,
    )
    received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    receipt_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    receipt_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    receipt_image_content_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Liaison QuickBooks Online — Bill ou Purchase selon le mode de
    # paiement (voir services/achat_qbo.py).
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
        return self.receipt_image_content_type is not None
