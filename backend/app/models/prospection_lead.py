"""ProspectionLead — chantiers repérés en mode drive-by.

Module Prospection séparé du CRM existant :
- CRM = leads entrants (formulaire public, prospects qui nous contactent)
- Prospection = leads sortants (on roule, on voit un multi-logement,
  on prend une photo, on cherche le propriétaire pour le contacter)

Cible Horizon : multi-logements 4-20 portes, terrains à
développer/redévelopper, semi-commercial. Zone : Montréal + Rive-Sud.
"""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
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

    # Scoring & tags automatiques (recalculés serveur-side à chaque
    # modification du lead). `score` 0-100 pondère les critères Horizon
    # (multi-logements 4-20 portes, vieux bâtiments, corp., etc.).
    # `tags` est un JSON-encoded array de strings.
    score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", index=True
    )
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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

    # Données financières pour calcul de l'equity. À remplir
    # manuellement (sources fiables : JLR payant, ou rumeur de quartier).
    purchase_price: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    purchase_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    mortgage_balance: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    # Drapeaux fiscaux (saisis manuellement par le prospecteur quand
    # il voit un avis de vente pour taxes affiché à la propriété, ou
    # qu'il l'apprend du proprio).
    tax_delinquent: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    tax_year_paid: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    tax_amount: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Adresse postale du proprio si différente de la propriété
    # (Absentee Owner pattern). owner_address existe déjà mais
    # on garde les deux : owner_address pour l'adresse complète,
    # mailing_address pour distinguer un proprio « hors site ».
    mailing_address: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
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
