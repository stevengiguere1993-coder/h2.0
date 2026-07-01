"""Project model for managing construction projects.

A Project represents an actual chantier / contract once a soumission
is accepted (or when we set one up manually). Everything else —
agenda events, bons de travail, punches, factures — hangs off it.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.client import Client


class ProjectStatus(str, Enum):
    PLANNED = "planned"           # « À planifier » dans l'UI
    READY_TO_START = "ready_to_start"  # « En attente de début »
    IN_PROGRESS = "in_progress"
    SUSPENDED = "suspended"
    # « Correction / Amélioration » — retour client avant la livraison
    # finale (Flux A). Les coûts de retour s'accumulent sur le projet.
    CORRECTION = "correction"
    DELIVERED = "delivered"


class Project(Base):
    """Construction project / chantier."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Links (all optional — a project can start from a Client, a
    # prospect contact_request, or directly from an accepted soumission).
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    soumission_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("soumissions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Responsable du projet : l'employé/user vers qui router un appel de
    # suivi d'un client existant (téléphonie). NULL => ancienne logique.
    responsible_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProjectStatus.PLANNED.value,
        index=True,
    )
    # Statut de la CORRECTION du projet (Flux A) : "a_planifier" (défaut),
    # "planifie", "termine". Une correction regroupe tous les points à
    # reprendre, faits d'un coup.
    correction_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="a_planifier"
    )
    # Type de projet : "construction" (défaut) ou "bon_travail" (ordre de
    # travail assignable — réutilise la plomberie projet : achats, heures,
    # facture). Permet de séparer les deux vues sans nouvelle table.
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="construction", index=True
    )

    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ID du « Job » QuickBooks (sous-client) représentant ce projet, une
    # fois synchronisé. Sert de clé d'idempotence pour ne pas recréer de
    # doublon et pour rattacher les factures au bon projet côté QBO.
    qbo_job_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    # Id de la Purchase QB qui porte le COÛT DE MAIN-D'ŒUVRE Kratos de ce
    # projet (heures × coût réel). Clé d'idempotence : on met à jour cette
    # dépense au lieu d'en recréer une à chaque synchro.
    qbo_labour_purchase_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    budget: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)

    # Permet à l'utilisateur de remplacer le calcul automatique des
    # heures de main-d'œuvre projetées (sinon = somme des phases ×
    # personnes assignées × 8 h/jour ouvrable). Exprimé en heures.
    estimated_hours_override: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 2), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    client: Mapped[Optional["Client"]] = relationship(
        "Client",
        back_populates="projects",
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name='{self.name}', status='{self.status}')>"
