"""Pydantic schemas for SousTraitant CRUD."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SousTraitantCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    contact_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=500)
    rbq_license: Optional[str] = Field(default=None, max_length=32)
    rbq_expires_at: Optional[date] = None
    insurance_provider: Optional[str] = Field(default=None, max_length=255)
    insurance_policy_number: Optional[str] = Field(default=None, max_length=64)
    insurance_expires_at: Optional[date] = None
    trades: Optional[str] = Field(default=None, max_length=500)
    hourly_rate: Optional[float] = Field(default=None, ge=0)
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None


class SousTraitantUpdate(BaseModel):
    full_name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    rbq_license: Optional[str] = None
    rbq_expires_at: Optional[date] = None
    insurance_provider: Optional[str] = None
    insurance_policy_number: Optional[str] = None
    insurance_expires_at: Optional[date] = None
    trades: Optional[str] = None
    hourly_rate: Optional[float] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    active: Optional[bool] = None
    notes: Optional[str] = None


class SousTraitantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    contact_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    rbq_license: Optional[str]
    rbq_expires_at: Optional[date]
    insurance_provider: Optional[str]
    insurance_policy_number: Optional[str]
    insurance_expires_at: Optional[date]
    trades: Optional[str]
    hourly_rate: Optional[float]
    rating: Optional[int]
    active: bool
    notes: Optional[str]
    created_at: datetime
