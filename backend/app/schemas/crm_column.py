"""Schemas pour les colonnes personnalisées du tableau CRM."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CrmColumnCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=120)
    dot: Optional[str] = Field(default=None, max_length=40)
    position: int = 0


class CrmColumnUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=120)
    dot: Optional[str] = Field(default=None, max_length=40)
    position: Optional[int] = None


class CrmColumnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    label: str
    dot: Optional[str]
    position: int
