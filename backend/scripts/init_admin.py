#!/usr/bin/env python3
"""
Initialize admin user from environment variables.

This script is designed to run during deployment (e.g., on Render).
It will create an admin user only if no admin exists yet.

Usage:
    python -m scripts.init_admin

Environment variables:
    - DATABASE_URL (required)
    - JWT_SECRET (required)
    - ADMIN_EMAIL (required for admin creation)
    - ADMIN_PASSWORD (required for admin creation)
"""

import asyncio
import os
import sys

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal
from app.models.user import User


async def init_admin(db: AsyncSession) -> None:
    """Initialize admin user from environment variables."""
    # Check if admin already exists
    result = await db.execute(
        select(User).where(User.is_admin == True)  # noqa: E712
    )
    if result.scalar_one_or_none():
        print("Admin user already exists. Skipping initialization.")
        return

    # Get credentials from environment
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")

    if not email or not password:
        print("ADMIN_EMAIL and ADMIN_PASSWORD not set. Skipping admin creation.")
        print("Set these environment variables to create an admin on first deploy.")
        return

    if len(password) < 8:
        print("Error: ADMIN_PASSWORD must be at least 8 characters")
        return

    # Check if email already exists
    result = await db.execute(
        select(User).where(User.email == email)
    )
    if result.scalar_one_or_none():
        print(f"User with email '{email}' already exists. Skipping.")
        return

    # Create admin
    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        is_active=True,
        is_admin=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    print(f"Admin user created: {email}")


async def main() -> None:
    """Main entry point."""
    async with AsyncSessionLocal() as db:
        await init_admin(db)


if __name__ == "__main__":
    asyncio.run(main())
