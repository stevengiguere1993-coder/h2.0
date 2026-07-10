"""Modèles du volet Gestion immobilière.

Inspiré des meilleurs PMS US (AppFolio, Yardi, Buildium) + Plexflow
+ ProprioExpert. Adapté au contexte québécois : matricule MAMH,
TPS/TVQ, baux résidentiels Régie du logement.

Conventions :
- Tous les modèles préfixés `imm_` côté SQL pour les distinguer des
  modèles construction/prospection.
- Ownership multi-entreprises via `imm_immeuble_ownership` (analogue
  à EntreprisePartner pour les entreprises).
- Lien optionnel à `mtl_property_units.matricule` pour le rôle
  d'évaluation déjà importé.
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
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampUpdateMixin


# ─── ENUMS ──────────────────────────────────────────────────────────────


class ImmeubleType(str, Enum):
    RESIDENTIEL = "residentiel"        # multi-logements résidentiel
    COMMERCIAL = "commercial"
    MIXTE = "mixte"
    UNIFAMILIAL = "unifamilial"
    AUTRE = "autre"


class LogementStatus(str, Enum):
    OCCUPE = "occupe"
    VACANT = "vacant"
    RESERVE = "reserve"  # bail signé pas encore commencé
    HORS_LOC = "hors_location"  # rénovation, propriétaire-occupé…


class BailStatus(str, Enum):
    ACTIF = "actif"
    TERMINE = "termine"
    RESILIE = "resilie"
    PROPOSE = "propose"  # bail signé pas encore commencé


class BailRenouvellementStatus(str, Enum):
    PROPOSE = "propose"     # avis envoyé au locataire
    ACCEPTE = "accepte"
    REFUSE = "refuse"
    EN_NEGOCIATION = "en_negociation"


class HypothequeStatus(str, Enum):
    ACTIVE = "active"
    REMBOURSEE = "remboursee"
    REFINANCEE = "refinancee"


class EvaluationKind(str, Enum):
    MUNICIPALE = "municipale"     # rôle d'évaluation
    MARCHANDE = "marchande"       # comparables
    APPRAISAL = "appraisal"       # évaluation pro
    AUTO = "auto"                 # estimation interne


class MaintenanceStatus(str, Enum):
    OUVERT = "ouvert"
    EN_COURS = "en_cours"
    EN_ATTENTE = "en_attente"     # pièce, fournisseur, locataire
    TERMINE = "termine"
    ANNULE = "annule"


class MaintenancePriorite(str, Enum):
    URGENCE = "urgence"           # ex. fuite eau, sans chauffage
    HAUTE = "haute"
    NORMALE = "normale"
    BASSE = "basse"


# ─── IMMEUBLE ───────────────────────────────────────────────────────────


class Immeuble(Base, TimestampUpdateMixin):
    """Immeuble locatif (multi-logements ou unifamilial)."""

    __tablename__ = "imm_immeubles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    address: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        default=ImmeubleType.RESIDENTIEL.value,
        server_default=ImmeubleType.RESIDENTIEL.value,
    )
    annee_construction: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    nb_logements: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    superficie_terrain: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    superficie_batiment: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # Lien rôle d'évaluation MAMH (matricule). Permet de récupérer
    # automatiquement valeur municipale + nb logements depuis la table
    # mtl_property_units déjà importée.
    matricule: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )

    # Acquisition
    purchase_price: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    purchase_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Photo de couverture : soit URL externe, soit blob uploadé directement.
    # Si `cover_photo_blob` est rempli, le frontend utilise l'endpoint de
    # stream pour récupérer l'image ; sinon il fallback sur `cover_photo_url`.
    cover_photo_url: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True
    )
    cover_photo_blob: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    cover_photo_content_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Contact d'urgence de l'immeuble (concierge/gestionnaire). Quand Léa
    # détecte une urgence locataire (dégât d'eau, effraction, feu…), elle
    # transfère ICI d'abord, puis repli sur le numéro de garde global.
    # Colonne additive (cf. db/session.py).
    urgence_phone: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Gestion externe : l'immeuble est géré par une compagnie tierce →
    # exclu des flux opérationnels (paiements de loyers, renouvellements,
    # dépôts, relances). Les finances macro (P&L, prévisionnel) restent
    # incluses. Colonnes additives (cf. db/session.py).
    gestion_externe: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    gestionnaire_externe_nom: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    gestionnaire_externe_contact: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Scope du catalogue (immeubles créés depuis le picker de tâche).
    # Au plus l'un des deux est rempli. Tous deux NULL = immeuble
    # « global » (legacy ou créé via le CRUD complet du volet immo).
    owner_entreprise_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    owner_deal_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )


class ImmeubleOwnership(Base):
    """Quelle entreprise détient quel immeuble, à quel %.

    Plusieurs entreprises peuvent co-détenir un immeuble (partenariat
    Atelier Boréal 60% + Pivot Conseil 40% par exemple)."""

    __tablename__ = "imm_immeuble_ownerships"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ownership_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=100.0,
        server_default="100",
    )


# ─── LOGEMENT (unité dans un immeuble) ─────────────────────────────────


class Logement(Base, TimestampUpdateMixin):
    """Unité locative dans un immeuble."""

    __tablename__ = "imm_logements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    numero: Mapped[str] = mapped_column(String(32), nullable=False)

    # Caractéristiques (nb pièces FR : 3½, 4½, 5½…)
    nb_pieces_decimal: Mapped[Optional[float]] = mapped_column(
        Numeric(3, 1), nullable=True
    )  # 3.5 = 3½
    nb_chambres: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    nb_sdb: Mapped[Optional[float]] = mapped_column(
        Numeric(3, 1), nullable=True
    )  # 1, 1.5, 2…
    superficie_pi2: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 1), nullable=True
    )

    etage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        default=ImmeubleType.RESIDENTIEL.value,
        server_default=ImmeubleType.RESIDENTIEL.value,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=LogementStatus.VACANT.value,
        server_default=LogementStatus.VACANT.value,
        index=True,
    )

    # Loyer demandé (référence pour les annonces, ne reflète pas
    # forcément le bail courant)
    loyer_demande: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ─── LOCATAIRE ──────────────────────────────────────────────────────────


class Locataire(Base, TimestampUpdateMixin):
    """Locataire (personne physique ou morale).

    Pas de NAS stocké en clair — uniquement les 4 derniers chiffres
    pour identification rapide. Le NAS complet va dans un coffre-fort
    documents séparé (à venir).
    """

    __tablename__ = "imm_locataires"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True, index=True
    )
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    nas_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)

    date_naissance: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    employeur: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    revenu_annuel: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Score interne 0-100 calculé à partir de l'historique paiements
    # (mis à jour automatiquement quand un paiement est enregistré).
    paiement_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ─── BAIL ───────────────────────────────────────────────────────────────


class Bail(Base, TimestampUpdateMixin):
    """Contrat de bail entre un locataire et un logement.

    Format québécois : 1er juillet au 30 juin par défaut. Renouvellement
    automatique sauf avis 3-6 mois avant (selon durée), géré dans
    BailRenouvellement.
    """

    __tablename__ = "imm_baux"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    logement_id: Mapped[int] = mapped_column(
        ForeignKey("imm_logements.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    locataire_id: Mapped[int] = mapped_column(
        ForeignKey("imm_locataires.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )

    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    loyer_mensuel: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    depot_garantie: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Inclusions (chauffage, eau chaude, électricité, internet…)
    chauffage_inclus: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    eau_chaude_inclus: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    electricite_inclus: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    internet_inclus: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=BailStatus.ACTIF.value,
        server_default=BailStatus.ACTIF.value,
        index=True,
    )

    # PDF du bail signé (URL S3 ou vault). À implémenter dans la phase
    # documents séparée.
    document_url: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Signature électronique du bail (lien tokenisé envoyé au locataire).
    # Colonnes ajoutées de façon additive via init_db (cf. db/session.py).
    signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    sent_to_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_by_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    signature_ip: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    signature_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    signature_image_content_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )


class BailRenouvellement(Base, TimestampUpdateMixin):
    """Cycle de renouvellement annuel d'un bail.

    Au Québec : avis au moins 3 mois avant la fin (loyer fixe) ou 6
    mois (HLM/longue durée). On crée une ligne dès l'envoi d'avis,
    statut = propose. Mise à jour quand le locataire répond.
    """

    __tablename__ = "imm_bail_renouvellements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bail_id: Mapped[int] = mapped_column(
        ForeignKey("imm_baux.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    avis_envoye_le: Mapped[date] = mapped_column(Date, nullable=False)
    nouveau_loyer: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    nouvelle_date_debut: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    nouvelle_date_fin: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False,
        default=BailRenouvellementStatus.PROPOSE.value,
        server_default=BailRenouvellementStatus.PROPOSE.value,
    )
    locataire_repondu_le: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ─── PAIEMENT DE LOYER ──────────────────────────────────────────────────


class PaiementLoyer(Base):
    """Paiement de loyer enregistré.

    Permet le rent-roll et le calcul du score de paiement du locataire.
    Distinct des Payment du module facturation construction.
    """

    __tablename__ = "imm_paiements_loyer"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bail_id: Mapped[int] = mapped_column(
        ForeignKey("imm_baux.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    mois_couvert: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # = 1er du mois facturé. Format YYYY-MM-01.

    montant: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    paye_le: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    methode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Marqueur si paiement en retard (>5 jours après le 1er)
    en_retard: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# ─── HYPOTHÈQUE ─────────────────────────────────────────────────────────


class Hypotheque(Base, TimestampUpdateMixin):
    """Prêt hypothécaire sur un immeuble.

    Plusieurs hypothèques possibles par immeuble (1ère, 2e, marge
    hypothécaire). Une alerte cron se déclenche 6 mois avant l'échéance
    pour préparer le refinancement.
    """

    __tablename__ = "imm_hypotheques"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    rang: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )  # 1 = première, 2 = deuxième…
    preteur: Mapped[str] = mapped_column(String(255), nullable=False)
    montant_initial: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False
    )
    balance_actuelle: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    taux_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 4), nullable=True
    )  # ex. 5.4500
    type_taux: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # 'fixe' | 'variable'
    amortissement_mois: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # ex. 300 = 25 ans

    paiement_mensuel: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Composition des intérêts choisie dans le calculateur de paiement :
    # 'semi' (semi-annuelle, standard hypothèques résidentielles CA) ou
    # 'mensuelle' (prêts commerciaux / variables). Persistée pour que la
    # préférence ne revienne pas au défaut après sauvegarde.
    # Colonne additive (cf. db/session.py).
    composition_interets: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )

    date_debut: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_fin_terme: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
    )  # date de renouvellement du terme

    status: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=HypothequeStatus.ACTIVE.value,
        server_default=HypothequeStatus.ACTIVE.value,
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ─── ÉVALUATION ─────────────────────────────────────────────────────────


class Evaluation(Base):
    """Snapshot de valeur d'un immeuble à une date donnée.

    Plusieurs lignes possibles (municipale annuelle, marchande estimée,
    appraisal pro). Garde l'historique pour les graphiques de
    valorisation et le calcul d'appréciation.
    """

    __tablename__ = "imm_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    kind: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=EvaluationKind.MARCHANDE.value,
    )
    valeur: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    date_evaluation: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )

    source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Évaluation de référence pour le calcul d'équité (valeur actuelle).
    # Une seule par immeuble : passer à True remet les autres à False
    # (cf. endpoint PATCH /evaluations/{id}).
    # Colonne additive (cf. db/session.py).
    is_reference: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# ─── MAINTENANCE ────────────────────────────────────────────────────────


class MaintenanceOrdre(Base, TimestampUpdateMixin):
    """Ordre de travail d'entretien sur un immeuble ou logement.

    Lié soit à l'immeuble (entretien commun, ex. déneigement) soit à un
    logement spécifique (ex. réparation lavabo).
    """

    __tablename__ = "imm_maintenance_ordres"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    logement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_logements.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    priorite: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=MaintenancePriorite.NORMALE.value,
        server_default=MaintenancePriorite.NORMALE.value,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=MaintenanceStatus.OUVERT.value,
        server_default=MaintenanceStatus.OUVERT.value,
        index=True,
    )

    fournisseur: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cout_estime: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    cout_reel: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    plannifie_pour: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    complete_le: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DepenseImmeuble(Base, TimestampUpdateMixin):
    """Dépense d'exploitation d'un immeuble (taxes, assurances,
    entretien, déneigement, énergie…).

    ``frequence`` pilote l'annualisation dans le P&L :
      - "ponctuel" : compté dans l'année de ``date_depense`` ;
      - "mensuel"  : montant × 12 (coût courant) ;
      - "annuel"   : montant × 1 (coût courant).
    """

    __tablename__ = "immeuble_depenses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    immeuble_id: Mapped[int] = mapped_column(
        # La table des immeubles s'appelle `imm_immeubles` (cf. Immeuble
        # plus haut). Un `immeubles.id` erroné faisait échouer TOUT
        # `Base.metadata.create_all()` (NoReferencedTableError) → init_db
        # plantait en silence à chaque boot. Voir docs/PROPOSITIONS.md P-02.
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # taxes_municipales / taxes_scolaires / assurances / energie /
    # entretien / deneigement / conciergerie / gestion / autre
    categorie: Mapped[str] = mapped_column(
        String(48), nullable=False, default="autre"
    )
    libelle: Mapped[str] = mapped_column(String(255), nullable=False)
    montant: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    frequence: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ponctuel",
        server_default="ponctuel",
    )
    date_depense: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_email: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True
    )

    # Le montant est un % des loyers mensuels plutôt qu'un montant fixe
    # (ex. frais de gestion à 5 % des loyers). Colonne additive
    # (cf. db/session.py).
    is_pourcentage: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Dépense taxable : appliquer TPS+TVQ Québec (×1.14975) dans les
    # calculs (cashflow, NOI). Colonne additive (cf. db/session.py).
    taxable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class RelanceLoyer(Base, TimestampUpdateMixin):
    """Relance d'un loyer en retard envoyée à un locataire (courriel).

    ``niveau`` = ordre de la relance pour ce bail + ce mois (1, 2, …).
    Sert de journal/preuve avant un recours (mise en demeure TAL).
    """

    __tablename__ = "imm_relances_loyer"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bail_id: Mapped[int] = mapped_column(
        ForeignKey("imm_baux.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mois_couvert: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )
    niveau: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    canal: Mapped[str] = mapped_column(
        String(16), nullable=False, default="courriel",
        server_default="courriel",
    )
    destinataire: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sent_by_email: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True
    )
