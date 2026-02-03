"""
Authentication endpoints.

Handles user login, registration, and profile retrieval.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentAdmin, CurrentUser, DBSession
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserRead
from app.services.auth import AuthService


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/login",
    response_model=Token,
    summary="User login",
    description="Authenticate with email and password to receive an access token.",
)
async def login(
    db: DBSession,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """
    Authenticate user and return access token.

    Uses OAuth2 password flow with email as username.

    - **username**: User's email address
    - **password**: User's password
    """
    auth_service = AuthService(db)
    token = await auth_service.login(
        email=form_data.username,
        password=form_data.password,
    )

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user (admin only)",
    description="Create a new user account. Requires admin privileges.",
)
async def register(
    user_data: UserCreate,
    db: DBSession,
    current_admin: CurrentAdmin,
) -> UserRead:
    """
    Register a new user (admin only).

    Only administrators can create new user accounts.

    - **email**: Unique email address
    - **password**: Password (min 8 characters)
    - **is_admin**: Whether to grant admin privileges
    """
    auth_service = AuthService(db)
    user = await auth_service.register(user_data)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    return UserRead.model_validate(user)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user",
    description="Retrieve the profile of the currently authenticated user.",
)
async def get_me(current_user: CurrentUser) -> UserRead:
    """
    Get current authenticated user's profile.

    Returns the user information associated with the provided access token.
    """
    return UserRead.model_validate(current_user)
