"""Offre d'achat ultra-minimaliste — flow inspiré de DuProprio.

Modèle dédié au formulaire « 5 champs » sur la page d'un deal du
Pipeline. Pas de versioning, pas de templates configurables, pas de
milestones — on garde tout au plus simple possible.

Le PurchaseAgreement complet (modèle calqué sur duProprio v4.7) reste
disponible pour les offres formelles avec négociations. Le présent
modèle Offer sert au cas d'usage « envoyer rapidement une offre
initiale » que Phil veut pouvoir réaliser en moins de 30 secondes.

Une `Offer` est attachée à un `ProspectionDeal` (et non à un lead) et
porte tous les champs utiles à l'envoi + signature électronique :
prix, conditions, deadlines, tokens de signature.
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class OfferStatus(str, Enum):
    """Statuts du cycle de vie d'une Offer.

    - brouillon : créée mais pas encore envoyée
    - envoye    : email parti au vendeur, en attente de réponse
    - signe     : vendeur a signé et accepté (équivalent « accepté »)
    - refuse    : vendeur a explicitement refusé
    - expire    : date_limite_reponse dépassée sans réponse
    """

    BROUILLON = "brouillon"
    ENVOYE = "envoye"
    SIGNE = "signe"
    REFUSE = "refuse"
    EXPIRE = "expire"


# Valeur boilerplate par défaut pour les inclusions standards d'une
# offre d'achat résidentielle. Ce texte est inscrit dans le PDF si
# l'utilisateur ne saisit rien — adapté au cas typique Horizon
# (immeubles à revenus).
DEFAULT_INCLUSIONS = (
    "Tous les éléments fixés à demeure (luminaires, stores, "
    "rideaux, tringles, électroménagers, chauffe-eau, fournaise, "
    "thermopompe, accessoires de salle de bain et de cuisine) "
    "selon usage et conformément à la loi."
)


class Offer(Base, TimestampUpdateMixin):
    """Offre d'achat minimaliste reliée à un Deal du Pipeline."""

    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    deal_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_deals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ----- Champs saisis par l'utilisateur (5 visibles max) -----
    prix_offert: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    date_possession: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    date_limite_reponse: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    vendeur_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    vendeur_nom: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # ----- Conditions standards (3 cases à cocher) -----
    condition_inspection: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    condition_inspection_delai_jours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    condition_financement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    condition_financement_delai_jours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=21, server_default="21"
    )
    condition_vente: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # ----- Pré-rempli auto -----
    acompte: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2),
        nullable=True,
        default=1000,
        server_default="1000",
    )
    inclusions: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=DEFAULT_INCLUSIONS,
        server_default=DEFAULT_INCLUSIONS,
    )

    # ----- Statut & signature -----
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=OfferStatus.BROUILLON.value,
        server_default=OfferStatus.BROUILLON.value,
        index=True,
    )
    signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    signed_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_ip: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
