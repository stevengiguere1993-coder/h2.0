"""Loyers moyens du marché par zone géographique.

Source primaire : SCHL/CMHC — Rapport sur le marché locatif (RMR).
CSV public, gratuit, mis à jour annuellement (publication oct/nov).

Granularité disponible : Studio, 1 chambre, 2 chambres, 3+ chambres.
Mapping vers la nomenclature québécoise :
- 1½  = Studio (Bachelor)
- 2½  = 1 chambre
- 3½  = 2 chambres
- 4½  = 3 chambres
- 5½ et 6½ = 3+ chambres (limite SCHL — pas de granularité plus fine
  dans les rapports publics, on note explicitement « estimé sur la
  base 3+ BR » dans l'UI)

Utilisé par le module Prospection pour calculer le revenu locatif
estimé d'un multi-logement et son GRM (Gross Rent Multiplier =
valeur foncière / revenu annuel) — la métrique de qualification clé
pour les décisions d'investissement multi-logements.
"""

from typing import Optional

from sqlalchemy import (
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketRent(Base):
    __tablename__ = "market_rents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Géographie. `cma` = Census Metropolitan Area (« Montréal »,
    # « Longueuil », « Brossard », ...). `zone` = sous-zone de la
    # SCHL (« Plateau Mont-Royal », « Verdun », « Vieux-Longueuil »,
    # ...) — null si stat agrégée à l'échelle de la ville entière.
    cma: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    zone: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True, index=True
    )

    # SCHL bedroom brackets. Stocké comme entier 0..3 :
    #   0 = Studio (1½)
    #   1 = 1 chambre (2½)
    #   2 = 2 chambres (3½)
    #   3 = 3+ chambres (4½, 5½, 6½ → tous mappés ici)
    bedrooms: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )

    avg_rent: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    vacancy_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True  # % (ex: 1.85 = 1.85 %)
    )
    sample_size: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    # Année du rapport (ex: 2025 pour la collecte d'octobre 2025).
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    __table_args__ = (
        # Une seule ligne par (CMA, zone, taille, année).
        UniqueConstraint(
            "cma", "zone", "bedrooms", "year", name="uq_market_rent"
        ),
        Index("ix_market_rents_cma_zone", "cma", "zone"),
    )
