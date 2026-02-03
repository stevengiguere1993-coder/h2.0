"""
Pydantic schemas for JWT token operations.

These schemas handle validation and serialization for authentication tokens.
"""

from typing import Optional

from pydantic import BaseModel


class Token(BaseModel):
    """
    Schema for token response.

    Returned by POST /auth/login endpoint.
    """

    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """
    Schema for decoded JWT token payload.

    Used internally to validate token contents.
    """

    sub: Optional[str] = None
    exp: Optional[int] = None
    iat: Optional[int] = None
