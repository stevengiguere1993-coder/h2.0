"""Rôle minimum requis pour une capacité configurable.

Une ligne par capacité (cf. ``app.core.capabilities``). Table éditée depuis
Paramètres → Permissions (owner uniquement). Le seed initial (au démarrage)
reproduit le comportement codé en dur, donc aucun changement visible tant que
l'owner ne modifie rien.
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class RolePermission(Base, TimestampUpdateMixin):
    __tablename__ = "role_permissions"

    #: Identifiant de la capacité (ex. "project.delete") — cf. CAPABILITIES.
    capability: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: Rôle minimum requis : "employee" | "manager" | "admin" | "owner".
    min_role: Mapped[str] = mapped_column(String(16), nullable=False)
