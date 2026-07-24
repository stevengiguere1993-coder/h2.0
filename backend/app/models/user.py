"""
User model for authentication and authorization.
"""

import json
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, LargeBinary, String, Text
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
    "developpement_logiciel",
    "communication",
)
DEFAULT_VOLETS = ["construction", "prospection", "developpement_logiciel"]


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

    # Profil utilisateur — affichage dans la sidebar et dans toutes
    # les listes (assignations, agenda, etc.). Si NULL on retombe sur
    # la partie locale du courriel comme avant.
    first_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    last_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    # Photo de profil stockée en bytes (style avatar). Le content-type
    # est gardé séparément pour pouvoir resservir la blob telle quelle
    # dans la réponse HTTP (image/jpeg, image/png, image/webp). Limite
    # côté upload : ~2 Mo, redimensionnée au besoin par le client.
    avatar_image: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    avatar_content_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    # Couleur de profil — clé courte (ex. « violet », « rose »,
    # « emerald »…). Sert à teinter la pastille d'assignation et
    # à donner une identité visuelle propre à chaque utilisateur
    # dans les listes / kanban. NULL = bleu neutre par défaut.
    profile_color: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    # Mobile personnel (E.164, ex. « +15149619015 »). Click-to-call : quand
    # CET utilisateur lance un appel sortant depuis le portail, c'est SON
    # téléphone qui sonne pour le mettre en relation (mappé ici, pas via un
    # numéro fixe d'environnement Render). Renseigné dans Profil → Mobile.
    phone_e164: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )

    @property
    def display_name(self) -> str:
        """Nom affichable : « Prénom Nom » s'ils sont renseignés,
        sinon la partie locale du courriel."""
        parts: list[str] = []
        if self.first_name:
            parts.append(self.first_name.strip())
        if self.last_name:
            parts.append(self.last_name.strip())
        if parts:
            return " ".join(parts)
        return (self.email or "").split("@", 1)[0]

    @property
    def has_avatar(self) -> bool:
        """True dès qu'un binaire d'avatar est stocké."""
        return self.avatar_image is not None

    def has_min_role(self, role: str) -> bool:
        return ROLE_RANK.get(self.role, 0) >= ROLE_RANK.get(role, 99)

    @property
    def volets(self) -> list[str]:
        """Liste des volets accessibles — UNIQUEMENT ce qui est configuré
        dans l'app (permissions v2, 2026-07-24) : ``volets_json`` (page
        Utilisateurs / Permissions), NULL → volets historiques par défaut.
        Owner & admin = tous les volets. Les anciennes whitelists d'emails
        codées en dur ont été retirées (migrées en DB au boot —
        ``ensure_volets_whitelist_migration``)."""
        if self.role in (UserRole.OWNER.value, UserRole.ADMIN.value):
            return list(VALID_VOLETS)
        if not self.volets_json:
            return list(DEFAULT_VOLETS)
        try:
            parsed = json.loads(self.volets_json)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v in VALID_VOLETS]
        except Exception:  # noqa: BLE001
            pass
        return list(DEFAULT_VOLETS)

    def has_volet(self, volet: str) -> bool:
        return volet in self.volets

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', role='{self.role}')>"
