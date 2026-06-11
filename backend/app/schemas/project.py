"""Pydantic schemas for Project operations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.schemas.client import ClientRead


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    client_id: Optional[int] = Field(default=None, gt=0)
    contact_request_id: Optional[int] = Field(default=None, gt=0)
    soumission_id: Optional[int] = Field(default=None, gt=0)
    responsible_user_id: Optional[int] = Field(default=None, gt=0)
    status: Optional[str] = Field(default=None, max_length=32)
    address: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = None
    notes: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[Decimal] = Field(default=None, ge=0)
    estimated_hours_override: Optional[Decimal] = Field(default=None, ge=0)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    client_id: Optional[int] = Field(default=None, gt=0)
    contact_request_id: Optional[int] = Field(default=None, gt=0)
    soumission_id: Optional[int] = Field(default=None, gt=0)
    # Envoyer null (explicitement) pour retirer le responsable.
    responsible_user_id: Optional[int] = Field(default=None, gt=0)
    status: Optional[str] = Field(default=None, max_length=32)
    address: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[Decimal] = Field(default=None, ge=0)
    estimated_hours_override: Optional[Decimal] = Field(default=None, ge=0)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    client_id: Optional[int]
    contact_request_id: Optional[int]
    soumission_id: Optional[int]
    responsible_user_id: Optional[int] = None
    # Nom du responsable (rempli côté endpoint via la relation) pour
    # l'affichage sans requête supplémentaire côté UI.
    responsible_name: Optional[str] = None
    status: str
    address: Optional[str]
    description: Optional[str]
    notes: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    budget: Optional[Decimal]
    # Total de la soumission liée — utilisé comme fallback côté UI
    # quand budget est null (cas des projets créés sans budget mais
    # rattachés à une soumission acceptée). Null si pas de soumission
    # liée ou si la soumission n'a pas de total.
    soumission_total: Optional[Decimal] = None
    # Type de facturation dérivé de la soumission liée : "forfaitaire",
    # "estime" ou "contrat". Sert de défaut pour la case « refacturable »
    # des achats (forfaitaire = décoché, sinon coché). "forfaitaire" par
    # défaut quand aucune soumission n'est liée.
    billing_kind: str = "forfaitaire"
    estimated_hours_override: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime


class ProjectReadWithClient(ProjectRead):
    client: Optional["ClientRead"] = None


# Convenience schema for listing (lightweight).
class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    address: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    budget: Optional[Decimal]
    client_id: Optional[int]
