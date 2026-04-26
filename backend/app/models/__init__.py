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
from app.models.client import Client
from app.models.contact_request import ContactRequest
from app.models.contact_request_photo import ContactRequestPhoto
from app.models.employe import Employe
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.follow_up import FollowUp
from app.models.fournisseur import Fournisseur
from app.models.help_request import HelpRequest
from app.models.leave_request import LeaveRequest, LeaveStatus  # noqa: F401
from app.models.measurement import MeasurementSnapshot
from app.models.measurement_photo import MeasurementPhoto
from app.models.notification import Notification
from app.models.numbering_counter import NumberingCounter
from app.models.payment import Payment
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_phase import ProjectPhase
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.project_assignees import (
    ProjectPhaseAssignee,
    ProjectTaskAssignee,
)
from app.models.project_photo import ProjectPhoto
from app.models.project_task import ProjectTask
from app.models.punch import Punch
from app.models.qbo_account_map import QboAccountMap
from app.models.qbo_token import QboToken
from app.models.sales_task import SalesTask, sales_task_assignees  # noqa: F401
from app.models.seo_article import SeoArticle
from app.models.service_template import ServiceTemplate, ServiceTemplateItem
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem
from app.models.sous_traitant import SousTraitant
from app.models.user import User

__all__ = [
    "Achat",
    "AgendaEvent",
    "AuditLog",
    "BonItem",
    "BonTravail",
    "AvailabilitySlot",
    "ExternalBusyBlock",
    "UserCalendarFeed",
    "Client",
    "ContactRequest",
    "ContactRequestPhoto",
    "Employe",
    "Facture",
    "FactureItem",
    "FollowUp",
    "Fournisseur",
    "HelpRequest",
    "LeaveRequest",
    "MeasurementSnapshot",
    "MeasurementPhoto",
    "Notification",
    "NumberingCounter",
    "Payment",
    "Project",
    "ProjectMember",
    "ProjectPhase",
    "ProjectPhaseAssignee",
    "ProjectPhoto",
    "ProjectTask",
    "ProjectTaskAssignee",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "Punch",
    "QboAccountMap",
    "QboToken",
    "SalesTask",
    "SeoArticle",
    "ServiceTemplate",
    "ServiceTemplateItem",
    "Soumission",
    "SoumissionItem",
    "SousTraitant",
    "User",
]
