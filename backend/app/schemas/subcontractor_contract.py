"""Schemas — termes de facturation d'un sous-traitant par projet."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.project_subcontractor_contract import BILLING_MODES


class SubcontractorContractCreate(BaseModel):
    project_id: int
    sous_traitant_id: int
    billing_mode: str = Field(default="markup_pct", max_length=16)
    markup_percent: Optional[float] = Field(default=None, ge=0, le=500)
    flat_hourly_rate: Optional[float] = Field(default=None, ge=0)
    lump_sum_amount: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None

    @field_validator("billing_mode")
    @classmethod
    def _valid_mode(cls, v: str) -> str:
        if v not in BILLING_MODES:
            raise ValueError(
                f"billing_mode must be one of {BILLING_MODES}"
            )
        return v


class SubcontractorContractUpdate(BaseModel):
    billing_mode: Optional[str] = Field(default=None, max_length=16)
    markup_percent: Optional[float] = Field(default=None, ge=0, le=500)
    flat_hourly_rate: Optional[float] = Field(default=None, ge=0)
    lump_sum_amount: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None

    @field_validator("billing_mode")
    @classmethod
    def _valid_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in BILLING_MODES:
            raise ValueError(
                f"billing_mode must be one of {BILLING_MODES}"
            )
        return v


class SubcontractorContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    sous_traitant_id: int
    billing_mode: str
    markup_percent: Optional[float]
    flat_hourly_rate: Optional[float]
    lump_sum_amount: Optional[float]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
