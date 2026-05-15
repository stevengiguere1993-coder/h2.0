"""Soumission (devis) du pôle Développement logiciel.

Un devis envoyé à un lead ou à un client. Le pipeline du closer a une
étape « soumission » : c'est ici qu'on suit le devis correspondant.
"""

from typing import Optional

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin

#: Statuts d'une soumission — alignés sur le pôle Construction
#: (5 colonnes du kanban : brouillon → envoyée → acceptée / refusée / expirée).
SOUMISSION_STATUSES = (
    "brouillon",
    "envoyee",
    "acceptee",
    "refusee",
    "expiree",
)


class DevlogSoumission(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_soumissions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # Une soumission cible un lead (prospect) et/ou un client.
    lead_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="brouillon",
        server_default="brouillon", index=True,
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<DevlogSoumission(id={self.id}, title='{self.title}', status='{self.status}')>"
