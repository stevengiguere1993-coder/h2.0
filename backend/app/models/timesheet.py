"""Feuille de temps (timesheet) — pôle Gestion d'entreprise.

Reproduit le fichier Excel « Heures employé » de façon scalable :
- une liste de compagnies partagée (``TimesheetCompany``) avec un taux de
  refacturation propre à chacune ;
- une feuille par employé et par période de paie (``Timesheet``,
  bi-hebdomadaire = 14 jours) avec un taux horaire (paie) et un taux de
  refacturation par défaut ;
- les heures saisies par compagnie et par jour (``TimesheetEntry``).

Chaque employé ne voit que ses propres feuilles ; les gestionnaires
(manager/admin/owner) voient et approuvent celles de tout le monde.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin

# Statuts d'une feuille de temps.
TIMESHEET_STATUSES = ("brouillon", "soumis", "approuve")

# Période bi-hebdomadaire : 14 jours (2 semaines de Lun à Dim).
TIMESHEET_DAYS = 14


class TimesheetCompany(Base, TimestampUpdateMixin):
    """Compagnie à laquelle un employé peut imputer des heures.

    Liste partagée par tous les employés. Chaque compagnie porte son propre
    taux de refacturation (certaines facturées au coût, d'autres avec marge).
    """

    __tablename__ = "timesheet_companies"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Taux de refacturation propre à la compagnie ($/h). Si NULL, on retombe
    # sur le taux de refacturation par défaut de la feuille.
    # Compagnie NON REFACTURABLE (retour Phil 2026-07-22) : les heures
    # comptent pour la paie mais refacturation = 0 (travail interne).
    # Colonne additive -> ensure_critical_columns.
    refacturable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    taux_refacturation: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )


class Timesheet(Base, TimestampUpdateMixin):
    """Feuille de temps d'un employé pour une période de paie (14 jours)."""

    __tablename__ = "timesheets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "period_start", name="uq_timesheet_user_period"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # Taux horaire versé à l'employé ($/h) et taux de refacturation par défaut.
    taux_horaire: Mapped[float] = mapped_column(
        Float, nullable=False, default=11.0, server_default="11"
    )
    taux_refacturation: Mapped[float] = mapped_column(
        Float, nullable=False, default=33.0, server_default="33"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon",
        server_default="brouillon",
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Notes par compagnie, encodées JSON {company_id: "texte"}.
    notes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class TimesheetUserRate(Base, TimestampUpdateMixin):
    """Taux de refacturation PROPRE à un couple (employé, compagnie).

    Chaque employé a son taux horaire et son taux de refacturation (sur la
    feuille), et le taux de refacturation peut en plus varier par compagnie
    POUR CET EMPLOYÉ (retour Phil 2026-07-22). Héritage d'une ligne :
    override employé → taux de la compagnie → défaut de la feuille.
    ``refacturable`` NULL = hérite du réglage de la compagnie.
    """

    __tablename__ = "timesheet_user_rates"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "company_id", name="uq_timesheet_user_rate"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("timesheet_companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taux_refacturation: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    refacturable: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )


class TimesheetReglement(Base, TimestampUpdateMixin):
    """Règlement enregistré contre le cumul d'un employé.

    ``kind`` = "paie" (on a payé l'employé) ou "refacturation" (on a
    refacturé la compagnie ``company_id`` pour ses heures). Le dashboard
    calcule solde = dû cumulé (toutes les feuilles) − règlements.
    """

    __tablename__ = "timesheet_reglements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("timesheet_companies.id", ondelete="SET NULL"),
        nullable=True,
    )
    montant: Mapped[float] = mapped_column(Float, nullable=False)
    date_reglement: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TimesheetEntry(Base, TimestampUpdateMixin):
    """Heures saisies pour (feuille, compagnie, jour).

    ``day_index`` va de 0 à 13 (Lun S1 … Dim S2). Seules les cases non nulles
    sont stockées.
    """

    __tablename__ = "timesheet_entries"
    __table_args__ = (
        UniqueConstraint(
            "timesheet_id",
            "company_id",
            "day_index",
            "refacturable",
            name="uq_timesheet_entry_cell_v2",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    timesheet_id: Mapped[int] = mapped_column(
        ForeignKey("timesheets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("timesheet_companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # La grille a DEUX blocs par semaine (retour Phil 2026-07-22) : heures
    # refacturables et heures NON refacturables. Les deux comptent pour la
    # paie ; seules les refacturables entrent dans la refacturation.
    # Colonne additive -> ensure_critical_columns + swap de contrainte
    # unique dans ensure_timesheet_tables.
    refacturable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
