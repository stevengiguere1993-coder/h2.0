"""Pydantic schemas — Contact (rolodex transverse) + vue agrégée."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# CRUD du modèle Contact (rolodex pur)
# --------------------------------------------------------------------------


class ContactCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    company: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=500)
    kind: str = Field(default="professional", max_length=32)
    specialty: Optional[str] = Field(default=None, max_length=255)
    tags_json: Optional[str] = None
    active: bool = True
    notes: Optional[str] = None


class ContactUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    kind: Optional[str] = Field(default=None, max_length=32)
    specialty: Optional[str] = None
    tags_json: Optional[str] = None
    active: Optional[bool] = None
    notes: Optional[str] = None


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    company: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    kind: str
    specialty: Optional[str]
    tags_json: Optional[str]
    active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# Vue agrégée — fédère contacts purs + sous-traitants + fournisseurs +
# employés partenaires + sous-traitants devlog
# --------------------------------------------------------------------------


class UnifiedContact(BaseModel):
    """Représentation unifiée d'un contact, quel que soit son origine.

    `source` indique d'où vient la donnée (le frontend l'utilise pour
    décider si l'édition se fait inline — quand source='contact' — ou
    via la fiche dédiée du module d'origine)."""

    # id composite "source:id" pour clé React unique et lookup direct.
    id: str
    source: str  # contact | sous_traitant | fournisseur | employe_partner | devlog_sous_traitant
    source_id: int
    full_name: str
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    kind: str  # libellé haut-niveau pour le badge UI
    specialty: Optional[str] = None
    active: bool = True
    # URL relative de la fiche dédiée (None pour les contacts purs qui
    # s'éditent inline dans la sidebar de /entreprises/contacts).
    detail_url: Optional[str] = None
    # True quand le contact est dans la table contact_hides et que
    # l'utilisateur a demandé include_hidden=true. Sert à l'UI pour
    # le griser et proposer un bouton « démasquer ».
    hidden: bool = False


class ContactHideRequest(BaseModel):
    """Body de POST /api/v1/contacts/hide — masque un fédéré."""

    source: str = Field(..., min_length=1, max_length=64)
    source_id: int
