"""
User model for authentication and authorization.
"""

from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, String
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

    def has_min_role(self, role: str) -> bool:
        return ROLE_RANK.get(self.role, 0) >= ROLE_RANK.get(role, 99)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', role='{self.role}')>"
