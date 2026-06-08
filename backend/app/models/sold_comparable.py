"""Comparable de vente (transaction immobilière vendue).

Sert au module Prospection : permet à l'utilisateur d'accumuler des
ventes comparables (« comps ») pour un secteur donné afin d'évaluer la
valeur marchande d'un immeuble cible.

Trois sources de données :
- "manual"  : saisie à la main par l'utilisateur (toujours fiable).
- "numeriq" : scrapé depuis le journal des ventes (via le VPS).
- "registre": import du registre foncier (futur).

Chaque comparable est croisé avec `mtl_property_units` via `search_key`
(« <civique>|<rue normalisée> ») pour enrichir automatiquement les
champs du rôle d'évaluation (matricule, nb de logements, année de
construction, superficie du terrain, libellé d'utilisation) sans
re-saisie.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SoldComparable(Base):
    __tablename__ = "sold_comparables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Matricule du rôle d'évaluation (rempli par croisement avec
    # `mtl_property_units` quand l'adresse matche). NULL si non croisé.
    matricule: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )

    civique: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    nom_rue: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    municipalite: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )
    # Région : « mtl-island », « laval », « rive-sud », « rive-nord ».
    region: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, index=True
    )

    address_full: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )

    # Clé de recherche normalisée : « <civique>|<rue normalisée> ».
    # MÊME normalisation que MontrealPropertyUnit.search_key — permet de
    # croiser les deux tables pour enrichir le comparable.
    search_key: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True, index=True
    )

    price: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    date_sold: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
    )

    # Champs enrichis via le croisement avec `mtl_property_units`.
    nb_logement: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    annee_construction: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    superficie_terrain: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    libelle_utilisation: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Provenance : "manual" | "numeriq" | "registre".
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual"
    )
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Payload brut de la source (JSON-encodé) pour traçabilité / debug.
    raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
