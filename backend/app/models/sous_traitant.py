"""Sous-traitant — subcontracted trade (electrician, plumber, etc.)

Separate from `Fournisseur` (material supplier) so we can capture
construction-specific fields: RBQ license, insurance, hourly rate,
trade specialties.
"""

from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class SousTraitant(Base, TimestampUpdateMixin):
    __tablename__ = "sous_traitants"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Identity
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Régions desservies — liste séparée par virgules parmi un
    # ensemble fixe (Montréal, Longueuil, Laval, Sorel, Châteauguay,
    # Saint-Constant, Vaudreuil). Un sous-traitant peut couvrir
    # plusieurs régions ; même format que `trades`.
    region: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )

    # RBQ (Regie du batiment du Quebec) licensing
    rbq_license: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    rbq_expires_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Liability insurance
    insurance_provider: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    insurance_policy_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    insurance_expires_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Trade & pricing
    # Comma-separated list of specialties: "plomberie, electricite, ceramique"
    trades: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    hourly_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1..5 (note générale, legacy)

    # Frais de déplacement — certains sous-traitants facturent un
    # déplacement, d'autres non ; ça impacte le prix final. `charges_travel_fee`
    # = drapeau oui/non, `travel_fee_amount` = montant indicatif (CAD),
    # `travel_fee_notes` = précisions (ex. « 0,60 $/km au-delà de 30 km »).
    charges_travel_fee: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )
    travel_fee_amount: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    travel_fee_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Qualifications 1..5 on four axes — the overall score shown in the UI
    # is the mean of the axes that are filled in.
    competence_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    availability_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    punctuality_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quality_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Lifecycle
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
