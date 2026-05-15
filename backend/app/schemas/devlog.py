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
# DevlogSoumissionItem (lignes de soumission)
# --------------------------------------------------------------------------


class DevlogSoumissionItemCreate(BaseModel):
    soumission_id: int
    position: Optional[int] = None
    description: str = Field(..., min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: float = Field(default=1, ge=0)
    unit_price: float = Field(default=0, ge=0)
    notes: Optional[str] = None


class DevlogSoumissionItemUpdate(BaseModel):
    position: Optional[int] = None
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[float] = Field(default=None, ge=0)
    unit_price: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None


class DevlogSoumissionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    soumission_id: int
    position: int
    description: str
    unit: Optional[str]
    quantity: float
    unit_price: float
    total: float
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# DevlogSousTraitant
# --------------------------------------------------------------------------


class DevlogSousTraitantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=50)
    specialty: Optional[str] = Field(default=None, max_length=255)
    hourly_rate: Optional[float] = Field(default=None, ge=0)
    active: bool = True
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None


class DevlogSousTraitantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    specialty: Optional[str] = None
    hourly_rate: Optional[float] = Field(default=None, ge=0)
    active: Optional[bool] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None


class DevlogSousTraitantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    company: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    specialty: Optional[str]
    hourly_rate: Optional[float]
    active: bool
    rating: Optional[int]
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


# --------------------------------------------------------------------------
# DevlogInvoice
# --------------------------------------------------------------------------


class DevlogInvoiceCreate(BaseModel):
    number: Optional[str] = Field(default=None, max_length=64)
    client_id: Optional[int] = None
    project_id: Optional[int] = None
    amount: Optional[float] = Field(default=None, ge=0)
    status: str = Field(default="brouillon", max_length=16)
    issued_date: Optional[date] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None


class DevlogInvoiceUpdate(BaseModel):
    number: Optional[str] = None
    client_id: Optional[int] = None
    project_id: Optional[int] = None
    amount: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None
    issued_date: Optional[date] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None


class DevlogInvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: Optional[str]
    client_id: Optional[int]
    project_id: Optional[int]
    amount: Optional[float]
    status: str
    issued_date: Optional[date]
    due_date: Optional[date]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# DevlogInvoiceItem
# --------------------------------------------------------------------------


class DevlogInvoiceItemCreate(BaseModel):
    invoice_id: int
    position: Optional[int] = None
    description: str = Field(..., min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: float = Field(default=1, ge=0)
    unit_price: float = Field(default=0, ge=0)
    source_kind: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None


class DevlogInvoiceItemUpdate(BaseModel):
    position: Optional[int] = None
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[float] = Field(default=None, ge=0)
    unit_price: Optional[float] = Field(default=None, ge=0)
    source_kind: Optional[str] = None
    notes: Optional[str] = None


class DevlogInvoiceItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    position: int
    description: str
    unit: Optional[str]
    quantity: float
    unit_price: float
    total: float
    source_kind: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class DevlogInvoiceImportRequest(BaseModel):
    """Import depuis un projet : heures (regroupées par employé × taux
    facturable) et/ou items de la soumission acceptée."""

    project_id: int
    include_hours: bool = True
    hourly_rate: Optional[float] = Field(
        default=None, ge=0,
        description="Taux facturable global (CAD/h). Si null, on prend "
        "$0 — l'admin éditera la ligne après.",
    )
    include_soumission: bool = False
    soumission_id: Optional[int] = None


class DevlogInvoiceImportResult(BaseModel):
    added: int


# --------------------------------------------------------------------------
# DevlogContract
# --------------------------------------------------------------------------


class DevlogContractCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body: Optional[str] = None
    status: str = Field(default="brouillon", max_length=16)
    soumission_id: Optional[int] = None
    client_id: Optional[int] = None
    project_id: Optional[int] = None


class DevlogContractUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    body: Optional[str] = None
    status: Optional[str] = None
    soumission_id: Optional[int] = None
    client_id: Optional[int] = None
    project_id: Optional[int] = None


class DevlogContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: Optional[str]
    status: str
    soumission_id: Optional[int]
    client_id: Optional[int]
    project_id: Optional[int]
    signature_token: Optional[str]
    sent_at: Optional[datetime]
    signed_at: Optional[datetime]
    signed_name: Optional[str]
    signed_ip: Optional[str]
    created_at: datetime
    updated_at: datetime


class DevlogContractPublicRead(BaseModel):
    """Vue publique servie sur la page de signature — pas d'IDs internes
    ni de champs admin."""

    title: str
    body: Optional[str]
    status: str
    signed_at: Optional[datetime]
    signed_name: Optional[str]


class DevlogContractSignRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
