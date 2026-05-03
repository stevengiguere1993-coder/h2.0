"""Schemas Pydantic pour les partenaires et liens externes d'une entreprise."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Partenaires ───────────────────────────────────────────────────────


class PartnerBase(BaseModel):
    entreprise_id: int
    user_id: Optional[int] = None
    partner_name: Optional[str] = Field(default=None, max_length=255)
    partner_email: Optional[str] = Field(default=None, max_length=320)
    partner_notes: Optional[str] = None
    role: str = Field(default="associe", max_length=32)
    ownership_pct: Optional[float] = Field(default=None, ge=0, le=100)


class PartnerCreate(PartnerBase):
    pass


class PartnerUpdate(BaseModel):
    user_id: Optional[int] = None
    partner_name: Optional[str] = Field(default=None, max_length=255)
    partner_email: Optional[str] = Field(default=None, max_length=320)
    partner_notes: Optional[str] = None
    role: Optional[str] = Field(default=None, max_length=32)
    ownership_pct: Optional[float] = Field(default=None, ge=0, le=100)


class PartnerRead(PartnerBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # Champs dérivés pour l'UI : `display_name` = partner_name si fourni,
    # sinon User.full_name si user_id, sinon "Partenaire #id".
    display_name: str = ""
    display_email: Optional[str] = None


# ─── Liens externes ────────────────────────────────────────────────────


class LinkBase(BaseModel):
    entreprise_id: int
    label: str = Field(..., min_length=1, max_length=128)
    url: str = Field(..., min_length=1, max_length=2048)
    kind: str = Field(default="autre", max_length=32)
    notes: Optional[str] = None


class LinkCreate(LinkBase):
    pass


class LinkUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=128)
    url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    kind: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None


class LinkRead(LinkBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
