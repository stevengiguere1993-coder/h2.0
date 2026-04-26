"""Supplier / subcontractor."""

from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class Fournisseur(Base, TimestampUpdateMixin):
    __tablename__ = "fournisseurs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # e.g. plumbing, lumber, tiles
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    # Compte de dépense QuickBooks utilisé par défaut quand on pousse
    # un Achat de ce fournisseur. Doit être le NOM exact d'un compte
    # du Plan comptable QB (ex. « Matériaux et fournitures »,
    # « Sous-traitance »). Si vide, on retombe sur le default_expense
    # _account global de QboAccountMap.
    qbo_expense_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
