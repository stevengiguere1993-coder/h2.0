"""Pydantic schemas pour le volet Gestion d'entreprises."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Entreprise ─────────────────────────────────────────────────────────


class EntrepriseBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    neq: Optional[str] = Field(default=None, max_length=32)
    type: str = Field(default="gestion", max_length=32)
    color_accent: str = Field(default="#7c3aed", pattern=r"^#[0-9a-fA-F]{6}$")
    description: Optional[str] = None
    is_active: bool = True


class EntrepriseCreate(EntrepriseBase):
    pass


class EntrepriseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    neq: Optional[str] = Field(default=None, max_length=32)
    type: Optional[str] = Field(default=None, max_length=32)
    color_accent: Optional[str] = Field(
        default=None, pattern=r"^#[0-9a-fA-F]{6}$"
    )
    description: Optional[str] = None
    is_active: Optional[bool] = None


class EntrepriseRead(EntrepriseBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    monday_board_id: Optional[str] = None
    monday_board_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ─── Tâche ─────────────────────────────────────────────────────────────


class EntrepriseTacheBase(BaseModel):
    entreprise_id: int
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    departement: Optional[str] = Field(default=None, max_length=32)
    status: str = Field(default="backlog", max_length=16)
    impact: Optional[int] = Field(default=None, ge=1, le=10)
    confidence: Optional[int] = Field(default=None, ge=1, le=10)
    effort: Optional[int] = Field(default=None, ge=1, le=10)
    assignee_user_id: Optional[int] = None
    due_date: Optional[date] = None
    recurrence: Optional[str] = Field(default=None, max_length=16)
    tags_json: Optional[str] = None


class EntrepriseTacheCreate(EntrepriseTacheBase):
    pass


class EntrepriseTacheUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    departement: Optional[str] = Field(default=None, max_length=32)
    status: Optional[str] = Field(default=None, max_length=16)
    impact: Optional[int] = Field(default=None, ge=1, le=10)
    confidence: Optional[int] = Field(default=None, ge=1, le=10)
    effort: Optional[int] = Field(default=None, ge=1, le=10)
    assignee_user_id: Optional[int] = None
    due_date: Optional[date] = None
    recurrence: Optional[str] = Field(default=None, max_length=16)
    tags_json: Optional[str] = None
    completed_at: Optional[datetime] = None


class EntrepriseTacheRead(EntrepriseTacheBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    completed_at: Optional[datetime] = None
    monday_item_id: Optional[str] = None
    monday_board_id: Optional[str] = None
    monday_group_title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Score calculé serveur-side (ICE × multiplicateur d'urgence). Optionnel
    # — None si l'un des champs ICE est absent.
    score: Optional[float] = None


class TacheImportResult(BaseModel):
    """Résultat du POST /entreprises/import-monday-tasks."""

    boards_processed: int
    entreprises_created: int
    entreprises_updated: int
    taches_created: int
    taches_updated: int
    errors: List[str] = Field(default_factory=list)
