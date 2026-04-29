"""Valeurs par défaut pour les Promesses d'achat — un singleton (id=1)
édité depuis /prospection/parametres. Appliqué à la création d'une
nouvelle PA en complément du pré-remplissage depuis le lead.
"""

from typing import Optional

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class PurchaseAgreementTemplate(Base, TimestampUpdateMixin):
    __tablename__ = "purchase_agreement_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Defaults financement
    financing_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="hypothecaire",
        server_default="hypothecaire",
    )
    financing_min_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    financing_max_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 3), nullable=True
    )
    financing_amortization_years: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    financing_min_term_years: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # Defaults conditions
    inspection_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    inspection_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    visit_units_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    water_septic_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Defaults sections texte libre (clauses standards Horizon)
    baux_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inclusions_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exclusions_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    other_conditions_text: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Acheteur principal (Horizon ou société porteuse)
    default_buyer_1_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    default_buyer_1_address: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    default_buyer_1_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    default_buyer_1_phone_day: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
