"""
Models module - SQLAlchemy ORM models

All models are imported here to ensure they are registered
with SQLAlchemy's metadata for Alembic autogenerate.
"""

from app.models.user import User
from app.models.client import Client
from app.models.project import Project

__all__ = ["User", "Client", "Project"]
