"""
Project model for managing construction projects.
"""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.client import Client


class Project(Base, TimestampMixin):
    """
    Project model representing construction projects.

    Attributes:
        id: Primary key
        name: Project name
        client_id: Foreign key to the associated client
        created_at: Timestamp when project was created
        client: Reference to the associated client
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationships
    client: Mapped["Client"] = relationship(
        "Client",
        back_populates="projects",
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name='{self.name}', client_id={self.client_id})>"
