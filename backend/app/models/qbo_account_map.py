"""Mapping mode de paiement (Achat) → nom du compte QBO.

Permet à l'admin de configurer dans /app/parametres quel compte
QuickBooks utiliser pour chaque mode de paiement, sans redéployer.
Single-row (id=1).

Chaque champ est le `Name` exact du compte QBO tel qu'il apparaît
dans QB → Comptabilité → Plan comptable. À l'utilisation, on fait
une query QBO pour résoudre ce Name → Account Id réel.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QboAccountMap(Base):
    __tablename__ = "qbo_account_maps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # Compte d'expense par défaut (pour les achats sans projet précis,
    # « matériaux généraux / outils / fournitures de chantier »).
    default_expense_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Mode opérations (chèque / sur compte fournisseur) → Bill QB,
    # géré côté QB par le compte Comptes Fournisseurs (A/P) par
    # défaut. Pas besoin de mapper, mais on garde le champ au cas où.
    operations_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Cartes de crédit + comptant + interac → Purchase QB, charge
    # directement la dépense ET crédite le compte de paiement.
    cc_steven_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    cc_michael_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    interac_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    cash_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
