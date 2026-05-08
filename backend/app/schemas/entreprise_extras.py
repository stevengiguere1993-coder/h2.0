"""Schemas Pydantic pour les chantiers Récurrence + Finance + ValuePlan."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Tâches récurrentes (templates) ────────────────────────────────────


class TacheTemplateBase(BaseModel):
    entreprise_id: int
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    departement: Optional[str] = Field(default=None, max_length=32)
    impact: Optional[int] = Field(default=None, ge=1, le=10)
    confidence: Optional[int] = Field(default=None, ge=1, le=10)
    effort: Optional[int] = Field(default=None, ge=1, le=10)
    assignee_user_id: Optional[int] = None
    every_n: int = Field(default=1, ge=1, le=365)
    unit: str = Field(default="mois", max_length=16)
    lead_days: int = Field(default=7, ge=0, le=90)
    next_due: date
    is_active: bool = True


class TacheTemplateCreate(TacheTemplateBase):
    pass


class TacheTemplateUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    departement: Optional[str] = Field(default=None, max_length=32)
    impact: Optional[int] = Field(default=None, ge=1, le=10)
    confidence: Optional[int] = Field(default=None, ge=1, le=10)
    effort: Optional[int] = Field(default=None, ge=1, le=10)
    assignee_user_id: Optional[int] = None
    every_n: Optional[int] = Field(default=None, ge=1, le=365)
    unit: Optional[str] = Field(default=None, max_length=16)
    lead_days: Optional[int] = Field(default=None, ge=0, le=90)
    next_due: Optional[date] = None
    is_active: Optional[bool] = None


class TacheTemplateRead(TacheTemplateBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nb_materialized: int
    last_materialized_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TacheTemplateGlobalRead(TacheTemplateRead):
    """Variante de `TacheTemplateRead` enrichie du nom de l'entreprise.

    Utilisée par la page globale `/taches/recurrentes` qui liste tous
    les templates cross-entreprise. Évite N+1 côté front.
    """

    entreprise_name: str


class MaterializeResult(BaseModel):
    """Résultat du cron de matérialisation."""
    templates_scanned: int = 0
    taches_created: int = 0
    templates_updated: int = 0
    errors: List[str] = Field(default_factory=list)


class ComplianceCatalogItem(BaseModel):
    """Entrée du catalogue de templates compliance Québec."""
    code: str
    label: str
    description: str
    departement: str
    every_n: int
    unit: str
    lead_days: int
    impact: int
    confidence: int
    effort: int


class ComplianceImportRequest(BaseModel):
    """Sélection de codes catalogue à matérialiser comme templates."""
    codes: List[str] = Field(default_factory=list, min_length=1)
    next_due: Optional[date] = None  # default = 1er du mois prochain


class ComplianceImportResult(BaseModel):
    created: int = 0
    skipped: List[str] = Field(default_factory=list)  # codes déjà présents
    templates: List[TacheTemplateRead] = Field(default_factory=list)


# ─── Finance snapshots ─────────────────────────────────────────────────


class FinanceSnapshotBase(BaseModel):
    entreprise_id: int
    year_month: date  # toujours YYYY-MM-01
    revenu: Optional[float] = Field(default=None, ge=0)
    depenses: Optional[float] = Field(default=None, ge=0)
    ebitda: Optional[float] = None
    resultat_net: Optional[float] = None
    tresorerie: Optional[float] = None
    dette_long_terme: Optional[float] = Field(default=None, ge=0)
    valorisation_estimee: Optional[float] = Field(default=None, ge=0)
    source: str = Field(default="manuel", max_length=16)
    notes: Optional[str] = None


class FinanceSnapshotCreate(FinanceSnapshotBase):
    pass


class FinanceSnapshotUpdate(BaseModel):
    revenu: Optional[float] = Field(default=None, ge=0)
    depenses: Optional[float] = Field(default=None, ge=0)
    ebitda: Optional[float] = None
    resultat_net: Optional[float] = None
    tresorerie: Optional[float] = None
    dette_long_terme: Optional[float] = Field(default=None, ge=0)
    valorisation_estimee: Optional[float] = Field(default=None, ge=0)
    source: Optional[str] = Field(default=None, max_length=16)
    notes: Optional[str] = None


class FinanceSnapshotRead(FinanceSnapshotBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class FinanceTimeseries(BaseModel):
    """Série temporelle pour un graphique évolution P&L + cash + valo."""
    entreprise_id: int
    months: List[str] = Field(default_factory=list)  # YYYY-MM
    revenu: List[Optional[float]] = Field(default_factory=list)
    depenses: List[Optional[float]] = Field(default_factory=list)
    ebitda: List[Optional[float]] = Field(default_factory=list)
    tresorerie: List[Optional[float]] = Field(default_factory=list)
    valorisation: List[Optional[float]] = Field(default_factory=list)


class EntrepriseFinanceSummary(BaseModel):
    """Synthèse rapide d'une entreprise pour la heatmap multi-entreprises."""
    entreprise_id: int
    name: str
    color_accent: str
    last_month: Optional[str] = None
    revenu_ttm: Optional[float] = None        # trailing 12 months
    ebitda_ttm: Optional[float] = None
    tresorerie_courante: Optional[float] = None
    valorisation_courante: Optional[float] = None
    target_valuation: Optional[float] = None
    progress_pct: Optional[float] = None      # 0..100 vers target


# ─── Value plan + milestones ───────────────────────────────────────────


class ValuePlanDriverItem(BaseModel):
    key: str
    label: str
    current: Optional[float] = None
    target: Optional[float] = None
    unit: Optional[str] = None


class ValuePlanBase(BaseModel):
    entreprise_id: int
    target_valuation: float = Field(..., ge=0)
    target_date: date
    multiple_ebitda: Optional[float] = Field(default=None, ge=0, le=100)
    multiple_revenu: Optional[float] = Field(default=None, ge=0, le=100)
    drivers: List[ValuePlanDriverItem] = Field(default_factory=list)
    these: Optional[str] = None
    is_active: bool = True


class ValuePlanCreate(ValuePlanBase):
    pass


class ValuePlanUpdate(BaseModel):
    target_valuation: Optional[float] = Field(default=None, ge=0)
    target_date: Optional[date] = None
    multiple_ebitda: Optional[float] = Field(default=None, ge=0, le=100)
    multiple_revenu: Optional[float] = Field(default=None, ge=0, le=100)
    drivers: Optional[List[ValuePlanDriverItem]] = None
    these: Optional[str] = None
    is_active: Optional[bool] = None


class ValuePlanRead(ValuePlanBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class ValueMilestoneBase(BaseModel):
    plan_id: int
    label: str = Field(..., min_length=1, max_length=255)
    target_date: date
    target_value: Optional[float] = None
    metric: Optional[str] = Field(default=None, max_length=64)
    status: str = Field(default="a_venir", max_length=16)
    achieved_date: Optional[date] = None
    achieved_value: Optional[float] = None
    notes: Optional[str] = None


class ValueMilestoneCreate(ValueMilestoneBase):
    pass


class ValueMilestoneUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=255)
    target_date: Optional[date] = None
    target_value: Optional[float] = None
    metric: Optional[str] = Field(default=None, max_length=64)
    status: Optional[str] = Field(default=None, max_length=16)
    achieved_date: Optional[date] = None
    achieved_value: Optional[float] = None
    notes: Optional[str] = None


class ValueMilestoneRead(ValueMilestoneBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
