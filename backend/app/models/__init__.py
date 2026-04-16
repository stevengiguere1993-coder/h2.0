"""
Models module - SQLAlchemy ORM models

All models are imported here to ensure they are registered
with SQLAlchemy's metadata for Alembic autogenerate and create_all.
"""

from app.models.client import Client
from app.models.contact_request import ContactRequest
from app.models.project import Project
from app.models.user import User

__all__ = ["Client", "ContactRequest", "Project", "User"]
