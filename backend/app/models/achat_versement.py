"""Versement (paiement partiel) d'un Achat fournisseur.

Une facture fournisseur peut être payée en PLUSIEURS versements (ex.
2 virements Interac de 4 000 $). Chaque versement est poussé vers
QuickBooks comme une BillPayment distincte (montant + date + compte
réels), ce qui permet d'apparier chaque ligne du flux bancaire à SON
paiement — impossible quand l'achat est poussé en une seule dépense
du montant total (QB n'apparie pas 2 lignes bancaires à 1 dépense).
"""

from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AchatVersement(Base, TimestampMixin):
    __tablename__ = "achat_versements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    achat_id: Mapped[int] = mapped_column(
        ForeignKey("achats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # Date réelle du paiement (celle du relevé bancaire).
    paid_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Mode réel : cheque_horizon / cc_* (jamais bill_to_pay).
    payment_method: Mapped[str] = mapped_column(
        String(32), nullable=False, default="cheque_horizon"
    )
    # Id de la BillPayment QB correspondante (idempotence du push).
    qbo_bill_payment_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
