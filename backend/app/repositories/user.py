"""
User Repository for database operations.

Handles all database interactions for User model.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.schemas.user import UserCreate


class UserRepository:
    """
    Repository for User database operations.

    Provides methods for CRUD operations and authentication-related queries.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize repository with database session.

        Args:
            db: Async database session
        """
        self.db = db

    async def get_by_id(self, user_id: int) -> Optional[User]:
        """
        Get a user by ID.

        Args:
            user_id: The user's primary key

        Returns:
            User if found, None otherwise
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        """
        Get a user by email address.

        Args:
            email: The user's email address

        Returns:
            User if found, None otherwise
        """
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def create(self, user_data: UserCreate) -> User:
        """
        Create a new user.

        Args:
            user_data: User creation data including email and password

        Returns:
            The created User instance
        """
        # Determine the final role. If caller passed `role` explicitly,
        # that wins. Otherwise we fall back to: admin if is_admin,
        # employee otherwise. Also keep the legacy is_admin flag in
        # sync so any old code paths still work.
        role = getattr(user_data, "role", None)
        if not role:
            role = "admin" if user_data.is_admin else "employee"
        is_admin = user_data.is_admin or role in ("owner", "admin")

        user = User(
            email=user_data.email,
            hashed_password=get_password_hash(user_data.password),
            is_admin=is_admin,
            role=role,
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def authenticate(
        self, email: str, password: str
    ) -> Optional[User]:
        """
        Authenticate a user by email and password.

        Args:
            email: The user's email address
            password: The plain text password to verify

        Returns:
            User if credentials are valid, None otherwise
        """
        user = await self.get_by_email(email)
        if user is None:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    async def is_active(self, user: User) -> bool:
        """
        Check if a user account is active.

        Args:
            user: The user to check

        Returns:
            True if active, False otherwise
        """
        return user.is_active

    async def update_password(
        self, user: User, new_password: str
    ) -> User:
        """
        Update a user's password.

        Args:
            user: The user to update
            new_password: The new plain text password

        Returns:
            The updated User instance
        """
        user.hashed_password = get_password_hash(new_password)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def set_active(self, user: User, is_active: bool) -> User:
        """
        Set a user's active status.

        Args:
            user: The user to update
            is_active: The new active status

        Returns:
            The updated User instance
        """
        user.is_active = is_active
        await self.db.flush()
        await self.db.refresh(user)
        return user
