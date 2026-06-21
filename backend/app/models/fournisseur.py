"""Supplier / subcontractor."""

from typing import Optional

from sqlalchemy import Boolean, Integer, String
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
    # Fournisseur inscrit à la TPS/TVQ ? Par défaut OUI (cas normal au
    # Québec). Si NON, ses achats ne portent pas de taxe récupérable :
    # on ne divise pas leur montant par 1.14975 et on ne réclame aucun
    # CTI/RTI dessus (cf. calcul de rentabilité projet).
    tax_registered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    # Delai de paiement par defaut (net-N jours) sur les achats payes
    # par facture fournisseur (payment_method = bill_to_pay). NULL =
    # utilise 30 par defaut. Sert a calculer due_at sur chaque Achat.
    payment_terms_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    # Compte de dépense QuickBooks utilisé par défaut quand on pousse
    # un Achat de ce fournisseur. Doit être le NOM exact d'un compte
    # du Plan comptable QB (ex. « Matériaux et fournitures »,
    # « Sous-traitance »). Si vide, on retombe sur le default_expense
    # _account global de QboAccountMap.
    qbo_expense_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Adresse du fournisseur (une ligne libre). Importee depuis le
    # BillAddr du Vendor QuickBooks quand il existe deja, et renvoyee
    # sur le Vendor QB quand on en cree un nouveau.
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Id du Vendor QuickBooks correspondant. Memorise au 1er match
    # (par email/nom) pour eviter de re-resoudre a chaque push.
    qbo_vendor_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
