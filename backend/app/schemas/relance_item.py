"""Schemas pour les relances planifiées par lead (RelanceItem)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Channel = Literal["call", "email", "sms"]
ItemStatus = Literal["pending", "sent", "done", "skipped", "cancelled"]


class RelanceItemCreate(BaseModel):
    channel: Channel = "call"
    label: str = Field(..., min_length=1, max_length=160)
    scheduled_at: datetime
    email_template_id: Optional[int] = None
    position: Optional[int] = None


class RelanceItemUpdate(BaseModel):
    channel: Optional[Channel] = None
    label: Optional[str] = Field(default=None, min_length=1, max_length=160)
    scheduled_at: Optional[datetime] = None
    email_template_id: Optional[int] = None
    position: Optional[int] = None
    status: Optional[ItemStatus] = None


class RelanceItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_request_id: int
    position: int
    channel: str
    label: str
    email_template_id: Optional[int]
    scheduled_at: datetime
    status: str
    created_at: datetime
