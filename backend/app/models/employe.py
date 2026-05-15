"""Employee / staff member (internal + partners)."""

from typing import Optional

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class Employe(Base, TimestampUpdateMixin):
    __tablename__ = "employes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # e.g. foreman, plumber, electrician
    # Taux coûtant (ce qu'Horizon paie à l'employé).
    hourly_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    # Taux facturé au client final. Sert à l'import des punches sur une
    # facture. NULL = on retombe sur `hourly_rate` (rétrocompat). Permet
    # de découpler le coût interne du prix vendu au client.
    billing_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    is_partner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    # ---- Profil RH ----
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    license_number: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    emergency_contact_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    emergency_contact_phone: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )

    # ---- CCQ + paie ----
    # Si l'employé est CCQ, le coût horaire réel est majoré (cotisations
    # CCQ : assurance, fonds de formation, vacances, RVER…). En plus,
    # la prime CNESST s'ajoute systématiquement (rate de l'unité d'emploi
    # × salaire imposable). Stocké comme % en décimal — ex. 0.085 = 8,5 %.
    is_ccq: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    cnesst_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 4), nullable=True
    )
    ccq_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 4), nullable=True
    )

    # URL personnel chez Employeur D (espace employé pour les talons de
    # paie). On stocke l'URL complète plutôt que de deviner — chaque
    # employé a une page différente.
    employeur_d_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
