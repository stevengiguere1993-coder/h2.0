"""UserBusinessRole — rôle fonctionnel attribué à un user pour le
volet construction. Distinct du User.role (owner/admin/manager/
employee) qui régit les permissions techniques.

Un user peut avoir PLUSIEURS rôles fonctionnels (ex. Steven est à la
fois closer et chargé de projet sur certains chantiers).

Rôles supportés (Phase 1) :
  - closer            : vendeur qui se déplace évaluer un prospect
  - gestionnaire      : gestionnaire d'immeubles, prend les urgences
  - charge_projet     : responsable d'un chantier en cours
  - technicien        : ouvrier qui se déplace sur les chantiers
  - admin_office      : back-office, jamais de RV terrain

Ces rôles servent à :
  - Filtrer les agendas (« voir tous les RV des closers »)
  - Déterminer qui peut être assigné à quel type de RV
  - Router les appels téléphoniques (Léa cherche un closer dispo)
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FunctionalRole(str, Enum):
    CLOSER = "closer"
    GESTIONNAIRE = "gestionnaire"
    CHARGE_PROJET = "charge_projet"
    TECHNICIEN = "technicien"
    ADMIN_OFFICE = "admin_office"


FUNCTIONAL_ROLE_LABELS = {
    FunctionalRole.CLOSER.value: "Closer (vendeur terrain)",
    FunctionalRole.GESTIONNAIRE.value: "Gestionnaire immobilier",
    FunctionalRole.CHARGE_PROJET.value: "Chargé de projet",
    FunctionalRole.TECHNICIEN.value: "Technicien",
    FunctionalRole.ADMIN_OFFICE.value: "Admin back-office",
}


class UserBusinessRole(Base):
    __tablename__ = "user_business_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_kind", name="uq_user_role_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    # Note libre (ex. « closer cuisines+SDB », « gestionnaire Plateau »)
    notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
