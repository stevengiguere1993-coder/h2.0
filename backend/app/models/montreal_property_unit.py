"""Unité d'évaluation foncière de la Ville de Montréal.

Source : données ouvertes de la Ville de Montréal
https://donnees.montreal.ca/dataset/unites-evaluation-fonciere
(CSV mis à jour ~1 fois par an, ~500k lignes, libre de droits).

Sert de cache local pour le module Prospection : à partir d'une adresse
on retrouve instantanément le matricule, le nombre de logements, l'année
de construction et les superficies — sans dépendance réseau et sans
limitation de taux.

⚠ Pas d'info propriétaire dans ce dataset (vie privée). Pour le
propriétaire on passe par les corporations REQ (table req_companies).
"""

from typing import Optional

from sqlalchemy import Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MontrealPropertyUnit(Base):
    __tablename__ = "mtl_property_units"

    # MATRICULE83 — identifiant unique d'une unité d'évaluation à
    # Montréal (chaîne de 18-22 caractères avec tirets).
    matricule: Mapped[str] = mapped_column(String(32), primary_key=True)

    civique_debut: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    civique_fin: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    nom_rue: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    suite_debut: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    municipalite: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True
    )

    nombre_logement: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    annee_construction: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    code_utilisation: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True
    )
    libelle_utilisation: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    categorie_uef: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    superficie_terrain: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    superficie_batiment: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # Clé de recherche normalisée : "<civique>|<rue normalisée>"
    # Permet un index B-tree pour des lookups O(log n) à partir d'une
    # adresse saisie côté frontend.
    search_key: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True, index=True
    )

    __table_args__ = (
        Index("ix_mtl_units_nom_rue", "nom_rue"),
    )
