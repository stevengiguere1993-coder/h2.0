"""Pydantic schemas — pôle Développement logiciel (clients & leads)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------
# DevlogClient
# --------------------------------------------------------------------------


class DevlogClientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=500)
    website: Optional[str] = Field(default=None, max_length=255)
    status: str = Field(default="active", max_length=16)
    notes: Optional[str] = None


class DevlogClientUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class DevlogClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    company: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    website: Optional[str]
    status: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# DevlogLead
# --------------------------------------------------------------------------


class DevlogLeadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=50)
    source: str = Field(default="interne", max_length=16)
    status: str = Field(default="nouveau", max_length=20)
    assigned_to_user_id: Optional[int] = None
    project_summary: Optional[str] = None
    budget_range: Optional[str] = Field(default=None, max_length=64)
    notes: Optional[str] = None


class DevlogLeadUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    position: Optional[int] = None
    assigned_to_user_id: Optional[int] = None
    project_summary: Optional[str] = None
    budget_range: Optional[str] = None
    notes: Optional[str] = None


class DevlogLeadStatusUpdate(BaseModel):
    """Déplacement d'un lead dans le kanban du closer."""

    status: str = Field(..., max_length=20)
    position: Optional[int] = None


class DevlogLeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    company: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    source: str
    status: str
    position: int
    assigned_to_user_id: Optional[int]
    project_summary: Optional[str]
    budget_range: Optional[str]
    notes: Optional[str]
    client_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# DevlogSoumission
# --------------------------------------------------------------------------


class DevlogSoumissionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    lead_id: Optional[int] = None
    client_id: Optional[int] = None
    amount: Optional[float] = Field(default=None, ge=0)
    status: str = Field(default="brouillon", max_length=16)
    summary: Optional[str] = None
    notes: Optional[str] = None


class DevlogSoumissionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    lead_id: Optional[int] = None
    client_id: Optional[int] = None
    amount: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None
    summary: Optional[str] = None
    notes: Optional[str] = None


class DevlogSoumissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    lead_id: Optional[int]
    client_id: Optional[int]
    amount: Optional[float]
    status: str
    summary: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# DevlogProject
# --------------------------------------------------------------------------


class DevlogProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    client_id: Optional[int] = None
    soumission_id: Optional[int] = None
    description: Optional[str] = None
    status: str = Field(default="a_demarrer", max_length=16)
    start_date: Optional[date] = None
    due_date: Optional[date] = None


class DevlogProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    client_id: Optional[int] = None
    soumission_id: Optional[int] = None
    description: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    due_date: Optional[date] = None


class DevlogProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    client_id: Optional[int]
    soumission_id: Optional[int]
    description: Optional[str]
    status: str
    start_date: Optional[date]
    due_date: Optional[date]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# DevlogTimeEntry
# --------------------------------------------------------------------------


class DevlogTimeEntryCreate(BaseModel):
    project_id: Optional[int] = None
    user_id: Optional[int] = None
    work_date: date
    hours: float = Field(..., ge=0)
    description: Optional[str] = None


class DevlogTimeEntryUpdate(BaseModel):
    project_id: Optional[int] = None
    user_id: Optional[int] = None
    work_date: Optional[date] = None
    hours: Optional[float] = Field(default=None, ge=0)
    description: Optional[str] = None


class DevlogTimeEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: Optional[int]
    user_id: Optional[int]
    work_date: date
    hours: float
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
