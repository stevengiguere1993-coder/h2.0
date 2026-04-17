"""
Pydantic schemas for ContactRequest operations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.contact_request import ContactRequestStatus, ProjectType


class ContactRequestCreate(BaseModel):
    """Public payload posted from the landing form."""

    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=500)
    project_type: ProjectType = ProjectType.AUTRE
    budget_range: Optional[str] = Field(default=None, max_length=32)
    message: str = Field(..., min_length=10, max_length=5000)
    locale: str = Field(default="fr", pattern="^(fr|en)$")
    source: Optional[str] = Field(default=None, max_length=128)
    gdpr_consent: bool = Field(
        ..., description="Must be true — user consents to being contacted"
    )
    marketing_consent: bool = False


class ContactRequestUpdate(BaseModel):
    """Admin update — move the request through the pipeline."""

    status: Optional[ContactRequestStatus] = None
    internal_notes: Optional[str] = Field(default=None, max_length=10_000)


class ContactRequestRead(BaseModel):
    """Schema returned to authenticated staff."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    phone: Optional[str]
    address: Optional[str]
    project_type: str
    budget_range: Optional[str]
    message: str
    locale: str
    source: Optional[str]
    status: str
    internal_notes: Optional[str]
    gdpr_consent: bool
    marketing_consent: bool
    created_at: datetime
    updated_at: datetime


class ContactRequestPublicAck(BaseModel):
    """Public acknowledgement returned after a successful submission.

    Note: do not echo back the submitted data — avoids email enumeration.
    """

    ok: bool = True
    reference: str = Field(
        ..., description="Short human-readable reference for the submission"
    )
