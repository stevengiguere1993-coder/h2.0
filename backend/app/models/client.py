"""
Client model for managing construction clients.
"""

from typing import TYPE_CHECKING, List

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project


class Client(Base, TimestampMixin):
    """
    Client model representing construction clients.

    Attributes:
        id: Primary key
        name: Client name
        created_at: Timestamp when client was created
        projects: List of projects associated with this client
    """

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    # Relationships
    projects: Mapped[List["Project"]] = relationship(
        "Project",
        back_populates="client",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Client(id={self.id}, name='{self.name}')>"
