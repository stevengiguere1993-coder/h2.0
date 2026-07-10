"""Punch (time entry) — replaces Monday 'Temps (PUNCH)' board."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class Punch(Base, TimestampUpdateMixin):
    __tablename__ = "punches"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    employe_id: Mapped[int] = mapped_column(
        ForeignKey("employes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Lets employees clock hours against a prospect before a project
    # exists — typically visits, quoting and soumission preparation.
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    hours: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)

    task: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    geolocation: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # 'lat,lng'
    approved: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    # Phase B — refacturation des heures.
    # Date où le punch a été versé sur une facture client. Garde-fou
    # contre la double-facturation. Plusieurs punches peuvent pointer
    # vers la même `facture_item_id` (regroupement par employé × taux
    # à l'import).
    invoiced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    facture_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("facture_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Heures pointées DIRECTEMENT sur un bon de travail interne (entretien
    # de nos immeubles) plutôt que sur un projet → le coût remonte au bon.
    bon_travail_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("bons_travail.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Feuille de temps QBO (TimeActivity) créée pour ce punch — les heures
    # apparaissent dans le SUIVI DE PROJET QuickBooks (rentabilité) SANS
    # écriture comptable (la paie est déjà au grand livre). Idempotence du
    # push : un punch déjà lié n'est pas recréé ; supprimé/désapprouvé →
    # le TimeActivity QB est retiré.
    qbo_time_activity_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
