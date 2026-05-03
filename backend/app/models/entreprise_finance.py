"""Suivi financier mensuel par entreprise + plan de valorisation.

`EntrepriseFinanceSnapshot` : un row par (entreprise, mois). Stocke
revenu, dépenses, EBITDA, trésorerie, valorisation estimée. Permet
graphique évolution + comparaison inter-entreprises.

`EntrepriseValuePlan` : plan de création de valeur (target valorisation,
multiple sectoriel, drivers en JSON). Une seule ligne active par
entreprise.

`EntrepriseValueMilestone` : jalons mesurables vers la cible.
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class FinanceSource(str, Enum):
    MANUEL = "manuel"
    QBO = "qbo"               # importé depuis QuickBooks Online
    BANQUE = "banque"         # connexion bancaire (Plaid/Flinks futur)
    ESTIMATION = "estimation" # interne, pas encore vérifié


class MilestoneStatus(str, Enum):
    A_VENIR = "a_venir"
    EN_COURS = "en_cours"
    ATTEINT = "atteint"
    MANQUE = "manque"


class EntrepriseFinanceSnapshot(Base, TimestampUpdateMixin):
    """Snapshot financier mensuel d'une entreprise.

    Un seul snapshot par (entreprise, year_month) — upsert via la
    contrainte unique. Permet de garder l'historique pour le graphique
    d'évolution P&L + cash + valorisation.
    """

    __tablename__ = "entreprise_finance_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Format : YYYY-MM-01 (toujours le 1er du mois).
    year_month: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )

    # Compte de résultat
    revenu: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    depenses: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    ebitda: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    resultat_net: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    # Trésorerie / bilan
    tresorerie: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    dette_long_terme: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    # Valorisation estimée à ce mois (calculée ou saisie).
    valorisation_estimee: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    # Source des chiffres (manuel / QBO / banque / estimation).
    source: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=FinanceSource.MANUEL.value,
        server_default=FinanceSource.MANUEL.value,
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "entreprise_id", "year_month",
            name="uq_entreprise_finance_month",
        ),
    )


class EntrepriseValuePlan(Base, TimestampUpdateMixin):
    """Plan de création de valeur d'une entreprise.

    Une seule ligne active (is_active=True) par entreprise. Les anciens
    plans sont conservés pour historique en passant is_active=False.
    """

    __tablename__ = "entreprise_value_plans"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Cible : on veut atteindre X $ de valorisation à la date Y.
    target_valuation: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Multiple sectoriel utilisé pour l'estimation auto :
    # valorisation_estimee = ebitda × multiple_ebitda
    # OU revenu × multiple_revenu si EBITDA pas dispo.
    multiple_ebitda: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    multiple_revenu: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 2), nullable=True
    )

    # Drivers de valeur en JSON libre :
    # [{key, label, current, target, unit}, ...]
    # Ex. [{"key":"ebitda_margin","label":"Marge EBITDA","current":12,"target":25,"unit":"%"}]
    drivers_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Note de stratégie / thèse d'investissement.
    these: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        index=True,
    )


class EntrepriseValueMilestone(Base, TimestampUpdateMixin):
    """Jalon mesurable d'un plan de valorisation."""

    __tablename__ = "entreprise_value_milestones"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("entreprise_value_plans.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    label: Mapped[str] = mapped_column(String(255), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_value: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    metric: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )  # ex. "revenu", "ebitda", "valorisation"

    status: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=MilestoneStatus.A_VENIR.value,
        server_default=MilestoneStatus.A_VENIR.value,
        index=True,
    )

    achieved_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    achieved_value: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
