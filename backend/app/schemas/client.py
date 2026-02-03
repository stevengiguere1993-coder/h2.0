"""
Pydantic schemas for Client operations.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.schemas.project import ProjectRead


class ClientBase(BaseModel):
    """Base client schema with common fields."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Client name",
    )


class ClientCreate(ClientBase):
    """Schema for creating a new client."""

    pass


class ClientUpdate(BaseModel):
    """Schema for updating a client. All fields optional."""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Client name",
    )


class ClientRead(ClientBase):
    """Schema for reading client data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ClientReadWithProjects(ClientRead):
    """Schema for reading client with projects."""

    projects: List[ProjectRead] = []
