"""Pydantic schemas for Client operations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

if TYPE_CHECKING:
    from app.schemas.project import ProjectRead


class ClientBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = None
    contact_request_id: Optional[int] = Field(default=None, gt=0)


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = None


class ClientRead(ClientBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ClientReadWithProjects(ClientRead):
    projects: List["ProjectRead"] = []
