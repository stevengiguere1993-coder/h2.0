"""Registre des courtiers immobiliers (Prospection — Phil 2026-10-14).

But : savoir QUI vend les gros parcs de logements (20 logements et plus)
et se faire remarquer d'eux : un courriel de présentation personnalisé
(qui on est, ce qu'on achète, rétribution additionnelle), puis un suivi.

Trois tables :
  - prospection_courtiers          : la fiche du courtier (coordonnées,
                                     statut de la relation, relances) ;
  - prospection_courtier_annonces  : les annonces 20+ vues chez lui
                                     (Centris via extension / VPS, ou
                                     fiche d'analyse Kratos) ;
  - prospection_courtier_contacts  : le journal des contacts (courriel
                                     envoyé, appel, réponse…).

Nouvelles tables → create_all au démarrage (aucune colonne ajoutée à une
table existante).
"""

from __future__ import annotations

from datetime import date, datetime
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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


#: Statut de la relation avec le courtier.
COURTIER_STATUTS = (
    "a_contacter",  # dans le registre, jamais contacté
    "contacte",     # courriel de présentation envoyé (ou appel fait)
    "repondu",      # il a répondu
    "partenaire",   # relation établie : il nous envoie des dossiers
    "ignorer",      # ne pas contacter
)

COURTIER_SOURCES = ("centris", "extension", "analyse", "manuel")


class ProspectionCourtier(Base, TimestampUpdateMixin):
    __tablename__ = "prospection_courtiers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nom: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agence: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    courriel: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    telephone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cellulaire: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    site_web: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    #: Secteur / ville où il vend surtout (texte libre).
    secteur: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    langue: Mapped[str] = mapped_column(
        String(8), nullable=False, default="fr", server_default="fr"
    )
    #: D'où vient la fiche : centris | extension | analyse | manuel.
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manuel", server_default="manuel"
    )
    statut: Mapped[str] = mapped_column(
        String(32), nullable=False, default="a_contacter",
        server_default="a_contacter", index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Clé de dédoublonnage = nom normalisé (sans accents, minuscules,
    #: espaces simples). Un même courtier vu par l'extension, le VPS et
    #: une fiche d'analyse = UNE ligne.
    cle_dedup: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    premier_vu_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dernier_vu_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dernier_contact_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    prochaine_relance_le: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    nb_relances: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Recherche automatique du courriel (2026-10-14) : où on l'a lu,
    #: verifie | probable, quand on a cherché, ce qu'on a écarté.
    #: ⚠️ Colonnes ajoutées après la création de la table →
    #: ensure_critical_columns (session.py).
    courriel_source: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    courriel_confiance: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    courriel_cherche_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    courriel_recherche_note: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )


class ProspectionCourtierAnnonce(Base):
    __tablename__ = "prospection_courtier_annonces"
    __table_args__ = (
        UniqueConstraint(
            "courtier_id", "source_url", name="uq_courtier_annonce_url"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    courtier_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_courtiers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    centris_listing_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("centris_listings.id", ondelete="SET NULL"), nullable=True
    )
    lead_analysis_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("lead_analyses.id", ondelete="SET NULL"), nullable=True
    )
    mls_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    #: URL Centris, ou « analyse:{id} » pour une fiche sans annonce.
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    adresse: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ville: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    nb_units: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prix: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    vue_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProspectionCourtierContact(Base):
    __tablename__ = "prospection_courtier_contacts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    courtier_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_courtiers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    annonce_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("prospection_courtier_annonces.id", ondelete="SET NULL"),
        nullable=True,
    )
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: courriel | telephone | rencontre | autre
    canal: Mapped[str] = mapped_column(
        String(16), nullable=False, default="courriel", server_default="courriel"
    )
    #: sortant (nous → lui) | entrant (lui → nous)
    direction: Mapped[str] = mapped_column(
        String(8), nullable=False, default="sortant", server_default="sortant"
    )
    sujet: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contenu: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auteur_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
