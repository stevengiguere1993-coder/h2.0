"""
User model for authentication and authorization.
"""

import json
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    pass


class UserRole(str, Enum):
    """User roles with increasing privilege levels.

    - owner: full access (Olivier, Matias). Can manage users + roles.
    - admin: full access except user management.
    - manager: can approve leaves, see CRM/clients/factures/finances.
    - employee: field worker. Sees only assigned projects + own agenda
                + own punches + own leave requests.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"


#: Ordered role ranks — each level includes everything below it.
ROLE_RANK = {
    UserRole.OWNER.value: 4,
    UserRole.ADMIN.value: 3,
    UserRole.MANAGER.value: 2,
    UserRole.EMPLOYEE.value: 1,
}


#: Volets disponibles dans le portail Horizon. Un user peut avoir
#: accès à 1 ou plusieurs volets. Par défaut (backward compat) un
#: user existant a accès aux deux volets historiques (construction +
#: prospection). Les 3 nouveaux volets (entreprises, immobilier,
#: investisseur) sont en développement et restreints à une whitelist.
VALID_VOLETS = (
    "construction",
    "prospection",
    "entreprises",
    "immobilier",
    "investisseur",
)
DEFAULT_VOLETS = ["construction", "prospection"]

#: Whitelists temporaires pour les volets en développement. Mis à jour
#: au cas par cas en attendant la généralisation. Comparaison
#: insensible à la casse.
ENTREPRISES_WHITELIST_EMAILS = {
    "stevengiguere1993@gmail.com",
    "sgiguere@immohorizon.com",
    "pmeuser@immohorizon.com",
    "mvilliard@immohorizon.com",
}

IMMOBILIER_WHITELIST_EMAILS = {
    "stevengiguere1993@gmail.com",
    "sgiguere@immohorizon.com",
}

INVESTISSEUR_WHITELIST_EMAILS = {
    "stevengiguere1993@gmail.com",
    "sgiguere@immohorizon.com",
}


def email_in_whitelist(email: Optional[str], whitelist: set[str]) -> bool:
    if not email:
        return False
    return email.strip().lower() in {w.lower() for w in whitelist}


class User(Base, TimestampMixin):
    """User account. The legacy `is_admin` flag is kept in sync with the
    new `role` column for backward compatibility (admin/owner → True)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(16),
        default=UserRole.EMPLOYEE.value,
        server_default=UserRole.EMPLOYEE.value,
        nullable=False,
        index=True,
    )
    # Opaque secret token used to auth the public ICS feed URL
    # (/api/v1/calendar/my-agenda.ics?token=XXX). The token is embedded
    # in the URL the user pastes into Google/Apple/Outlook — external
    # calendar apps can't send Bearer headers. Regenerating the token
    # invalidates the old subscription URL.
    calendar_feed_token: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    # When True, the user is forced through the /app/change-password
    # screen at next login before being allowed anywhere else. Used by
    # the auto-created employee accounts (mot de passe temporaire
    # « Horizon ») and by admin-triggered resets.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    # Volets accessibles par cet utilisateur, JSON-encodé. Format :
    # `["construction"]`, `["prospection"]` ou `["construction","prospection"]`.
    # Si NULL → backward compat = accès à TOUS les volets.
    volets_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Permission spéciale : peut assigner des RDV agenda à d'autres
    # utilisateurs même sans être manager+. Géré au cas-par-cas par
    # l'owner (ex : Zachary, employé prospecteur qui doit pouvoir
    # planifier des RDV pour son boss).
    can_assign_others: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    # Token opaque pour l'auto-confirmation des RDV agenda par email.
    # L'invité reçoit un lien /agenda/confirm/{event_id}?token=XXX qui
    # valide sans login. Régénérable par l'utilisateur.
    agenda_invite_token: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )

    # Préférence de thème pour le portail (volets construction +
    # prospection + app mobile). 'light' = noir sur blanc (défaut),
    # 'dark' = blanc sur noir. La page publique (immohorizon.com)
    # garde toujours son thème dark, peu importe ce champ.
    theme_preference: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="light",
        server_default="light",
    )

    def has_min_role(self, role: str) -> bool:
        return ROLE_RANK.get(self.role, 0) >= ROLE_RANK.get(role, 99)

    @property
    def volets(self) -> list[str]:
        """Liste des volets accessibles. NULL → tous les volets
        historiques (backward compat).

        Les 3 nouveaux volets (entreprises, immobilier, investisseur)
        sont ajoutés automatiquement si l'email du user est dans la
        whitelist correspondante — peu importe ce qui est stocké dans
        `volets_json`. Ça permet d'activer un volet sans toucher la
        DB le temps du développement."""
        base: list[str]
        if not self.volets_json:
            base = list(DEFAULT_VOLETS)
        else:
            try:
                parsed = json.loads(self.volets_json)
                if isinstance(parsed, list):
                    base = [str(v) for v in parsed if v in VALID_VOLETS]
                else:
                    base = list(DEFAULT_VOLETS)
            except Exception:
                base = list(DEFAULT_VOLETS)

        # Whitelist override pour les volets en développement.
        out = list(base)
        if email_in_whitelist(self.email, ENTREPRISES_WHITELIST_EMAILS):
            if "entreprises" not in out:
                out.append("entreprises")
        if email_in_whitelist(self.email, IMMOBILIER_WHITELIST_EMAILS):
            if "immobilier" not in out:
                out.append("immobilier")
        if email_in_whitelist(self.email, INVESTISSEUR_WHITELIST_EMAILS):
            if "investisseur" not in out:
                out.append("investisseur")
        return out

    def has_volet(self, volet: str) -> bool:
        return volet in self.volets

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', role='{self.role}')>"
