﻿"""Pydantic schemas — pôle Développement logiciel (clients & leads)."""

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
    address: Optional[str] = Field(default=None, max_length=500)
    project_type: str = Field(default="autre", max_length=32)
    source: Optional[str] = Field(default=None, max_length=128)
    status: str = Field(default="new", max_length=32)
    kanban_column: Optional[str] = Field(default=None, max_length=64)
    locale: str = Field(default="fr", max_length=8)
    assigned_to_user_id: Optional[int] = None
    project_summary: Optional[str] = None
    budget_range: Optional[str] = Field(default=None, max_length=64)
    notes: Optional[str] = None


class DevlogLeadUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    project_type: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    kanban_column: Optional[str] = None
    locale: Optional[str] = None
    position: Optional[int] = None
    assigned_to_user_id: Optional[int] = None
    project_summary: Optional[str] = None
    budget_range: Optional[str] = None
    notes: Optional[str] = None


class DevlogLeadStatusUpdate(BaseModel):
    """Déplacement d'un lead dans le kanban du CRM."""

    status: str = Field(..., max_length=32)
    kanban_column: Optional[str] = Field(default=None, max_length=64)
    position: Optional[int] = None


class DevlogLeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    company: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    project_type: str
    source: Optional[str]
    status: str
    kanban_column: Optional[str]
    position: int
    locale: str
    assigned_to_user_id: Optional[int]
    project_summary: Optional[str]
    budget_range: Optional[str]
    notes: Optional[str]
    client_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# DevlogLeadNeed (besoins client par pôle)
# --------------------------------------------------------------------------


class DevlogLeadNeedCreate(BaseModel):
    lead_id: int
    position: Optional[int] = None
    pole: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=255)
    notes: Optional[str] = None
    complexity: Optional[str] = Field(default=None, max_length=16)
    priority: Optional[str] = Field(default=None, max_length=16)


class DevlogLeadNeedUpdate(BaseModel):
    position: Optional[int] = None
    pole: Optional[str] = Field(default=None, min_length=1, max_length=64)
    label: Optional[str] = Field(default=None, min_length=1, max_length=255)
    notes: Optional[str] = None
    complexity: Optional[str] = Field(default=None, max_length=16)
    priority: Optional[str] = Field(default=None, max_length=16)


class DevlogLeadNeedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    position: int
    pole: str
    label: str
    notes: Optional[str]
    complexity: Optional[str]
    priority: Optional[str]
    created_at: datetime
    updated_at: datetime


class DevlogLeadPlanItem(BaseModel):
    description: str
    quantity: float = 1
    unit: Optional[str] = "h"
    cost_per_unit: float = 0


class DevlogLeadPlanSection(BaseModel):
    pole: str
    name: str
    billing_kind: str = "initial"
    markup_percent: Optional[float] = 100
    notes: Optional[str] = None
    items: list[DevlogLeadPlanItem] = []


class DevlogLeadPlan(BaseModel):
    summary: str
    sections: list[DevlogLeadPlanSection]


class DevlogLeadPlanToSoumissionRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    plan: DevlogLeadPlan


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
    # --- Refonte « devis_dev » ---------------------------------------
    is_devis_dev: bool = False
    marge_recurrente_pct: Optional[float] = Field(
        default=None, ge=0, le=500
    )
    marge_initiale_pct: Optional[float] = Field(
        default=None, ge=0, le=500
    )
    commission_closer_pct: Optional[float] = Field(
        default=None, ge=0, le=100
    )
    taux_dev_horaire: Optional[float] = Field(default=None, ge=0)
    taux_manager_horaire: Optional[float] = Field(default=None, ge=0)
    heures_manager: Optional[float] = Field(default=None, ge=0)
    client_recurring_description: Optional[str] = None


class DevlogSoumissionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    lead_id: Optional[int] = None
    client_id: Optional[int] = None
    amount: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None
    summary: Optional[str] = None
    notes: Optional[str] = None
    # --- Refonte « devis_dev » ---------------------------------------
    is_devis_dev: Optional[bool] = None
    marge_recurrente_pct: Optional[float] = Field(
        default=None, ge=0, le=500
    )
    marge_initiale_pct: Optional[float] = Field(
        default=None, ge=0, le=500
    )
    commission_closer_pct: Optional[float] = Field(
        default=None, ge=0, le=100
    )
    taux_dev_horaire: Optional[float] = Field(default=None, ge=0)
    taux_manager_horaire: Optional[float] = Field(default=None, ge=0)
    heures_manager: Optional[float] = Field(default=None, ge=0)
    client_recurring_description: Optional[str] = None


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
    # --- Refonte « devis_dev » ---------------------------------------
    is_devis_dev: bool = False
    marge_recurrente_pct: Optional[float] = None
    marge_initiale_pct: Optional[float] = None
    commission_closer_pct: Optional[float] = None
    taux_dev_horaire: Optional[float] = None
    taux_manager_horaire: Optional[float] = None
    heures_manager: Optional[float] = None
    client_recurring_description: Optional[str] = None
    # --- Envoi PDF + signature (vague 1) -----------------------------
    signature_token: Optional[str] = None
    sent_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    signed_name: Optional[str] = None
    signed_ip: Optional[str] = None


# --------------------------------------------------------------------------
# DevlogSoumissionItem (lignes de soumission)
# --------------------------------------------------------------------------


class DevlogSoumissionItemCreate(BaseModel):
    soumission_id: int
    section_id: Optional[int] = None
    position: Optional[int] = None
    description: str = Field(..., min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: float = Field(default=1, ge=0)
    cost_per_unit: float = Field(default=0, ge=0)
    unit_price: float = Field(default=0, ge=0)
    notes: Optional[str] = None
    # --- Refonte « devis_dev » ---------------------------------------
    item_kind: Optional[str] = Field(default=None, max_length=20)
    heures: Optional[float] = Field(default=None, ge=0)


class DevlogSoumissionItemUpdate(BaseModel):
    section_id: Optional[int] = None
    position: Optional[int] = None
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[float] = Field(default=None, ge=0)
    cost_per_unit: Optional[float] = Field(default=None, ge=0)
    unit_price: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    # --- Refonte « devis_dev » ---------------------------------------
    item_kind: Optional[str] = Field(default=None, max_length=20)
    heures: Optional[float] = Field(default=None, ge=0)


class DevlogSoumissionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    soumission_id: int
    section_id: Optional[int]
    position: int
    description: str
    unit: Optional[str]
    quantity: float
    cost_per_unit: float
    unit_price: float
    total: float
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    # --- Refonte « devis_dev » ---------------------------------------
    item_kind: str = "feature"
    heures: Optional[float] = None


# --------------------------------------------------------------------------
# DevisPreview (refonte « devis_dev ») — résultat de compute_devis()
# --------------------------------------------------------------------------


class DevisPreviewRecurringItem(BaseModel):
    id: Optional[int] = None
    description: str
    cost_per_unit: float


class DevisPreviewRecurring(BaseModel):
    total_owner_cost: float
    total_client_amount: float
    marge_amount: float
    marge_pct: float
    items_breakdown: list[DevisPreviewRecurringItem]


class DevisPreviewFeatureClient(BaseModel):
    id: Optional[int] = None
    description: str
    heures: float
    prix_client: float


class DevisPreviewFixedClient(BaseModel):
    id: Optional[int] = None
    description: str
    cost_per_unit: float
    prix_client: float


class DevisPreviewInitial(BaseModel):
    couts_dev: float
    cout_manager: float
    frais_fixes_total: float
    base: float
    closing: float
    total_avant_marge: float
    total_apres_marge: float
    total_final: float
    marge_amount: float
    marge_pct: float
    closer_pct: float
    taux_dev_horaire: float
    taux_manager_horaire: float
    heures_manager: float
    features_client: list[DevisPreviewFeatureClient]
    frais_fixes_client: list[DevisPreviewFixedClient]


class DevisPreview(BaseModel):
    is_invalid: bool
    recurring: DevisPreviewRecurring
    initial: DevisPreviewInitial


# --------------------------------------------------------------------------
# DevlogSoumissionSection
# --------------------------------------------------------------------------


class DevlogSoumissionSectionCreate(BaseModel):
    soumission_id: int
    position: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=255)
    billing_kind: str = Field(default="initial", max_length=16)
    markup_percent: Optional[float] = Field(default=None, ge=0, le=1000)
    client_label: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = None


class DevlogSoumissionSectionUpdate(BaseModel):
    position: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    billing_kind: Optional[str] = None
    markup_percent: Optional[float] = Field(default=None, ge=0, le=1000)
    client_label: Optional[str] = None
    notes: Optional[str] = None


class DevlogSoumissionSectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    soumission_id: int
    position: int
    name: str
    billing_kind: str
    markup_percent: Optional[float]
    client_label: Optional[str]
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
    # Envoi + consultation publique (pièce #5, vague 1).
    signature_token: Optional[str] = None
    sent_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
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
