"""Annonce Centris — multi-logements à vendre.

Différent de RentalListing : ce sont des immeubles **à vendre**, pas
des logements à louer. Source : Centris.ca, catégorie « Multiplex
(2-5) » + « Immeuble résidentiel ».

Stratégie identique : on stocke seulement les MÉTRIQUES (prix, # unités,
année, superficie, adresse, lat/lng) + l'URL canonique pour dédup. Pas
de description complète ni photos pour limiter le stockage et éviter
les questions ToS.

Usage :
1. Notifications « nouvelle vente sur ton territoire » au matin
2. Match avec MTL property units (matricule/adresse) → si match, le
   lead correspondant est mis à jour avec le prix demandé
3. Vue « Annonces du jour » dans Prospection pour identifier de
   nouvelles cibles
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CentrisListing(Base):
    __tablename__ = "centris_listings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # MLS Centris (ex: 12345678) — clé canonique
    mls_id: Mapped[Optional[str]] = mapped_column(
        String(16), unique=True, nullable=True, index=True
    )
    source_url: Mapped[str] = mapped_column(
        String(500), unique=True, index=True, nullable=False
    )

    # Catégorie : "multiplex_2_5", "immeuble_residentiel_6_plus"
    category: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )

    # Adresse + géo
    address: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    civique: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, index=True
    )
    nom_rue: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    city: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True, index=True
    )
    quartier: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    postal_code: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    lat: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, index=True
    )
    lng: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, index=True
    )

    # Caractéristiques de l'immeuble
    price: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True, index=True
    )
    nb_units: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )  # 2, 3, 4, 5, 6+
    year_built: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    superficie_terrain: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    superficie_batiment: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # Revenus annuels indicatifs (parfois affichés dans Centris)
    revenus_annuels: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # Courtier (souvent affiché)
    broker_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    broker_phone: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    # Match contre nos données
    matricule: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )

    # Métadonnées de scraping
    listed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Vendu / retiré : on ne le voit plus dans les listes
    delisted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_meta_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    __table_args__ = (
        Index("ix_centris_addr", "civique", "nom_rue", "city"),
    )
