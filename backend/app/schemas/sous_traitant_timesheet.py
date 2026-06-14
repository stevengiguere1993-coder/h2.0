"""Pydantic schemas pour la feuille de temps sous-traitant."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SousTraitantTimesheetCreate(BaseModel):
    sous_traitant_id: int
    project_id: Optional[int] = None
    work_date: date
    worker_count: int = Field(default=1, ge=1)
    total_hours: float = Field(..., ge=0)
    notes: Optional[str] = Field(default=None, max_length=2000)


class SousTraitantTimesheetUpdate(BaseModel):
    sous_traitant_id: Optional[int] = None
    project_id: Optional[int] = None
    work_date: Optional[date] = None
    worker_count: Optional[int] = Field(default=None, ge=1)
    total_hours: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = Field(default=None, max_length=2000)


class SousTraitantTimesheetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sous_traitant_id: int
    project_id: Optional[int]
    work_date: date
    worker_count: int
    total_hours: float
    notes: Optional[str]
    created_at: datetime
