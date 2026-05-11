"""Analyse de leads immobiliers — capture + extraction + analyse financière.

Workflow :
  1. L'utilisateur colle/upload des sources (URL Centris, texte SMS,
     photos, PDFs, captures d'écran).
  2. Le service `lead_extraction` envoie tout à Claude (vision +
     texte) qui retourne un JSON structuré.
  3. Une `LeadAnalysis` est créée avec statut "a_analyser".
  4. L'utilisateur complète les champs manuels d'analyse (loyers
     projetés, travaux, taux refi…) — Phase 2.
  5. Bouton « Lancer l'analyse » → moteur Excel répliqué → résultats
     + lead passe en "decision_en_attente" — Phase 3.
  6. L'utilisateur classe en "interessant" ou "abandonne".
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class LeadAnalysisStatus(str, Enum):
    """4 colonnes du kanban Analyses."""

    A_ANALYSER = "a_analyser"
    DECISION_EN_ATTENTE = "decision_en_attente"
    INTERESSANT = "interessant"
    ABANDONNE = "abandonne"


class LeadAnalysis(Base, TimestampUpdateMixin):
    """Une fiche d'analyse d'immeuble créée à partir de sources
    diverses (URL, texte, fichiers). Tout le contenu extrait est
    stocké en colonnes typées + un `extracted_json` brut pour
    conserver la sortie complète de Claude (utile pour réutiliser
    si on raffine plus tard l'extraction)."""

    __tablename__ = "lead_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Statut kanban (4 valeurs ci-dessus).
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=LeadAnalysisStatus.A_ANALYSER.value,
        server_default=LeadAnalysisStatus.A_ANALYSER.value,
        index=True,
    )

    # Position manuelle dans la colonne kanban (drag & drop).
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # ── Champs critiques extraits ─────────────────────────────────

    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    province: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True, default="QC", server_default="QC"
    )

    # Prix demandé (CAD).
    asking_price: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    # Nombre total de logements (somme typologie si fournie).
    nb_logements: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # Répartition par typologie en JSON :
    # { "1.5": 2, "3.5": 4, "4.5": 2, "5.5": 0 } etc.
    typology_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Revenus bruts annuels.
    revenus_bruts: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    # Dépenses détaillées.
    taxes_municipales: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    taxes_scolaires: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    assurances: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    energie: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    depenses_autres: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    annee_construction: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # ── Champs additionnels ───────────────────────────────────────

    superficie_terrain: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    superficie_batiment: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    evaluation_municipale: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    courtier_nom: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    courtier_contact: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    type_batiment: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    nb_stationnements: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # ── Sources originales conservées ─────────────────────────────

    # URLs collées par l'utilisateur (séparées par newline).
    source_urls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Texte brut original (email, SMS, copier-coller).
    source_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # JSON brut retourné par Claude (extraction complète, utile
    # pour audit ou ré-extraction).
    extracted_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # ── Champs manuels d'analyse (Phase 2 — réservés pour l'instant) ──

    # Loyers projetés par typologie : { "3.5": 1200, "4.5": 1400 }
    loyers_projetes_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    # Loyer max abordabilité par typologie (si pertinent).
    loyers_max_abordabilite_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    travaux_estimes: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    nb_logements_ajoutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    nb_thermopompes_ajoutees: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    ajout_wifi: Mapped[Optional[bool]] = mapped_column(
        nullable=True
    )
    reduction_energie_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    taux_interet_refi_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 3), nullable=True
    )
    # B13 (Taux global d'actualisation) — défaut 4 %, modifiable.
    tga_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 3), nullable=True, default=4.0, server_default="4.0"
    )
    # B14 (Taux d'intérêt prêt à l'achat) — défaut 4 %, modifiable.
    taux_interet_achat_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 3), nullable=True, default=4.0, server_default="4.0"
    )
    duree_projet_annees: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    frais_developpement: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    frais_negociations: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    # Résultat de l'analyse financière (Phase 3) — JSON avec tous
    # les scénarios. Le scénario « best refi » est cumulé pour
    # affichage rapide sur la carte kanban.
    analysis_results_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    best_refi_amount: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    # Nom du programme qui a donné la meilleure équité (« SCHL
    # standard », « SCHL Efficacité énergétique (50 pts) »,
    # « SCHL Abordabilité + Efficacité (100 pts) »).
    best_refi_program: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )

    # Notes internes (champ libre admin).
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Conversion vers Pipeline ──────────────────────────────────

    # Si l'utilisateur a converti ce lead en ProspectionLead (le
    # pipeline officiel), on stocke l'id pour pouvoir naviguer
    # entre les deux et éviter les doublons.
    converted_to_lead_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("prospection_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class LeadAnalysisAttachment(Base):
    """Fichier original attaché à une analyse (photo, PDF, capture
    d'écran). Stocké en BYTEA — limite ~10 MB par fichier (validation
    côté endpoint), 4-5 fichiers max par lead en pratique. Si on
    explose en taille on basculera sur du S3 plus tard."""

    __tablename__ = "lead_analysis_attachments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    lead_analysis_id: Mapped[int] = mapped_column(
        ForeignKey("lead_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
