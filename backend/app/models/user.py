"""
User model for authentication and authorization.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    pass


class User(Base, TimestampMixin):
    """
    User model representing system users.

    Attributes:
        id: Primary key
        email: Unique email address
        hashed_password: Bcrypt hashed password
        is_active: Whether the user account is active
        is_admin: Whether the user has admin privileges
        created_at: Timestamp when user was created
    """

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

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}')>"
