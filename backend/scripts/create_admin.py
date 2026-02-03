#!/usr/bin/env python3
"""
Script to create the first admin user.

Usage:
    python -m scripts.create_admin

Environment variables required:
    - DATABASE_URL
    - JWT_SECRET
"""

import asyncio
import os
import sys

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from getpass import getpass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal
from app.models.user import User


async def create_admin(
    email: str,
    password: str,
    db: AsyncSession,
) -> User:
    """Create an admin user."""
    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        is_active=True,
        is_admin=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def check_existing_admin(db: AsyncSession) -> bool:
    """Check if an admin user already exists."""
    result = await db.execute(
        select(User).where(User.is_admin == True)  # noqa: E712
    )
    return result.scalar_one_or_none() is not None


async def main() -> None:
    """Main entry point."""
    print("=" * 50)
    print("  CREATE FIRST ADMIN USER")
    print("=" * 50)
    print()

    async with AsyncSessionLocal() as db:
        # Check if admin already exists
        if await check_existing_admin(db):
            print("An admin user already exists.")
            print("Use the API to create additional users.")
            return

        # Get email
        email = input("Email: ").strip()
        if not email:
            print("Error: Email is required")
            return

        # Check if email exists
        result = await db.execute(
            select(User).where(User.email == email)
        )
        if result.scalar_one_or_none():
            print(f"Error: User with email '{email}' already exists")
            return

        # Get password
        password = getpass("Password (min 8 chars): ")
        if len(password) < 8:
            print("Error: Password must be at least 8 characters")
            return

        password_confirm = getpass("Confirm password: ")
        if password != password_confirm:
            print("Error: Passwords do not match")
            return

        # Create admin
        try:
            user = await create_admin(email, password, db)
            print()
            print("=" * 50)
            print("  ADMIN CREATED SUCCESSFULLY")
            print("=" * 50)
            print(f"  ID:    {user.id}")
            print(f"  Email: {user.email}")
            print(f"  Admin: {user.is_admin}")
            print("=" * 50)
        except Exception as e:
            print(f"Error creating admin: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())
