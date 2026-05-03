"""Modèles du volet Investisseur.

Suit les investissements personnels d'un User (avec volet « investisseur »)
dans des immeubles du portefeuille. Calcule TVPI, DPI, cash-on-cash via
Distribution + valorisation courante de la part.

Conventions :
- Préfixe `inv_` côté SQL.
- Un User est l'investisseur (pas de modèle Investisseur séparé — on
  réutilise User avec volets contenant "investisseur").
- Un Investissement = participation à un Immeuble à un % défini.
- Distribution = versement reçu (loyer net distribué, appréciation
  réalisée à la sortie, refinancement, etc.).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class InvestissementStatus(str, Enum):
    ACTIF = "actif"
    SORTIE = "sortie"          # investisseur sorti (vente parts)
    EN_ATTENTE = "en_attente"  # closing pas finalisé


class DistributionType(str, Enum):
    LOYER = "loyer"               # cash flow opérationnel
    APPRECIATION = "appreciation" # gain capital réalisé
    REFINANCEMENT = "refinancement"
    SORTIE = "sortie"             # vente / rachat parts
    AUTRE = "autre"


class Investissement(Base, TimestampUpdateMixin):
    """Participation d'un User dans un immeuble."""

    __tablename__ = "inv_investissements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Montant investi (en CAD) et % de parts détenu
    montant_investi: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False
    )
    parts_pct: Mapped[float] = mapped_column(
        Numeric(6, 3), nullable=False, default=0,
        server_default="0",
    )  # ex. 12.500 = 12.5%

    date_investissement: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=InvestissementStatus.ACTIF.value,
        server_default=InvestissementStatus.ACTIF.value,
        index=True,
    )

    # Sortie éventuelle
    date_sortie: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    montant_sortie: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_visible_to_investor: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class Distribution(Base):
    """Versement reçu par un investisseur sur un investissement.

    Permet de calculer DPI = total distributions / capital investi.
    """

    __tablename__ = "inv_distributions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    investissement_id: Mapped[int] = mapped_column(
        ForeignKey("inv_investissements.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    date_distribution: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        default=DistributionType.LOYER.value,
        server_default=DistributionType.LOYER.value,
    )
    montant: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
