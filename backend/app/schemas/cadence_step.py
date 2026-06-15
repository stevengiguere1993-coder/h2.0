"""Schemas pour les étapes de la séquence de relance (cadence)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Channel = Literal["call", "email", "sms"]


class CadenceStepCreate(BaseModel):
    channel: Channel = "call"
    delay_days: int = Field(default=0, ge=0, le=365)
    label: str = Field(..., min_length=1, max_length=160)
    email_template_id: Optional[int] = None
    position: Optional[int] = None
    active: bool = True


class CadenceStepUpdate(BaseModel):
    channel: Optional[Channel] = None
    delay_days: Optional[int] = Field(default=None, ge=0, le=365)
    label: Optional[str] = Field(default=None, min_length=1, max_length=160)
    email_template_id: Optional[int] = None
    position: Optional[int] = None
    active: Optional[bool] = None


class CadenceStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    channel: str
    delay_days: int
    label: str
    email_template_id: Optional[int]
    active: bool
    created_at: datetime
