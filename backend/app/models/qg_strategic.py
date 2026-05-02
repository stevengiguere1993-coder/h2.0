"""Modèles stratégiques du QG (volet Gestion d'entreprises).

Inspirés de la spec QG : domaines fonctionnels, KPIs, activités
business, résumés IA, insights, visions stratégiques, projets
proposés (par humain ou par IA), historique de conversations IA.

Tous scopés par ``entreprise_id`` pour le multi-tenancy. Le calcul
des permissions reste côté endpoint (whitelist + EntreprisePartner).

Pas de pgvector ici — l'indexation sémantique sera ajoutée en PR 2.3
dans une table ``ai_embedding`` séparée pour ne pas alourdir les
modèles métier.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


# ─── ENUMS ──────────────────────────────────────────────────────────────


class DomainType(str, Enum):
    FINANCE = "finance"
    SALES = "sales"
    OPERATIONS = "operations"
    HR = "hr"
    MARKETING = "marketing"
    PRODUCT = "product"
    LEGAL = "legal"
    IT = "it"
    CUSTOMER_SUPPORT = "customer_support"
    STRATEGY = "strategy"
    OTHER = "other"


class InsightType(str, Enum):
    RISK = "risk"
    OPPORTUNITY = "opportunity"
    SYNERGY = "synergy"
    ANOMALY = "anomaly"
    RECOMMENDATION = "recommendation"


class InsightStatus(str, Enum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    IN_ACTION = "in_action"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class SummaryType(str, Enum):
    DAILY_BRIEFING = "daily_briefing"
    WEEKLY_REVIEW = "weekly_review"
    MONTHLY_REVIEW = "monthly_review"
    QUARTERLY_REVIEW = "quarterly_review"
    COMPANY_PULSE = "company_pulse"


class SummaryScope(str, Enum):
    ORGANIZATION = "organization"
    COMPANY = "company"  # = entreprise dans notre vocabulaire
    DOMAIN = "domain"


class StrategicProjectStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    REJECTED = "rejected"


class ActivityKind(str, Enum):
    EMAIL_RECEIVED = "email_received"
    EMAIL_SENT = "email_sent"
    MEETING_SCHEDULED = "meeting_scheduled"
    MEETING_HELD = "meeting_held"
    SALE_CLOSED = "sale_closed"
    INVOICE_PAID = "invoice_paid"
    INVOICE_OVERDUE = "invoice_overdue"
    DOCUMENT_CREATED = "document_created"
    MESSAGE_POSTED = "message_posted"
    KPI_UPDATED = "kpi_updated"
    MANUAL_NOTE = "manual_note"
    OTHER = "other"


# ─── DOMAINS ────────────────────────────────────────────────────────────


class Domain(Base, TimestampUpdateMixin):
    """Domaine fonctionnel d'une entreprise (finance / ventes / ops…).

    Permet de catégoriser tâches, KPIs, activités et insights par
    département pour les vues filtrées et les rapports cross-cutting.
    """

    __tablename__ = "qg_domains"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        default=DomainType.OTHER.value,
        server_default=DomainType.OTHER.value,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ─── KPIs ───────────────────────────────────────────────────────────────


class KPI(Base, TimestampUpdateMixin):
    """Indicateur clé d'une entreprise (par domaine optionnel).

    Une ligne = 1 valeur pour 1 période. L'historique se construit en
    accumulant les lignes (period_start qui change). Permet les
    sparklines + comparaisons period-over-period.
    """

    __tablename__ = "qg_kpis"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    domain_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qg_domains.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Clé canonique (slug) ex. 'mrr', 'tasks_done', 'health_score'
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    value: Mapped[Optional[float]] = mapped_column(
        Numeric(18, 4), nullable=True
    )
    target: Mapped[Optional[float]] = mapped_column(
        Numeric(18, 4), nullable=True
    )
    delta_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 4), nullable=True
    )

    period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# ─── ACTIVITIES (timeline business) ─────────────────────────────────────


class Activity(Base):
    """Événement business unifié (email reçu, vente conclue, facture
    payée, KPI mis à jour…). Sert de feed brut pour les briefings IA.

    Source = provider externe (gmail, qbo, monday…) ou source interne
    (notre app). external_id permet la déduplication idempotente lors
    des syncs répétées.
    """

    __tablename__ = "qg_activities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    domain_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qg_domains.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    actor_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    actor_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )

    amount: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    currency: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    metadata_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )


# ─── SUMMARIES (sortie IA : briefings, reviews) ─────────────────────────


class Summary(Base):
    """Synthèse générée par l'IA (briefing quotidien, revue hebdo…).

    On garde l'historique : une ligne par génération, jamais d'écrasement.
    Permet de comparer ce qu'on disait il y a un mois vs. maintenant, et
    de retomber sur un ancien briefing si on a perdu le fil.
    """

    __tablename__ = "qg_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        default=SummaryType.DAILY_BRIEFING.value,
    )
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=SummaryScope.COMPANY.value,
    )

    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Liste de bullet points / faits saillants, JSON-encodée.
    highlights_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Provenance IA
    model_used: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    provider: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    prompt_version: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    input_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    output_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    generation_duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# ─── INSIGHTS (alertes, opportunités, anomalies détectées par IA) ──────


class Insight(Base, TimestampUpdateMixin):
    """Alerte/proposition générée par l'IA.

    Cycle de vie : new → acknowledged → in_action → resolved/dismissed.
    Liée optionnellement à un summary source pour traçabilité.
    """

    __tablename__ = "qg_insights"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    domain_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qg_domains.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False,
        default=InsightStatus.NEW.value,
        server_default=InsightStatus.NEW.value,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    confidence: Mapped[Optional[float]] = mapped_column(
        Numeric(4, 3), nullable=True
    )
    suggested_actions_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    estimated_impact_currency: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    estimated_impact_label: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    source_summary_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qg_summaries.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    acknowledged_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ─── VISIONS (horizons stratégiques) ────────────────────────────────────


class Vision(Base, TimestampUpdateMixin):
    """Vision stratégique pour un horizon donné (7j / 30j / 90j / 12m).

    Générée par IA (à partir des KPIs + activités + insights), validable
    ensuite par l'humain (approved_by_user_id).
    """

    __tablename__ = "qg_visions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    horizon_label: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # ex. '7 jours', '30 jours', '12 mois'
    horizon_start: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_end: Mapped[date] = mapped_column(Date, nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    objectives_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    key_actions_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    generated_by_ai: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ─── STRATEGIC PROJECTS (proposés humain ou IA) ─────────────────────────


class StrategicProject(Base, TimestampUpdateMixin):
    """Projet stratégique d'une entreprise (au sens « grosse initiative »,
    distinct des Project du volet Construction).

    Peut être proposé par l'IA (proposed_by_ai=True) avec rationale, ou
    saisi manuellement. Une fois approuvé, on crée des EntrepriseTache
    enfants pour le décliner en exécution.
    """

    __tablename__ = "qg_strategic_projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    domain_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qg_domains.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default=StrategicProjectStatus.PROPOSED.value,
        server_default=StrategicProjectStatus.PROPOSED.value,
        index=True,
    )

    proposed_by_ai: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    ai_rationale: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    estimated_impact_currency: Mapped[Optional[float]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    estimated_roi: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 4), nullable=True
    )

    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


# ─── AI CONVERSATIONS (historique du command bar ⌘K) ───────────────────


class AIConversation(Base, TimestampUpdateMixin):
    """Conversation IA initiée depuis la command bar ⌘K.

    Privée à l'utilisateur qui la crée (pas partagée à l'entreprise).
    L'entreprise_context_id mémorise quel volet on regardait pour
    permettre les follow-ups contextuels.
    """

    __tablename__ = "qg_ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    entreprise_context_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("entreprises.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    title: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )


class AIMessage(Base):
    """Un message dans une conversation IA (user ou assistant)."""

    __tablename__ = "qg_ai_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("qg_ai_conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # 'user' | 'assistant' | 'system'
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Provenance IA pour les messages assistant
    model_used: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    provider: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    input_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    output_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
