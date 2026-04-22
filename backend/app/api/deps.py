"""
FastAPI Dependencies for authentication and authorization.

These dependencies handle token validation and user retrieval
for protected endpoints.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.repositories.user import UserRepository


# OAuth2 scheme for Bearer token authentication
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=True,
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Dependency to get the current authenticated user.

    Validates the JWT token and returns the corresponding user.

    Args:
        token: JWT access token from Authorization header
        db: Database session

    Returns:
        The authenticated User

    Raises:
        HTTPException: 401 if token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Decode and validate token
    user_id_str = decode_token(token)
    if user_id_str is None:
        raise credentials_exception

    try:
        user_id = int(user_id_str)
    except ValueError:
        raise credentials_exception

    # Get user from database
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Legacy admin guard — accepts owner or admin roles.

    Kept for backward compatibility; new code should prefer the
    role-specific deps below (RequireManager, RequireAdmin, RequireOwner).
    """
    if not (current_user.is_admin or current_user.role in ("owner", "admin")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


# --- Role-based guards (phase A/B) ---


def _require_min_role(min_role: str):
    async def check(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if not current_user.has_min_role(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissions insuffisantes.",
            )
        return current_user
    return check


get_current_manager = _require_min_role("manager")
get_current_admin_role = _require_min_role("admin")
get_current_owner = _require_min_role("owner")


# Type aliases for cleaner dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
RequireManager = Annotated[User, Depends(get_current_manager)]
RequireAdminRole = Annotated[User, Depends(get_current_admin_role)]
RequireOwner = Annotated[User, Depends(get_current_owner)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
