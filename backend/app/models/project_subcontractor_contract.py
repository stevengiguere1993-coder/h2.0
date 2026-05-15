"""Termes de facturation d'un sous-traitant pour un projet donné.

Quand un sous-traitant facture Horizon (heures × taux ou montant
forfaitaire), Horizon refacture le client final selon les termes
négociés au projet — qui diffèrent souvent du taux global du
sous-traitant.

Trois modes de facturation supportés :
  * markup_pct      cost × (1 + markup_percent / 100)
  * flat_hourly     hours × flat_hourly_rate (override total)
  * lump_sum        montant forfaitaire fixe sur le projet
"""

from typing import Optional

from sqlalchemy import Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin

#: Modes de facturation supportés.
BILLING_MODES = ("markup_pct", "flat_hourly", "lump_sum")


class ProjectSubcontractorContract(Base, TimestampUpdateMixin):
    __tablename__ = "project_subcontractor_contracts"
    __table_args__ = (
        # Un seul contrat par couple (projet, sous-traitant) : si on doit
        # renégocier, on édite le contrat existant plutôt que d'en créer
        # un nouveau.
        UniqueConstraint(
            "project_id",
            "sous_traitant_id",
            name="uq_proj_subcontract",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sous_traitant_id: Mapped[int] = mapped_column(
        ForeignKey("sous_traitants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    billing_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="markup_pct",
        server_default="markup_pct",
    )
    # Utilisé en mode markup_pct uniquement (% à ajouter au coûtant).
    markup_percent: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    # Utilisé en mode flat_hourly uniquement (taux $/h appliqué aux
    # heures saisies sur la facture du sous-traitant).
    flat_hourly_rate: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    # Utilisé en mode lump_sum uniquement (montant fixe total).
    lump_sum_amount: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ProjectSubcontractorContract(id={self.id}, "
            f"project={self.project_id}, sous_traitant={self.sous_traitant_id}, "
            f"mode={self.billing_mode})>"
        )
