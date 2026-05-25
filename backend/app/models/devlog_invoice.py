"""Facture du pôle Développement logiciel.

Facturation d'un client, généralement rattachée à un projet de
développement.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin

#: Statuts d'une facture.
INVOICE_STATUSES = ("brouillon", "envoyee", "payee", "annulee")


class DevlogInvoice(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_invoices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Numéro de facture (saisi librement pour l'instant).
    number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="brouillon",
        server_default="brouillon", index=True,
    )
    issued_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Envoi PDF + consultation publique (vague 1, mai 2026) ---
    # Token opaque pour la page publique /devlog/pay-invoice/{token}.
    signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    # Horodatage d'envoi par email au client.
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Horodatage du marquage manuel « payée » (en attendant Stripe).
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Paiement en ligne via Stripe Checkout (mai 2026) ---
    # ID de la Checkout Session courante (cs_live_...). Sert au mapping
    # webhook → facture si l'event ne porte pas metadata.invoice_id.
    stripe_session_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )
    # PaymentIntent associé (pi_live_...). Conservé pour réconciliation
    # comptable / remboursements éventuels.
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    # Méthode de paiement effective : stripe | virement | cheque | manuel.
    # Renseigné automatiquement à l'encaissement Stripe, ou par l'admin
    # lors d'un mark-paid manuel (legacy = NULL).
    payment_method: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    def __repr__(self) -> str:
        return f"<DevlogInvoice(id={self.id}, number='{self.number}', status='{self.status}')>"
