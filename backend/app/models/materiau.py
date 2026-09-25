"""Catalogue de MATÉRIAUX et prix par magasin (retour 2026-09-25).

Objectif : magasiner le meilleur prix entre les détaillants (Rona, Home
Depot, Réno-Dépôt, BMR, Canac, Patrick Morin…), suivre les rabais et
leur date de fin, et nourrir les budgets (coûtant matériaux des
soumissions, budgets de phases, listes d'achats).

- ``Magasin``               : un détaillant.
- ``Materiau``              : un article du catalogue (nom, catégorie, unité).
- ``MateriauOffre``         : l'offre COURANTE d'un magasin pour un matériau
                              (une ligne par couple matériau × magasin) :
                              prix, prix régulier, rabais et fin de rabais,
                              lien / n° d'article, dernière vérification,
                              source (import | manuel | auto).
- ``MateriauPrixHistorique``: chaque prix observé, pour la tendance.

Nouvelles tables → create_all au démarrage ; colonnes toutes nullables ou
à défaut. Déclarées dans api_ia_couverture (cliquet « IA au courant »).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Magasin(Base):
    __tablename__ = "magasins"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    #: Site web (racine) — sert aux liens et, plus tard, au relevé
    #: automatique des prix.
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    #: Couleur d'affichage (hex sans #), optionnelle.
    color: Mapped[Optional[str]] = mapped_column(String(6), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Materiau(Base):
    __tablename__ = "materiaux"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    #: Nom normalisé (minuscules, sans accents ni ponctuation) — clé de
    #: dédoublonnage à l'import.
    name_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    #: Catégorie libre : Électricité, Plomberie, Quincaillerie, Gypse…
    categorie: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    #: Unité d'achat : unité, boîte, pi, pi², sac, gal…
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    offres: Mapped[list["MateriauOffre"]] = relationship(
        back_populates="materiau", cascade="all, delete-orphan"
    )


class MateriauOffre(Base):
    """Offre courante d'UN magasin pour UN matériau."""

    __tablename__ = "materiau_offres"
    __table_args__ = (
        UniqueConstraint("materiau_id", "magasin_id", name="uq_materiau_offre"),
        Index("ix_materiau_offres_magasin", "magasin_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    materiau_id: Mapped[int] = mapped_column(
        ForeignKey("materiaux.id", ondelete="CASCADE"), nullable=False, index=True
    )
    magasin_id: Mapped[int] = mapped_column(
        ForeignKey("magasins.id", ondelete="CASCADE"), nullable=False
    )
    #: Prix unitaire COURANT (HT), celui qu'on paierait aujourd'hui.
    unit_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    #: Prix régulier quand le courant est un prix de rabais.
    regular_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    on_sale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: Dernier jour du rabais (inclus), si connu.
    sale_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    #: Lien vers la page produit et/ou n° d'article chez ce magasin.
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    #: import (fichier historique) | manuel | auto (relevé quotidien).
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manuel", server_default="manuel"
    )
    #: Quand ce prix a été observé. NULL = prix d'archive sans date
    #: (import d'un vieux fichier) → à vérifier avant d'acheter.
    observed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    materiau: Mapped["Materiau"] = relationship(back_populates="offres")
    magasin: Mapped["Magasin"] = relationship()


class MateriauPrixHistorique(Base):
    __tablename__ = "materiau_prix_historique"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    materiau_id: Mapped[int] = mapped_column(
        ForeignKey("materiaux.id", ondelete="CASCADE"), nullable=False, index=True
    )
    magasin_id: Mapped[int] = mapped_column(
        ForeignKey("magasins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    regular_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    on_sale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sale_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manuel", server_default="manuel"
    )
    observed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Provenance libre : « Historique projet 77 Gauthier (fichier Olivier) ».
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
