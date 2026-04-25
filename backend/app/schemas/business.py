"""Pydantic schemas for business entities (soumissions, agenda, bons, punches, factures, achats, employes, fournisseurs)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Employe ----------
class EmployeCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    role: Optional[str] = Field(default=None, max_length=64)
    hourly_rate: Optional[float] = Field(default=None, ge=0)
    is_partner: bool = False
    notes: Optional[str] = None
    address: Optional[str] = Field(default=None, max_length=500)
    license_number: Optional[str] = Field(default=None, max_length=64)
    emergency_contact_name: Optional[str] = Field(default=None, max_length=255)
    emergency_contact_phone: Optional[str] = Field(default=None, max_length=50)
    is_ccq: bool = False
    cnesst_rate: Optional[float] = Field(default=None, ge=0, le=1)
    ccq_rate: Optional[float] = Field(default=None, ge=0, le=1)
    employeur_d_url: Optional[str] = Field(default=None, max_length=500)


class EmployeUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    hourly_rate: Optional[float] = None
    is_partner: Optional[bool] = None
    active: Optional[bool] = None
    notes: Optional[str] = None
    address: Optional[str] = None
    license_number: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    is_ccq: Optional[bool] = None
    cnesst_rate: Optional[float] = Field(default=None, ge=0, le=1)
    ccq_rate: Optional[float] = Field(default=None, ge=0, le=1)
    employeur_d_url: Optional[str] = None


class EmployeRead(_Base):
    id: int
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    role: Optional[str]
    hourly_rate: Optional[float]
    is_partner: bool
    active: bool
    notes: Optional[str]
    address: Optional[str] = None
    license_number: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    is_ccq: bool = False
    cnesst_rate: Optional[float] = None
    ccq_rate: Optional[float] = None
    employeur_d_url: Optional[str] = None
    created_at: datetime


# ---------- Fournisseur ----------
class FournisseurCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    contact_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    category: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None


class FournisseurUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    category: Optional[str] = None
    website: Optional[str] = None
    active: Optional[bool] = None
    notes: Optional[str] = None


class FournisseurRead(_Base):
    id: int
    name: str
    contact_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    category: Optional[str]
    website: Optional[str]
    active: bool
    notes: Optional[str]
    created_at: datetime


# ---------- Soumission ----------
class SoumissionCreate(BaseModel):
    # Optionnel : si non fourni, l'endpoint utilise next_soumission_number
    # pour générer une référence séquentielle alignée avec QuickBooks.
    reference: Optional[str] = Field(default=None, max_length=32)
    contact_request_id: Optional[int] = None
    client_id: Optional[int] = None
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    subtotal: Optional[float] = None
    tps: Optional[float] = None
    tvq: Optional[float] = None
    total: Optional[float] = None
    valid_until: Optional[datetime] = None
    notes: Optional[str] = None
    client_note: Optional[str] = None
    property_address: Optional[str] = None


class SoumissionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    subtotal: Optional[float] = None
    tps: Optional[float] = None
    tvq: Optional[float] = None
    total: Optional[float] = None
    status: Optional[str] = None
    sent_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    pdf_url: Optional[str] = None
    notes: Optional[str] = None
    client_note: Optional[str] = None
    property_address: Optional[str] = None


class SoumissionRead(_Base):
    id: int
    reference: str
    contact_request_id: Optional[int]
    client_id: Optional[int]
    title: str
    description: Optional[str]
    subtotal: Optional[float]
    tps: Optional[float]
    tvq: Optional[float]
    total: Optional[float]
    status: str
    sent_at: Optional[datetime]
    accepted_at: Optional[datetime]
    valid_until: Optional[datetime]
    pdf_url: Optional[str]
    notes: Optional[str]
    client_note: Optional[str] = None
    property_address: Optional[str]
    created_at: datetime


# ---------- Agenda ----------
class AgendaEventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = None
    start_at: datetime
    end_at: Optional[datetime] = None
    all_day: bool = False
    project_id: Optional[int] = None
    assignee_id: Optional[int] = None
    contact_request_id: Optional[int] = None
    event_type: str = "chantier"


class AgendaEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    project_id: Optional[int] = None
    assignee_id: Optional[int] = None
    contact_request_id: Optional[int] = None
    event_type: Optional[str] = None


class AgendaEventRead(_Base):
    id: int
    title: str
    description: Optional[str]
    location: Optional[str]
    start_at: datetime
    end_at: Optional[datetime]
    all_day: bool
    project_id: Optional[int]
    assignee_id: Optional[int]
    contact_request_id: Optional[int] = None
    event_type: str
    created_at: datetime


# ---------- BonTravail ----------
class BonTravailCreate(BaseModel):
    reference: str = Field(..., max_length=32)
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    scope_md: Optional[str] = None
    project_id: Optional[int] = None
    client_id: Optional[int] = None
    amount: Optional[float] = None


class BonTravailUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scope_md: Optional[str] = None
    amount: Optional[float] = None
    status: Optional[str] = None
    sent_to_email: Optional[EmailStr] = None
    sent_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    signed_by_name: Optional[str] = None


class BonTravailRead(_Base):
    id: int
    reference: str
    title: str
    description: Optional[str]
    scope_md: Optional[str]
    project_id: Optional[int]
    client_id: Optional[int]
    amount: Optional[float]
    status: str
    sent_to_email: Optional[str]
    sent_at: Optional[datetime]
    signed_at: Optional[datetime]
    signed_by_name: Optional[str]
    created_at: datetime


# ---------- Punch ----------
class PunchCreate(BaseModel):
    employe_id: int
    project_id: Optional[int] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    hours: Optional[float] = None
    task: Optional[str] = None
    geolocation: Optional[str] = None
    notes: Optional[str] = None


class PunchUpdate(BaseModel):
    ended_at: Optional[datetime] = None
    hours: Optional[float] = None
    task: Optional[str] = None
    geolocation: Optional[str] = None
    approved: Optional[bool] = None
    notes: Optional[str] = None


class PunchRead(_Base):
    id: int
    employe_id: int
    project_id: Optional[int]
    started_at: datetime
    ended_at: Optional[datetime]
    hours: Optional[float]
    task: Optional[str]
    geolocation: Optional[str]
    approved: bool
    notes: Optional[str]
    created_at: datetime


# ---------- Facture ----------
class FactureCreate(BaseModel):
    reference: str = Field(..., max_length=32)
    client_id: Optional[int] = None
    project_id: Optional[int] = None
    subtotal: Optional[float] = None
    tps: Optional[float] = None
    tvq: Optional[float] = None
    total: Optional[float] = None
    balance: Optional[float] = None
    issued_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    internal_notes: Optional[str] = None
    client_note: Optional[str] = None


class FactureUpdate(BaseModel):
    subtotal: Optional[float] = None
    tps: Optional[float] = None
    tvq: Optional[float] = None
    total: Optional[float] = None
    balance: Optional[float] = None
    status: Optional[str] = None
    issued_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    qbo_invoice_id: Optional[str] = None
    qbo_doc_number: Optional[str] = None
    qbo_sync_token: Optional[str] = None
    internal_notes: Optional[str] = None
    client_note: Optional[str] = None


class FactureRead(_Base):
    id: int
    reference: str
    client_id: Optional[int]
    project_id: Optional[int]
    subtotal: Optional[float]
    tps: Optional[float]
    tvq: Optional[float]
    total: Optional[float]
    balance: Optional[float]
    status: str
    issued_at: Optional[datetime]
    due_at: Optional[datetime]
    paid_at: Optional[datetime]
    qbo_invoice_id: Optional[str]
    qbo_doc_number: Optional[str]
    internal_notes: Optional[str] = None
    client_note: Optional[str] = None
    created_at: datetime


# ---------- Achat ----------
class AchatCreate(BaseModel):
    # Optionnel : si non fourni, l'endpoint utilise next_po_number
    # pour attribuer un PO-XXXX séquentiel.
    reference: Optional[str] = Field(default=None, max_length=32)
    fournisseur_id: Optional[int] = None
    project_id: Optional[int] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    assigned_employe_id: Optional[int] = None
    payment_method: Optional[str] = Field(default=None, max_length=32)
    status: Optional[str] = Field(default=None, max_length=32)


class AchatUpdate(BaseModel):
    description: Optional[str] = None
    amount: Optional[float] = None
    status: Optional[str] = None
    ordered_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = None
    fournisseur_id: Optional[int] = None
    project_id: Optional[int] = None
    assigned_employe_id: Optional[int] = None
    payment_method: Optional[str] = Field(default=None, max_length=32)


class AchatRead(_Base):
    id: int
    reference: str
    fournisseur_id: Optional[int]
    project_id: Optional[int]
    description: Optional[str]
    amount: Optional[float]
    status: str
    ordered_at: Optional[datetime]
    received_at: Optional[datetime]
    receipt_url: Optional[str]
    # True when a scanned receipt image is attached (served via
    # GET /api/v1/achats/{id}/receipt).
    has_receipt_image: bool = False
    receipt_image_content_type: Optional[str] = None
    # Workflow PO
    assigned_employe_id: Optional[int] = None
    payment_method: Optional[str] = None
    # Liaison QuickBooks Online (Bill ou Purchase).
    qbo_bill_id: Optional[str] = None
    qbo_doc_number: Optional[str] = None
    notes: Optional[str]
    created_at: datetime
