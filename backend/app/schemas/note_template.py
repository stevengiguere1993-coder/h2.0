"""Pydantic schemas for NoteTemplate CRUD (#16 — catalogue de notes)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class NoteTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1)
    category: str = Field(default="general", max_length=32)


class NoteTemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    body: Optional[str] = Field(default=None, min_length=1)
    category: Optional[str] = Field(default=None, max_length=32)


class NoteTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    body: str
    category: str
    created_at: datetime
