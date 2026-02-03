"""
Authentication Service for business logic.

Handles authentication operations including login, registration,
and token management.
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.token import Token
from app.schemas.user import UserCreate


class AuthService:
    """
    Service for authentication operations.

    Provides high-level authentication methods that coordinate
    between repositories and security utilities.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize service with database session.

        Args:
            db: Async database session
        """
        self.db = db
        self.user_repo = UserRepository(db)

    async def login(
        self, email: str, password: str
    ) -> Optional[Token]:
        """
        Authenticate user and generate access token.

        Args:
            email: User's email address
            password: User's plain text password

        Returns:
            Token if authentication successful, None otherwise
        """
        user = await self.user_repo.authenticate(email, password)
        if user is None:
            return None

        if not user.is_active:
            return None

        access_token = create_access_token(
            subject=str(user.id),
            additional_claims={
                "email": user.email,
                "is_admin": user.is_admin,
            },
        )

        return Token(access_token=access_token)

    async def register(
        self, user_data: UserCreate
    ) -> Optional[User]:
        """
        Register a new user.

        Args:
            user_data: User creation data

        Returns:
            Created User if successful, None if email already exists
        """
        existing_user = await self.user_repo.get_by_email(user_data.email)
        if existing_user is not None:
            return None

        user = await self.user_repo.create(user_data)
        return user

    async def get_current_user(self, user_id: int) -> Optional[User]:
        """
        Get current user by ID.

        Args:
            user_id: User's primary key

        Returns:
            User if found and active, None otherwise
        """
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            return None

        if not user.is_active:
            return None

        return user
