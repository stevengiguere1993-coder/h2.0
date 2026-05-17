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
    """Pipeline buy-flow Horizon — l'immeuble est repéré pour l'acheter
    (pas pour le rénover comme un client classique). Les statuts
    suivent les étapes d'acquisition immobilière au Québec.

    Branche après « offre acceptée » :
    - Acheter (deal_strategy=keep) : inspection → nego → notaire → acheté
    - Flip (deal_strategy=flip)    : en_cession → cédé (assignation
      de promesse d'achat à un autre investisseur)
    """

    A_VISITER = "a_visiter"  # repéré, pas encore visité de près
    VISITE = "visite"  # visite drive-by faite
    A_CONTACTER = "a_contacter"  # proprio identifié, à contacter
    CONTACTE = "contacte"  # contact initial fait
    HOT_LEAD = "hot_lead"  # lead très chaud — notification équipe
    COLD_LEAD = "cold_lead"  # lead refroidi — à laisser de côté pour l'instant
    A_RECONTACTER = "a_recontacter"  # snooze avec date — relance automatique
    SOUMISSIONNE = "soumissionne"  # OFFRE SOUMISE (renamed in UI)
    OFFRE_ACCEPTEE = "offre_acceptee"  # promesse d'achat acceptée
    EN_INSPECTION = "en_inspection"  # inspection en cours (path keep)
    EN_NEGO = "en_nego"  # négociation post-inspection (path keep)
    CHEZ_NOTAIRE = "chez_notaire"  # chez le notaire (path keep)
    EN_CESSION = "en_cession"  # cession en cours (path flip)
    CONVERTI = "converti"  # ACHETÉ par nous ou CÉDÉ via assignation
    PERDU = "perdu"  # refusé / pas vendable / retiré


class ProspectionOwnerKind(str, Enum):
    PARTICULIER = "particulier"
    CORPORATION = "corporation"
    INCONNU = "inconnu"


class ProspectionDealStrategy(str, Enum):
    """Stratégie de sortie du deal : on garde l'immeuble (acquisition
    pour notre portefeuille) ou on flip (revente de la promesse
    d'achat à un autre investisseur)."""

    UNDECIDED = "undecided"  # pas encore décidé
    KEEP = "keep"  # acheter pour nous
    FLIP = "flip"  # céder à un autre investisseur


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

    # Stratégie de deal : achat pour nous (keep) ou cession à un
    # autre investisseur (flip / wholesaling). « undecided » par
    # défaut tant qu'on n'a pas pris la décision.
    deal_strategy: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ProspectionDealStrategy.UNDECIDED.value,
        server_default=ProspectionDealStrategy.UNDECIDED.value,
        index=True,
    )
    # Prix d'achat soumis dans la promesse d'achat (offre faite au
    # propriétaire actuel). Différent du purchase_price qui est le
    # prix d'achat HISTORIQUE du proprio actuel.
    offer_amount: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    # Si flip : montant payé par l'investisseur final pour reprendre
    # notre promesse d'achat (cession). Notre profit = assignment_price
    # - offer_amount.
    assignment_price: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
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
    # Date à laquelle ce lead doit être recontacté (status =
    # `a_recontacter`). Quand cette date arrive ou est dépassée, un
    # processus de réveil (lazy promotion sur l'endpoint list) bascule
    # le lead vers `a_contacter` pour qu'il réapparaisse dans la file
    # active. Si NULL au moment du drop dans « À recontacter », on
    # auto-set à +6 mois côté API.
    recontact_at: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
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

    # Identifiant Monday — set quand le lead est importé depuis le
    # board CRM 7714284220. Permet l'import idempotent : ré-import
    # = UPDATE sans doublons.
    monday_item_id: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )

    # URL du dossier Google Drive du lead. Bouton « Drive » dans le
    # header de la fiche y mène. NULL = pas configuré.
    drive_folder_url: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True
    )
