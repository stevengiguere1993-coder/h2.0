"""Annonce de location scrapée — base de comparables loyers + source
de téléphones propriétaires.

Sources scrapées :
- Kijiji (catégorie « Apartments for rent »)
- LesPAC (catégorie « Logements à louer »)
- Plus tard : Centris (multi-logements, scrape Playwright)

⚠ On ne stocke que les MÉTRIQUES (prix, chambres, adresse, lat/lng)
+ le téléphone extrait via regex. Pas de titre, pas de description,
pas de photos — pour limiter le stockage et éviter les questions
de copyright / ToS.

Usage :
1. Comparables loyers : médiane par adresse + filtres (chambres,
   année…) — alimente le calculateur d'analyse à la place de Zilpex.
2. Téléphones proprio : matching par adresse civique → table
   prospection_lead.owner_phone si non encore set.
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


class RentalListing(Base):
    __tablename__ = "rental_listings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Source URL canonique (déduplication clé). Ex:
    # https://www.kijiji.ca/v-apartments/.../12345
    source_url: Mapped[str] = mapped_column(
        String(500), unique=True, index=True, nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # "kijiji" | "lespac" | "centris" | …

    # Adresse extraite + géocodée
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
    postal_code: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    lat: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, index=True
    )
    lng: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, index=True
    )

    # Caractéristiques
    price: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True, index=True
    )
    bedrooms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )  # 0 = studio, 1, 2, 3, 4+
    bathrooms: Mapped[Optional[float]] = mapped_column(
        Numeric(3, 1), nullable=True
    )
    sqft: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # Inclusions (JSON-encoded array de strings)
    # ex: ["chauffage", "electricite", "internet", "stationnement"]
    inclusions_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Contact extrait du texte de l'annonce
    phone: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )
    contact_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Métadonnées de scraping
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    # Quand l'annonce n'est plus visible (le scraper next-day ne la
    # trouve plus). Utile pour exclure des comparables stale.
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_rental_addr",
            "civique",
            "nom_rue",
            "city",
        ),
    )
