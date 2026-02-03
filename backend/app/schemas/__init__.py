"""
Schemas module - Pydantic validation schemas

This module contains Pydantic models for:
- Request validation
- Response serialization
- Data transfer objects (DTOs)
"""

from app.schemas.client import (
    ClientCreate,
    ClientRead,
    ClientReadWithProjects,
    ClientUpdate,
)
from app.schemas.project import (
    ProjectCreate,
    ProjectRead,
    ProjectReadWithClient,
    ProjectUpdate,
)
from app.schemas.token import Token, TokenPayload
from app.schemas.user import UserCreate, UserLogin, UserRead, UserUpdate

__all__ = [
    # Client
    "ClientCreate",
    "ClientRead",
    "ClientReadWithProjects",
    "ClientUpdate",
    # Project
    "ProjectCreate",
    "ProjectRead",
    "ProjectReadWithClient",
    "ProjectUpdate",
    # Token
    "Token",
    "TokenPayload",
    # User
    "UserCreate",
    "UserLogin",
    "UserRead",
    "UserUpdate",
]
