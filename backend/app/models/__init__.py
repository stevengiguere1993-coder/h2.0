"""
Models module - SQLAlchemy ORM models.

All models are imported here so their tables are registered
with the shared metadata for Alembic autogenerate and create_all.
"""

from app.models.achat import Achat
from app.models.agenda_event import AgendaEvent
from app.models.audit_log import AuditLog
from app.models.bon_item import BonItem
from app.models.bon_travail import BonTravail
from app.models.calendar_sync import (
    AvailabilitySlot,
    ExternalBusyBlock,
    UserCalendarFeed,
)
from app.models.centris_listing import CentrisListing
from app.models.client import Client
from app.models.client_document import ClientDocument  # noqa: F401
from app.models.contact import Contact  # noqa: F401
from app.models.contact_hide import ContactHide  # noqa: F401
from app.models.contact_request import ContactRequest
from app.models.contact_request_photo import ContactRequestPhoto
from app.models.devlog_client import DevlogClient  # noqa: F401
from app.models.devlog_invoice import DevlogInvoice  # noqa: F401
from app.models.devlog_invoice_item import DevlogInvoiceItem  # noqa: F401
from app.models.devlog_lead import DevlogLead  # noqa: F401
from app.models.devlog_lead_need import DevlogLeadNeed  # noqa: F401
from app.models.devlog_project import DevlogProject  # noqa: F401
from app.models.devlog_soumission import DevlogSoumission  # noqa: F401
from app.models.devlog_soumission_item import DevlogSoumissionItem  # noqa: F401
from app.models.devlog_soumission_section import DevlogSoumissionSection  # noqa: F401
from app.models.devlog_sous_traitant import DevlogSousTraitant  # noqa: F401
from app.models.devlog_time_entry import DevlogTimeEntry  # noqa: F401
from app.models.email_template import EmailTemplate
from app.models.employe import Employe
from app.models.entreprise import Entreprise, EntrepriseLink, EntreprisePartner  # noqa: F401
from app.models.entreprise_finance import (  # noqa: F401
    EntrepriseFinanceSnapshot,
    EntrepriseValueMilestone,
    EntrepriseValuePlan,
    FinanceSource,
    MilestoneStatus,
)
from app.models.entreprise_recurrence import (  # noqa: F401
    FrequenceUnit,
    TacheTemplate,
)
from app.models.entreprise_tache import EntrepriseTache, TacheStatus  # noqa: F401
from app.models.entreprise_tache_assignee import EntrepriseTacheAssignee  # noqa: F401
from app.models.entreprise_tache_immeuble import EntrepriseTacheImmeuble  # noqa: F401
from app.models.lead_analysis import (  # noqa: F401
    LeadAnalysis,
    LeadAnalysisAttachment,
    LeadAnalysisStatus,
)
from app.models.org_node import OrgNode  # noqa: F401
from app.models.qg_embedding import Embedding  # noqa: F401
from app.models.rencontre import (  # noqa: F401
    Rencontre,
    RencontreSection,
    RencontreStatus,
)
from app.models.qg_strategic import (  # noqa: F401
    Activity,
    ActivityKind,
    AIConversation,
    AIMessage,
    Domain,
    DomainType,
    Insight,
    InsightStatus,
    InsightType,
    KPI,
    StrategicProject,
    StrategicProjectStatus,
    Summary,
    SummaryScope,
    SummaryType,
    Vision,
)
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.follow_up import FollowUp
from app.models.fournisseur import Fournisseur
from app.models.help_request import HelpRequest
from app.models.investissement import (  # noqa: F401
    Distribution,
    DistributionType,
    Investissement,
    InvestissementStatus,
)
from app.models.immobilier import (  # noqa: F401
    Bail,
    BailRenouvellement,
    BailRenouvellementStatus,
    BailStatus,
    Evaluation,
    EvaluationKind,
    Hypotheque,
    HypothequeStatus,
    Immeuble,
    ImmeubleOwnership,
    ImmeubleType,
    Logement,
    LogementStatus,
    Locataire,
    MaintenanceOrdre,
    MaintenancePriorite,
    MaintenanceStatus,
    PaiementLoyer,
)
from app.models.kratos_message import (  # noqa: F401
    KratosIntentKind,
    KratosMessage,
    KratosMessageStatus,
)
from app.models.kratos_problem import (  # noqa: F401
    KratosProblem,
    KratosProblemSeverity,
    KratosProblemStatus,
)
from app.models.leave_request import LeaveRequest, LeaveStatus  # noqa: F401
from app.models.measurement import MeasurementSnapshot
from app.models.measurement_photo import MeasurementPhoto
from app.models.market_rent import MarketRent
from app.models.montreal_property_unit import MontrealPropertyUnit
from app.models.notification import Notification
from app.models.numbering_counter import NumberingCounter
from app.models.payment import Payment
from app.models.project import Project
from app.models.push_subscription import PushSubscription  # noqa: F401
from app.models.project_member import ProjectMember
from app.models.project_phase import ProjectPhase
from app.models.project_subcontractor_contract import (  # noqa: F401
    ProjectSubcontractorContract,
)
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.project_assignees import (
    ProjectPhaseAssignee,
    ProjectTaskAssignee,
)
from app.models.project_photo import ProjectPhoto
from app.models.project_task import ProjectTask
from app.models.prospection_analyse import ProspectionAnalyse
from app.models.prospection_deal import ProspectionDeal
from app.models.prospection_deal_task import ProspectionDealTask
from app.models.prospection_deal_task_assignee import (
    ProspectionDealTaskAssignee,
)
from app.models.prospection_deal_task_immeuble import (
    ProspectionDealTaskImmeuble,
)
from app.models.prospection_lead import ProspectionLead
from app.models.prospection_lead_list import (
    ProspectionLeadList,
    ProspectionLeadListMember,
)
from app.models.prospection_lead_photo import ProspectionLeadPhoto
from app.models.prospection_lead_transaction import (
    ProspectionLeadTransaction,
)
from app.models.punch import Punch
from app.models.purchase_agreement import (
    PurchaseAgreement,
    PurchaseAgreementStatus,  # noqa: F401
)
from app.models.purchase_agreement_template import PurchaseAgreementTemplate
from app.models.qbo_account_map import QboAccountMap
from app.models.qbo_token import QboToken
from app.models.rental_listing import RentalListing
from app.models.req_company import ReqCompany
from app.models.sales_task import SalesTask, sales_task_assignees  # noqa: F401
from app.models.seo_article import SeoArticle
from app.models.service_template import ServiceTemplate, ServiceTemplateItem
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem
from app.models.sous_traitant import SousTraitant
from app.models.user import User
from app.models.user_business_role import (  # noqa: F401
    FunctionalRole,
    UserBusinessRole,
)
from app.models.appointment_type import AppointmentType  # noqa: F401
from app.models.voice import (  # noqa: F401
    Call,
    CallDirection,
    CallRoute,
    CallRouteAction,
    CallStatus,
    CallTranscript,
    CallTurn,
    PhoneNumber,
    VoiceBusinessHours,
    VoiceCallerIntel,
    VoiceClientPresence,
    VoiceFilter,
    VoiceSms,
    VoiceUsageDaily,
)

__all__ = [
    "Achat",
    "AgendaEvent",
    "AuditLog",
    "BonItem",
    "BonTravail",
    "AvailabilitySlot",
    "ExternalBusyBlock",
    "UserCalendarFeed",
    "CentrisListing",
    "Client",
    "ClientDocument",
    "ContactRequest",
    "ContactRequestPhoto",
    "DevlogClient",
    "DevlogInvoice",
    "DevlogInvoiceItem",
    "DevlogLead",
    "DevlogProject",
    "DevlogSoumission",
    "DevlogSoumissionItem",
    "DevlogSoumissionSection",
    "DevlogSousTraitant",
    "DevlogTimeEntry",
    "EmailTemplate",
    "Employe",
    "Facture",
    "FactureItem",
    "FollowUp",
    "Fournisseur",
    "HelpRequest",
    "Bail",
    "BailRenouvellement",
    "Evaluation",
    "Distribution",
    "Hypotheque",
    "Immeuble",
    "ImmeubleOwnership",
    "Investissement",
    "Logement",
    "Locataire",
    "MaintenanceOrdre",
    "PaiementLoyer",
    "LeaveRequest",
    "MarketRent",
    "MeasurementSnapshot",
    "MeasurementPhoto",
    "MontrealPropertyUnit",
    "Notification",
    "NumberingCounter",
    "Payment",
    "Project",
    "ProjectMember",
    "ProjectPhase",
    "ProjectSubcontractorContract",
    "ProjectPhaseAssignee",
    "ProjectPhoto",
    "ProjectTask",
    "ProspectionAnalyse",
    "ProspectionDeal",
    "ProspectionDealTask",
    "ProspectionDealTaskAssignee",
    "ProspectionDealTaskImmeuble",
    "ProspectionLead",
    "ProspectionLeadList",
    "ProspectionLeadListMember",
    "ProspectionLeadPhoto",
    "ProspectionLeadTransaction",
    "PurchaseAgreement",
    "PurchaseAgreementTemplate",
    "ProjectTaskAssignee",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "Punch",
    "QboAccountMap",
    "QboToken",
    "RentalListing",
    "ReqCompany",
    "SalesTask",
    "SeoArticle",
    "ServiceTemplate",
    "ServiceTemplateItem",
    "Soumission",
    "SoumissionItem",
    "SousTraitant",
    "User",
    "Call",
    "CallRoute",
    "CallTranscript",
    "CallTurn",
    "PhoneNumber",
    "VoiceBusinessHours",
    "VoiceCallerIntel",
    "VoiceClientPresence",
    "VoiceFilter",
    "VoiceSms",
    "VoiceUsageDaily",
]
