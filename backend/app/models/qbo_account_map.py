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
    # Compte de dépense pour les factures de SOUS-TRAITANT (achat.kind ==
    # 'sub_invoice' ou achat.sous_traitant_id renseigné). Quand une facture
    # de sous-traitant est poussée vers QB, sa ligne est classée sur ce
    # compte (« Sous-traitant ») plutôt que sur le compte matériaux.
    sous_traitant_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Compte chèque Horizon — pour paiements immédiats par chèque
    # (Purchase QB, crédite ce compte directement).
    cheque_horizon_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Cartes de crédit Horizon (4 cartes). Toutes routées comme
    # Purchase QB qui crédite la carte au lieu du chèque.
    cc_steven_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    cc_michael_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    cc_olivier_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    cc_christian_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Coût de MAIN-D'ŒUVRE poussé sur le projet QB (heures Kratos × coût réel) :
    # - labour_expense_account  = compte de DÉPENSE débité (le coût du projet) ;
    # - labour_clearing_account = compte de CONTREPARTIE crédité (compte de
    #   répartition / salaires à payer), réconcilié ensuite avec la paie.
    labour_expense_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    labour_clearing_account: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
