"""Pydantic schemas pour le volet Investisseur."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Investissement ────────────────────────────────────────────────────


class InvestissementBase(BaseModel):
    user_id: int
    immeuble_id: int
    montant_investi: float = Field(..., ge=0)
    parts_pct: float = Field(default=0, ge=0, le=100)
    date_investissement: date
    status: str = Field(default="actif", max_length=16)
    date_sortie: Optional[date] = None
    montant_sortie: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    is_visible_to_investor: bool = True


class InvestissementCreate(InvestissementBase):
    pass


class InvestissementUpdate(BaseModel):
    montant_investi: Optional[float] = Field(default=None, ge=0)
    parts_pct: Optional[float] = Field(default=None, ge=0, le=100)
    date_investissement: Optional[date] = None
    status: Optional[str] = Field(default=None, max_length=16)
    date_sortie: Optional[date] = None
    montant_sortie: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    is_visible_to_investor: Optional[bool] = None


class InvestissementRead(InvestissementBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


# ─── Distribution ──────────────────────────────────────────────────────


class DistributionBase(BaseModel):
    investissement_id: int
    date_distribution: date
    type: str = Field(default="loyer", max_length=32)
    montant: float = Field(..., ge=0)
    notes: Optional[str] = None


class DistributionCreate(DistributionBase):
    pass


class DistributionRead(DistributionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ─── Vue investisseur (consolidée) ─────────────────────────────────────


class InvestissementWithKpis(BaseModel):
    """Investissement enrichi avec les KPIs calculés."""

    id: int
    immeuble_id: int
    immeuble_name: str
    immeuble_address: str
    immeuble_cover_photo_url: Optional[str] = None

    montant_investi: float
    parts_pct: float
    date_investissement: date
    status: str

    # Distributions reçues à ce jour
    total_distributions: float = 0.0
    nb_distributions: int = 0

    # Valeur courante de la part (basée sur évaluation immeuble × parts_pct,
    # nette de la balance hypothécaire allouée à la part)
    valeur_part_courante: Optional[float] = None

    # Ratios
    dpi: Optional[float] = None     # distributions / montant_investi
    tvpi: Optional[float] = None    # (distributions + valeur_part) / montant_investi
    rendement_annuel_estime: Optional[float] = None  # %


class InvestisseurPortefeuille(BaseModel):
    """Vue consolidée du portefeuille d'un investisseur."""

    user_id: int
    nb_investissements: int = 0
    total_capital_investi: float = 0.0
    total_distributions: float = 0.0
    valeur_portefeuille_courante: float = 0.0
    dpi_global: Optional[float] = None
    tvpi_global: Optional[float] = None

    investissements: List[InvestissementWithKpis] = Field(default_factory=list)
