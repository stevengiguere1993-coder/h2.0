"""
Models module - SQLAlchemy ORM models.

All models are imported here so their tables are registered
with the shared metadata for Alembic autogenerate and create_all.
"""

from app.models.achat import Achat
from app.models.agenda_event import AgendaEvent
from app.models.bon_item import BonItem
from app.models.bon_travail import BonTravail
from app.models.client import Client
from app.models.contact_request import ContactRequest
from app.models.employe import Employe
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.models.project_photo import ProjectPhoto
from app.models.project_task import ProjectTask
from app.models.punch import Punch
from app.models.qbo_token import QboToken
from app.models.seo_article import SeoArticle
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem
from app.models.sous_traitant import SousTraitant
from app.models.user import User

__all__ = [
    "Achat",
    "AgendaEvent",
    "BonItem",
    "BonTravail",
    "Client",
    "ContactRequest",
    "Employe",
    "Facture",
    "FactureItem",
    "Fournisseur",
    "Project",
    "ProjectPhoto",
    "ProjectTask",
    "Punch",
    "QboToken",
    "SeoArticle",
    "Soumission",
    "SoumissionItem",
    "SousTraitant",
    "User",
]
