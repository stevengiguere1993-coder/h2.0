"""Pydantic schemas for business entities (soumissions, agenda, bons, punches, factures, achats, employes, fournisseurs)."""

from __future__ import annotations

from datetime import date, datetime
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
    billing_rate: Optional[float] = Field(default=None, ge=0)
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
    billing_rate: Optional[float] = Field(default=None, ge=0)
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
    billing_rate: Optional[float] = None
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
    address: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = None
    payment_terms_days: Optional[int] = Field(default=None, ge=0, le=365)
    qbo_expense_account: Optional[str] = Field(default=None, max_length=255)
    # Inscrit à la TPS/TVQ (défaut Oui). Non → achats sans taxe récupérable.
    tax_registered: bool = True


class FournisseurUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    category: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = Field(default=None, max_length=500)
    active: Optional[bool] = None
    notes: Optional[str] = None
    payment_terms_days: Optional[int] = Field(default=None, ge=0, le=365)
    qbo_expense_account: Optional[str] = Field(default=None, max_length=255)
    tax_registered: Optional[bool] = None


class FournisseurRead(_Base):
    id: int
    name: str
    contact_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    category: Optional[str]
    website: Optional[str]
    address: Optional[str] = None
    active: bool
    notes: Optional[str]
    payment_terms_days: Optional[int] = None
    qbo_expense_account: Optional[str] = None
    qbo_vendor_id: Optional[str] = None
    tax_registered: bool = True
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
    pricing_kind: str = Field(
        default="forfaitaire", pattern="^(forfaitaire|estime)$"
    )
    # "quote" = devis classique (lignes de prix) ; "contract" = contrat
    # d'entreprise APCHQ (champs structurés dans contract_data, JSON).
    kind: str = Field(default="quote", pattern="^(quote|contract)$")
    contract_data: Optional[str] = None


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
    pricing_kind: Optional[str] = Field(
        default=None, pattern="^(forfaitaire|estime)$"
    )
    kind: Optional[str] = Field(
        default=None, pattern="^(quote|contract)$"
    )
    contract_data: Optional[str] = None


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
    archived_at: Optional[datetime] = None
    pdf_url: Optional[str]
    notes: Optional[str]
    client_note: Optional[str] = None
    property_address: Optional[str]
    pricing_kind: str = "forfaitaire"
    kind: str = "quote"
    contract_data: Optional[str] = None
    contractor_signed_name: Optional[str] = None
    contractor_signed_at: Optional[datetime] = None
    contractor_signature_token: Optional[str] = None
    signed_name: Optional[str] = None
    client_opened_at: Optional[datetime] = None
    client_last_opened_at: Optional[datetime] = None
    client_open_count: int = 0
    contractor_opened_at: Optional[datetime] = None
    contractor_last_opened_at: Optional[datetime] = None
    contractor_open_count: int = 0
    created_at: datetime


# ---------- Agenda ----------
class AgendaEventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = None
    start_at: datetime
    end_at: Optional[datetime] = None
    all_day: bool = False
    scope: str = Field(default="construction", pattern="^(construction|prospection)$")
    project_id: Optional[int] = None
    phase_id: Optional[int] = None
    assignee_id: Optional[int] = None
    contact_request_id: Optional[int] = None
    lead_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    event_type: str = "chantier"


class AgendaEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    scope: Optional[str] = Field(
        default=None, pattern="^(construction|prospection)$"
    )
    project_id: Optional[int] = None
    phase_id: Optional[int] = None
    assignee_id: Optional[int] = None
    contact_request_id: Optional[int] = None
    lead_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    event_type: Optional[str] = None


class AgendaEventRead(_Base):
    id: int
    title: str
    description: Optional[str]
    location: Optional[str]
    start_at: datetime
    end_at: Optional[datetime]
    all_day: bool
    scope: str = "construction"
    project_id: Optional[int]
    phase_id: Optional[int] = None
    assignee_id: Optional[int]
    contact_request_id: Optional[int] = None
    lead_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
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
    address: Optional[str] = Field(default=None, max_length=500)
    bon_type: Optional[str] = Field(default=None, max_length=32)
    assignee_user_id: Optional[int] = None
    # False = demande interne (gestion immobilière) → pas de signature.
    requires_signature: Optional[bool] = None
    origin: Optional[str] = Field(default=None, max_length=32)


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
    address: Optional[str] = None
    bon_type: Optional[str] = None
    assignee_user_id: Optional[int] = None
    requires_signature: Optional[bool] = None


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
    address: Optional[str] = None
    bon_type: str = "temps_materiel"
    assignee_user_id: Optional[int] = None
    requires_signature: bool = True
    origin: Optional[str] = None
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
    # Tous les champs sont optionnels — l'admin peut corriger l'heure
    # de début, l'heure de fin, ou réassigner à un autre projet/lead.
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    hours: Optional[float] = None
    task: Optional[str] = None
    geolocation: Optional[str] = None
    approved: Optional[bool] = None
    notes: Optional[str] = None
    project_id: Optional[int] = None
    contact_request_id: Optional[int] = None
    employe_id: Optional[int] = None


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
    # Référence optionnelle : laissée vide, l'API attribue le prochain
    # numéro séquentiel (aligné sur la séquence QuickBooks). Ça garantit
    # que les factures « hors projet » suivent la même numérotation que
    # celles générées depuis un projet, au lieu d'un horodatage côté
    # client.
    reference: str = Field(default="", max_length=32)
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
    is_final: bool = False


class FactureUpdate(BaseModel):
    # Le numéro de référence est éditable par un admin (correction
    # ponctuelle, alignement sur la séquence QBO, fusion). Conflit
    # d'unicité géré par la contrainte SQL — l'API renverra une 4xx.
    reference: Optional[str] = None
    subtotal: Optional[float] = None
    tps: Optional[float] = None
    tvq: Optional[float] = None
    total: Optional[float] = None
    balance: Optional[float] = None
    status: Optional[str] = None
    issued_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    next_reminder_at: Optional[datetime] = None
    qbo_invoice_id: Optional[str] = None
    qbo_doc_number: Optional[str] = None
    qbo_sync_token: Optional[str] = None
    internal_notes: Optional[str] = None
    client_note: Optional[str] = None
    is_final: Optional[bool] = None


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
    last_reminder_at: Optional[datetime] = None
    reminder_count: int = 0
    next_reminder_at: Optional[datetime] = None
    qbo_invoice_id: Optional[str]
    qbo_doc_number: Optional[str]
    internal_notes: Optional[str] = None
    client_note: Optional[str] = None
    is_final: bool = False
    signed_name: Optional[str] = None
    signed_at: Optional[datetime] = None
    signature_token: Optional[str] = None
    created_at: datetime


# ---------- Achat ----------
class PurchaseOrderCreate(BaseModel):
    # Optionnel : si non fourni, l'endpoint utilise next_po_number
    # pour attribuer une référence PO-XXXX séquentielle.
    reference: Optional[str] = Field(default=None, max_length=32)
    fournisseur_id: Optional[int] = None
    project_id: Optional[int] = None
    assigned_employe_id: Optional[int] = None
    description: Optional[str] = None
    amount_max: Optional[float] = None
    payment_method: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None
    status: Optional[str] = Field(default=None, max_length=32)


class PurchaseOrderUpdate(BaseModel):
    fournisseur_id: Optional[int] = None
    project_id: Optional[int] = None
    assigned_employe_id: Optional[int] = None
    description: Optional[str] = None
    amount_max: Optional[float] = None
    payment_method: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None
    status: Optional[str] = Field(default=None, max_length=32)
    sent_at: Optional[datetime] = None


class PurchaseOrderRead(_Base):
    id: int
    reference: str
    fournisseur_id: Optional[int]
    project_id: Optional[int]
    assigned_employe_id: Optional[int]
    description: Optional[str]
    amount_max: Optional[float]
    payment_method: Optional[str]
    status: str
    sent_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime


class AchatCreate(BaseModel):
    # Référence interne libre (ex. mémo court). Pas de séquence
    # automatique pour les achats — voir supplier_invoice_number pour
    # l'identification comptable.
    reference: Optional[str] = Field(default=None, max_length=32)
    purchase_order_id: Optional[int] = None
    fournisseur_id: Optional[int] = None
    project_id: Optional[int] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    amount_taxes: Optional[float] = None
    amount_tps: Optional[float] = None
    amount_tvq: Optional[float] = None
    supplier_invoice_number: Optional[str] = Field(default=None, max_length=64)
    invoice_date: Optional[date] = None
    payment_method: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None
    status: Optional[str] = Field(default=None, max_length=32)
    is_billable: Optional[bool] = None
    markup_percent: Optional[float] = Field(default=None, ge=0, le=500)
    sous_traitant_id: Optional[int] = None
    kind: Optional[str] = Field(default=None, max_length=16)
    hours: Optional[float] = Field(default=None, ge=0)


class AchatUpdate(BaseModel):
    purchase_order_id: Optional[int] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    amount_taxes: Optional[float] = None
    amount_tps: Optional[float] = None
    amount_tvq: Optional[float] = None
    status: Optional[str] = None
    received_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = None
    fournisseur_id: Optional[int] = None
    project_id: Optional[int] = None
    payment_method: Optional[str] = Field(default=None, max_length=32)
    supplier_invoice_number: Optional[str] = Field(default=None, max_length=64)
    invoice_date: Optional[date] = None
    is_billable: Optional[bool] = None
    markup_percent: Optional[float] = Field(default=None, ge=0, le=500)
    sous_traitant_id: Optional[int] = None
    kind: Optional[str] = Field(default=None, max_length=16)
    hours: Optional[float] = Field(default=None, ge=0)


class AchatRead(_Base):
    id: int
    reference: Optional[str]
    purchase_order_id: Optional[int]
    fournisseur_id: Optional[int]
    project_id: Optional[int]
    description: Optional[str]
    amount: Optional[float]
    amount_taxes: Optional[float] = None
    amount_tps: Optional[float] = None
    amount_tvq: Optional[float] = None
    supplier_invoice_number: Optional[str]
    invoice_date: Optional[date]
    status: str
    received_at: Optional[datetime]
    paid_at: Optional[datetime]
    due_at: Optional[datetime] = None
    receipt_url: Optional[str]
    has_receipt_image: bool = False
    receipt_image_content_type: Optional[str] = None
    payment_method: Optional[str] = None
    qbo_bill_id: Optional[str] = None
    qbo_doc_number: Optional[str] = None
    notes: Optional[str]
    is_billable: bool = True
    markup_percent: Optional[float] = None
    invoiced_at: Optional[datetime] = None
    facture_item_id: Optional[int] = None
    sous_traitant_id: Optional[int] = None
    kind: str = "material"
    hours: Optional[float] = None
    created_at: datetime
