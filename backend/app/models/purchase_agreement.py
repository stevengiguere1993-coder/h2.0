"""Promesse d'achat (PA) — offre d'achat immobilier émise depuis le
module Prospection vers le propriétaire d'un lead.

Modèle calqué sur le template duProprio v4.7 (2023-06-28). Les
sections texte libre (baux, inclusions, exclusions, autres conditions)
sont stockées telles quelles pour rester modifiables sans schéma rigide.

Flow signature en 2 étapes :
- Acheteur interne (Horizon) signe en premier via lien interne au portail,
  marque la PA `pending_seller_signature`.
- Vendeur reçoit ensuite le lien tokenisé par email et choisit
  Accepter / Refuser via la page publique.
"""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class PurchaseAgreementStatus(str, Enum):
    DRAFT = "draft"
    PENDING_BUYER_SIGNATURE = "pending_buyer_signature"
    PENDING_SELLER_SIGNATURE = "pending_seller_signature"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PurchaseAgreement(Base, TimestampUpdateMixin):
    __tablename__ = "purchase_agreements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    reference: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False
    )

    lead_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PurchaseAgreementStatus.DRAFT.value,
        server_default=PurchaseAgreementStatus.DRAFT.value,
        index=True,
    )

    # ----- Section 1: Identification des parties -----
    buyer_1_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_1_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    buyer_1_phone_day: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    buyer_1_phone_eve: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    buyer_1_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    buyer_2_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_2_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    buyer_2_phone_day: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    buyer_2_phone_eve: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    buyer_2_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    seller_1_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    seller_1_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    seller_1_phone_day: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    seller_1_phone_eve: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    seller_1_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    seller_2_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    seller_2_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    seller_2_phone_day: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    seller_2_phone_eve: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    seller_2_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    # ----- Section 2: Objet du contrat -----
    property_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    lot_designation: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lot_width: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    lot_depth: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    lot_dimension_unit: Mapped[Optional[str]] = mapped_column(
        String(4), nullable=True  # "m" ou "pi"
    )
    lot_area: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    lot_area_unit: Mapped[Optional[str]] = mapped_column(
        String(4), nullable=True  # "m2" ou "pi2"
    )

    # ----- Section 3: Prix et modalités -----
    price: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    down_payment: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    mortgage_amount: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    deposit_amount: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    deposit_notary: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # ----- Section 4: Acheteur -----
    visit_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    rented_appliances_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ----- Section 5: Vendeur (déclarations capturables) -----
    annual_rents: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    leases_expiry_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ----- Section 6: Conditions -----
    financing_kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="hypothecaire",
        server_default="hypothecaire",  # ou "comptant"
    )
    financing_min_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True  # % minimum hypothèque demandé
    )
    financing_max_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 3), nullable=True  # % max taux d'intérêt
    )
    financing_amortization_years: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    financing_min_term_years: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

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

    buyer_property_sale_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    buyer_property_address: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    buyer_property_deadline: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )

    conditional_other_offer_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    other_offer_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # ----- Section 7: Transfert et occupation -----
    act_of_sale_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    occupation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    occupation_time: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    occupation_compensation_per_month: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    baux_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inclusions_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exclusions_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ----- Section 8: Autres conditions -----
    other_conditions_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ----- Section 9: Délai d'acceptation -----
    acceptance_deadline_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    acceptance_deadline_time: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True
    )

    # ----- Section 10/11: Signatures -----
    # Étape 1 — signature acheteur (interne, link envoyé au user qui signe
    # comme buyer_1, puis status -> pending_seller_signature)
    buyer_signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    buyer_signed_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    buyer_signed_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    buyer_signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    buyer_signature_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    buyer_signature_image_content_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    # Étape 2 — signature vendeur (publique, link tokenisé envoyé par email)
    seller_signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    seller_signed_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    seller_signed_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    seller_signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    seller_signature_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    seller_signature_image_content_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    seller_response: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True  # "accepted" ou "rejected"
    )
    seller_rejection_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Timestamps & métadonnées
    sent_to_seller_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Notes internes (jamais rendues sur le PDF ni la page publique)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
