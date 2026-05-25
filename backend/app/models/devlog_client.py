"""Client du pôle Développement logiciel.

Pôle distinct de la construction : ses propres clients (entreprises
pour qui on développe des plateformes / logiciels). Un lead « gagné »
du pipeline du closer est converti en DevlogClient.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class DevlogClient(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_clients"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Nom du contact principal.
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Entreprise du client (la boîte pour qui on développe).
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True, index=True
    )
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # "active" | "archived"
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Fiche unifiee prospect/client (mai 2026) — lien vers le DevlogLead
    # d'origine quand le client provient d'une conversion de prospect, et
    # horodatage de la conversion. Sert a afficher le badge "Prospect
    # depuis... Converti le..." sur la fiche client et a fusionner
    # l'historique (notes, soumissions, etc.) cote endpoint full-history.
    # NULLABLE : un client cree directement (sans prospect) reste valide.
    converted_from_lead_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    converted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<DevlogClient(id={self.id}, name='{self.name}')>"
