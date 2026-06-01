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
    # Entreprise (vs particulier) + représentant facultatif.
    is_company: bool = False
    representative: Optional[str] = Field(default=None, max_length=255)
    # Langue du client — « fr » (défaut) ou « en ».
    language: str = Field(default="fr", pattern="^(fr|en)$")


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = None
    is_company: Optional[bool] = None
    representative: Optional[str] = Field(default=None, max_length=255)
    language: Optional[str] = Field(default=None, pattern="^(fr|en)$")


class ClientRead(ClientBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    # Customer.Id QBO rempli par /api/v1/clients/{id}/push-to-qbo.
    qbo_customer_id: Optional[str] = None


class ClientReadWithProjects(ClientRead):
    projects: List["ProjectRead"] = []
