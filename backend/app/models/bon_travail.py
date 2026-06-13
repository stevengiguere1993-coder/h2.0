"""Bon de travail (work order) — can be sent to the client for signature."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class BonTravailStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    SIGNED = "signed"
    CANCELLED = "cancelled"


class BonTravail(Base, TimestampUpdateMixin):
    __tablename__ = "bons_travail"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )

    amount: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=BonTravailStatus.DRAFT.value, index=True
    )

    # Adresse du chantier (lieu des travaux) — clé de classement de la
    # liste : adresse → client → numéro, comme soumissions / projets.
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Nature du montant chargé au client :
    #  - "garantie"        → 0 $ (travaux sous garantie, non facturés)
    #  - "temps_materiel"  → T&M : selon punchs (heures) + achats (coût+markup)
    bon_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="temps_materiel"
    )

    # Employé/user assigné au bon — il devient une tâche pour lui
    # (apparait dans son tableau de bord « à faire »).
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Demande interne (ex. gestion immobilière) : pas de signature client
    # requise. Par défaut True (un bon construction part chez le client).
    requires_signature: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # Volet d'origine du bon : "gestion_immo" quand il est créé depuis la
    # zone Gestion immobilière (réparation d'immeuble), sinon NULL/"construction".
    # Sert au miroir lecture seule côté gestion immobilière.
    origin: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)

    sent_to_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_by_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    signature_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Public e-signature token for the client-facing link.
    signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )

    # Drawn signature captured from the public signing page.
    signature_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    signature_image_content_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
