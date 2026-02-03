"""
Pydantic schemas for Project operations.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectBase(BaseModel):
    """Base project schema with common fields."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Project name",
    )
    client_id: int = Field(
        ...,
        gt=0,
        description="ID of the associated client",
    )


class ProjectCreate(ProjectBase):
    """Schema for creating a new project."""

    pass


class ProjectUpdate(BaseModel):
    """Schema for updating a project. All fields optional."""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Project name",
    )
    client_id: Optional[int] = Field(
        default=None,
        gt=0,
        description="ID of the associated client",
    )


class ProjectRead(ProjectBase):
    """Schema for reading project data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ProjectReadWithClient(ProjectRead):
    """Schema for reading project with client details."""

    from app.schemas.client import ClientRead

    client: Optional["ClientRead"] = None
