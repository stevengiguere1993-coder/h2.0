"""
Pydantic schemas for User operations.

These schemas handle validation and serialization for user-related API operations.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema with common fields."""

    email: EmailStr


class UserCreate(UserBase):
    """
    Schema for creating a new user.

    Used by POST /auth/register endpoint.
    """

    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password must be between 8 and 128 characters",
    )
    is_admin: bool = Field(
        default=False,
        description="Whether the user should have admin privileges",
    )


class UserLogin(BaseModel):
    """
    Schema for user login.

    Used by POST /auth/login endpoint.
    """

    email: EmailStr
    password: str


class UserRead(UserBase):
    """
    Schema for reading user data.

    Used in API responses. Does not include sensitive data like password.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    is_admin: bool
    created_at: datetime


class UserUpdate(BaseModel):
    """
    Schema for updating user data.

    All fields are optional.
    """

    email: Optional[EmailStr] = None
    password: Optional[str] = Field(
        default=None,
        min_length=8,
        max_length=128,
    )
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
