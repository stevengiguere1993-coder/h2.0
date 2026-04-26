"""ProspectionLead — chantiers repérés en mode drive-by.

Module Prospection séparé du CRM existant :
- CRM = leads entrants (formulaire public, prospects qui nous contactent)
- Prospection = leads sortants (on roule, on voit un multi-logement,
  on prend une photo, on cherche le propriétaire pour le contacter)

Cible Horizon : multi-logements 4-20 portes, terrains à
développer/redévelopper, semi-commercial. Zone : Montréal + Rive-Sud.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class ProspectionLeadKind(str, Enum):
    MULTILOGEMENT = "multilogement"
    TERRAIN = "terrain"
    SEMI_COMMERCIAL = "semi_commercial"
    AUTRE = "autre"


class ProspectionLeadStatus(str, Enum):
    A_VISITER = "a_visiter"  # repéré, pas encore visité de près
    VISITE = "visite"  # visite de drive-by faite
    A_CONTACTER = "a_contacter"  # propriétaire identifié, à contacter
    CONTACTE = "contacte"  # contact initial fait
    SOUMISSIONNE = "soumissionne"  # soumission envoyée
    CONVERTI = "converti"  # contrat signé
    PERDU = "perdu"  # refusé / pas intéressé / mauvais timing


class ProspectionOwnerKind(str, Enum):
    PARTICULIER = "particulier"
    CORPORATION = "corporation"
    INCONNU = "inconnu"


class ProspectionLead(Base, TimestampUpdateMixin):
    __tablename__ = "prospection_leads"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Métadonnées de capture
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Identité du lead
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProspectionLeadKind.MULTILOGEMENT.value,
        server_default=ProspectionLeadKind.MULTILOGEMENT.value,
    )

    # Localisation
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)

    # Notes terrain
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Pipeline
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProspectionLeadStatus.A_VISITER.value,
        server_default=ProspectionLeadStatus.A_VISITER.value,
        index=True,
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )  # 1-5 étoiles

    # Données du rôle d'évaluation (Phase 2 — fillées par lookup auto)
    matricule: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    nb_logements: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    annee_construction: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    valeur_fonciere: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    superficie_terrain: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True  # en m²
    )

    # Propriétaire (Phase 2 — résolu via REQ ou rôle)
    owner_kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ProspectionOwnerKind.INCONNU.value,
        server_default=ProspectionOwnerKind.INCONNU.value,
    )
    owner_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    owner_address: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    owner_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    owner_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    owner_neq: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True  # Numéro Entreprise Québec si corp
    )

    # Suivi
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    contact_attempts_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Conversion vers le pipeline interne
    converted_to_contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    converted_to_project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Soft-delete
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
