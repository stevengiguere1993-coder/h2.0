"""Facture MENSUELLE ouverte par client QuickBooks (2026-07-27).

Une ligne = LA facture du mois d'un client dans une compagnie QBO
(realm) : les clics de facturation (relocation, frais de gestion,
refacturation feuille de temps) s'y greffent en lignes au lieu de créer
une facture par clic. Voir services/qbo_monthly_invoice.py.
Nouvelle table → ensure_qbo_connections_table.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QboMonthlyInvoice(Base):
    __tablename__ = "qbo_monthly_invoices"
    __table_args__ = (
        UniqueConstraint(
            "realm_id", "qbo_customer_id", "mois",
            name="uq_qbo_monthly_invoice",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: Compagnie QuickBooks (realm) — la vraie clé : chez Phil les scopes
    #: entreprise/immobilier pointent la même compagnie.
    realm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Scope résolu au moment du premier clic (informatif).
    scope: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    qbo_customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 1er du mois calendaire de la facture.
    mois: Mapped[date] = mapped_column(Date, nullable=False)
    qbo_invoice_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    qbo_doc_number: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
