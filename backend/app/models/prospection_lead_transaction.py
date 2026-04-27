"""Transactions historiques d'un lead Prospection.

Stockage manuel des ventes connues d'une propriété (le prospecteur les
saisit à mesure qu'il les apprend). Une vraie source automatisée
nécessiterait JLR ($), pas dans le scope MVP.

Sert à voir d'un coup d'œil :
- Quand le proprio actuel a acheté
- À quel prix
- L'historique des transferts (héritage, succession, vente ICOM)
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProspectionLeadTransaction(Base):
    __tablename__ = "prospection_lead_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    lead_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    transaction_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )
    amount: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    # vente | succession | donation | autre
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="vente"
    )
    # JLR | publication officielle | informateur | inconnu
    source: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
