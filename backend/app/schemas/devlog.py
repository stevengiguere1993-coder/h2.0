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
    # Fiche unifiee prospect/client : si le client provient d'une
    # conversion, on expose le lien vers le prospect source + date.
    converted_from_lead_id: Optional[int] = None
    converted_at: Optional[datetime] = None
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
    meeting_notes: Optional[str] = None


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
    meeting_notes: Optional[str] = None
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
    # Module parent (refonte 2026-06). Optionnel et rétrocompatible.
    module_id: Optional[int] = None
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
    module_id: Optional[int] = None
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
    # Module parent (refonte 2026-06) — NULL pour les items legacy /
    # récurrents. Exposé pour permettre au frontend de regrouper.
    module_id: Optional[int] = None
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
# DevlogSoumissionModule (refonte 2026-06 — niveau MODULE)
# --------------------------------------------------------------------------
#
# Un module regroupe des fonctionnalités (items) DANS la section
# « investissement initial ». Le prix d'un module = somme des ``total``
# de ses items. Couche purement organisationnelle en Phase 1 : aucun
# impact sur le calcul du total de la soumission.


class DevlogSoumissionModuleCreate(BaseModel):
    soumission_id: int
    section_id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=255)
    position: Optional[int] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    # État de sélection (servira aux phases suivantes). Default True.
    selected: bool = True


class DevlogSoumissionModuleUpdate(BaseModel):
    section_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    position: Optional[int] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    selected: Optional[bool] = None


class DevlogSoumissionModuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    soumission_id: int
    section_id: Optional[int]
    name: str
    position: int
    description: Optional[str]
    notes: Optional[str]
    selected: bool
    created_at: datetime
    updated_at: datetime


class DevlogSoumissionModuleWithItems(DevlogSoumissionModuleRead):
    """Module enrichi pour la lecture hiérarchique : ses items + le
    total dérivé (somme des ``total`` des items du module)."""

    total: float = 0.0
    items: list[DevlogSoumissionItemRead] = Field(default_factory=list)


class DevlogSoumissionItemAssignModule(BaseModel):
    """Assigne (ou détache si ``module_id`` est NULL) un item à un
    module."""

    module_id: Optional[int] = None


class DevlogModuleReorderRequest(BaseModel):
    """Réordonne les modules d'une soumission : liste ordonnée d'IDs.
    La position de chaque module devient son index dans la liste."""

    module_ids: list[int] = Field(..., min_length=1)


# --------------------------------------------------------------------------
# Lecture hiérarchique d'une soumission (sections → modules → items)
# --------------------------------------------------------------------------
#
# Vue d'organisation additive : pour la section « investissement
# initial » on expose modules → items ; ailleurs (sections récurrentes
# ou items legacy sans section) on expose les items directs. N'altère
# AUCUN calcul de total — purement structurelle.


class DevlogSoumissionSectionStructure(BaseModel):
    """Une section avec ses modules (et leurs items) + ses items
    directs (non rattachés à un module)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    soumission_id: int
    position: int
    name: str
    billing_kind: str
    markup_percent: Optional[float] = None
    client_label: Optional[str] = None
    notes: Optional[str] = None
    modules: list[DevlogSoumissionModuleWithItems] = Field(
        default_factory=list
    )
    direct_items: list[DevlogSoumissionItemRead] = Field(
        default_factory=list
    )


class DevlogSoumissionStructure(BaseModel):
    """Hiérarchie complète d'une soumission pour l'affichage :
    sections → (modules → items) pour l'initial, items directs ailleurs.

    ``orphan_modules`` : modules sans section (cas où la section a été
    supprimée — ``section_id`` mis à NULL). ``orphan_items`` : items
    sans section ET sans module (legacy)."""

    soumission_id: int
    sections: list[DevlogSoumissionSectionStructure] = Field(
        default_factory=list
    )
    orphan_modules: list[DevlogSoumissionModuleWithItems] = Field(
        default_factory=list
    )
    orphan_items: list[DevlogSoumissionItemRead] = Field(
        default_factory=list
    )


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
    # --- Taxes (Quebec) ---------------------------------------------
    tps_amount: float = 0.0
    tvq_amount: float = 0.0
    tps_pct: float = 5.0
    tvq_pct: float = 9.975
    total_client_amount_taxe: float = 0.0


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
    # --- Taxes (Quebec) ---------------------------------------------
    tps_amount: float = 0.0
    tvq_amount: float = 0.0
    tps_pct: float = 5.0
    tvq_pct: float = 9.975
    total_final_taxe: float = 0.0


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
    started_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
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
    # Paiement en ligne via Stripe Checkout (chantier #4, mai 2026).
    stripe_session_id: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None
    payment_method: Optional[str] = None
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
    deposit_required_cents: Optional[int] = Field(default=None, ge=0)


class DevlogContractUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    body: Optional[str] = None
    status: Optional[str] = None
    soumission_id: Optional[int] = None
    client_id: Optional[int] = None
    project_id: Optional[int] = None
    deposit_required_cents: Optional[int] = Field(default=None, ge=0)


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
    deposit_required_cents: Optional[int] = None
    deposit_paid_at: Optional[datetime] = None
    deposit_paid_amount_cents: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class DevlogContractMarkDepositPaid(BaseModel):
    """Payload de ``POST /devlog/contracts/{id}/mark-deposit-paid``.

    Le montant est passé en cents pour éviter les imprécisions float
    (cohérent avec le reste de la facturation Dev Logiciel)."""

    amount_cents: int = Field(..., ge=0)


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


# --------------------------------------------------------------------------
# DevlogProjectPhase / Task / Member / Finances (vague 2, mai 2026)
# --------------------------------------------------------------------------


class DevlogProjectPhaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    position: int = Field(default=0, ge=0)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str = Field(default="planifie", max_length=16)


class DevlogProjectPhaseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    position: Optional[int] = Field(default=None, ge=0)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = Field(default=None, max_length=16)


class DevlogProjectPhaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    description: Optional[str]
    position: int
    start_date: Optional[date]
    end_date: Optional[date]
    status: str
    created_at: datetime
    updated_at: datetime


class DevlogProjectPhaseReorder(BaseModel):
    phase_ids: list[int] = Field(default_factory=list)


class DevlogProjectTaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    phase_id: Optional[int] = Field(default=None, gt=0)
    assignee_user_id: Optional[int] = Field(default=None, gt=0)
    status: str = Field(default="a_faire", max_length=16)
    priority: str = Field(default="moyenne", max_length=16)
    due_date: Optional[date] = None


class DevlogProjectTaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    phase_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    status: Optional[str] = Field(default=None, max_length=16)
    priority: Optional[str] = Field(default=None, max_length=16)
    due_date: Optional[date] = None


class DevlogProjectTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    phase_id: Optional[int]
    title: str
    description: Optional[str]
    assignee_user_id: Optional[int]
    status: str
    priority: str
    due_date: Optional[date]
    created_at: datetime
    updated_at: datetime


class DevlogProjectMemberCreate(BaseModel):
    user_id: Optional[int] = Field(default=None, gt=0)
    sous_traitant_id: Optional[int] = Field(default=None, gt=0)
    role: Optional[str] = Field(default=None, max_length=64)
    hourly_rate: Optional[float] = Field(default=None, ge=0)


class DevlogProjectMemberUpdate(BaseModel):
    role: Optional[str] = Field(default=None, max_length=64)
    hourly_rate: Optional[float] = Field(default=None, ge=0)


class DevlogProjectMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    user_id: Optional[int]
    sous_traitant_id: Optional[int]
    role: Optional[str]
    hourly_rate: Optional[float]
    added_by_user_id: Optional[int]
    added_at: datetime


class DevlogProjectFinances(BaseModel):
    """Vue agregee lecture seule des finances d'un projet Dev Logiciel.

    Refonte (mai 2026) : split initial / recurrent. ``total_soumission``
    et ``total_reste_a_facturer`` ne couvrent plus que la partie
    investissement initial. Les services recurrents ont leurs propres
    KPIs (MRR + nombre de services actifs).
    """

    project_id: int
    soumission_id: Optional[int]
    total_facture: float
    total_paye: float
    total_reste_a_facturer: float
    # Total de l'investissement initial (mise en oeuvre uniquement,
    # sans le recurrent).
    total_soumission: float
    total_heures_facturables: float
    marge_estimee: float
    nb_sections_soumission: int

    # --- Bloc recurrent (mai 2026) ---
    mrr_active_cents: int = 0
    nb_recurring_services_active: int = 0
    nb_recurring_services_pending: int = 0
    nb_recurring_services_paused: int = 0
    nb_recurring_services_cancelled: int = 0


# --------------------------------------------------------------------------
# DevlogProjectPhoto / Purchase / Recap (vague 2 - mai 2026, suite)
# --------------------------------------------------------------------------


class DevlogProjectPhotoRead(BaseModel):
    """Metadonnees d'une photo de projet (sans blob)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    content_type: str
    filename: Optional[str]
    size_bytes: Optional[int]
    caption: Optional[str]
    uploaded_by_user_id: Optional[int]
    uploaded_by_email: Optional[str]
    created_at: datetime


class DevlogProjectPhotoCaptionUpdate(BaseModel):
    caption: Optional[str] = Field(default=None, max_length=500)


class DevlogProjectPurchaseCreate(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    amount_cents: int = Field(..., ge=0)
    supplier: Optional[str] = Field(default=None, max_length=255)
    purchased_at: Optional[date] = None
    notes: Optional[str] = None


class DevlogProjectPurchaseUpdate(BaseModel):
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    amount_cents: Optional[int] = Field(default=None, ge=0)
    supplier: Optional[str] = Field(default=None, max_length=255)
    purchased_at: Optional[date] = None
    notes: Optional[str] = None


class DevlogProjectPurchaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    description: str
    amount_cents: int
    supplier: Optional[str]
    purchased_at: Optional[date]
    notes: Optional[str]
    has_receipt: bool = False
    receipt_filename: Optional[str]
    receipt_content_type: Optional[str]
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class DevlogProjectRecapEvent(BaseModel):
    """Une entree d'audit log resumee pour la frise d'evenements."""

    id: int
    action: str
    entity_type: Optional[str]
    entity_id: Optional[int]
    user_email: Optional[str]
    created_at: datetime
    details_json: Optional[str] = None


class DevlogProjectRecapPhase(BaseModel):
    """Resume d'une phase pour la section Jalons du recap."""

    id: int
    name: str
    status: str
    position: int
    start_date: Optional[date]
    end_date: Optional[date]


class DevlogProjectRecap(BaseModel):
    """Vue lecture seule consolidee d'un projet Dev Logiciel.

    Agrege le statut, les jalons (phases), les KPIs financiers et les
    derniers evenements (audit log) en un seul payload pour l'onglet
    Recap.
    """

    project_id: int
    name: str
    status: str
    started_at: Optional[datetime]
    start_date: Optional[date]
    due_date: Optional[date]

    # Avancement
    nb_phases: int
    nb_phases_terminees: int
    pct_phases_terminees: float
    phases: list[DevlogProjectRecapPhase] = Field(default_factory=list)

    # Heures saisies
    total_heures: float

    # Finances (reuse subset of DevlogProjectFinances)
    total_facture: float
    total_paye: float
    total_reste_a_facturer: float
    total_soumission: float
    marge_estimee: float

    # Achats du projet (cumul)
    total_achats_cents: int
    nb_achats: int

    # --- Services recurrents (mai 2026) ---
    mrr_active_cents: int = 0
    nb_recurring_services_active: int = 0
    nb_recurring_services_pending: int = 0
    delivered_at: Optional[datetime] = None

    # Activite recente
    events: list[DevlogProjectRecapEvent] = Field(default_factory=list)