"""
Admin bootstrap — create the first admin user.

Usage (Render Shell):
    ADMIN_EMAIL=steven@example.com ADMIN_PASSWORD='ChangeMe!2026' \
      python -m app.scripts.create_admin

Idempotent: if a user already exists with the given email, the script
will upgrade the account to admin rather than create a duplicate.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal, close_db, init_db
from app.models.user import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("create_admin")


async def run() -> int:
    email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD") or ""
    if not email or not password:
        log.error("ADMIN_EMAIL and ADMIN_PASSWORD must be set")
        return 1
    if len(password) < 10:
        log.error("Admin password must be at least 10 characters")
        return 1

    await init_db()

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if existing:
            existing.is_admin = True
            existing.is_active = True
            existing.hashed_password = get_password_hash(password)
            log.info("Admin upgraded / password reset: %s", email)
        else:
            user = User(
                email=email,
                hashed_password=get_password_hash(password),
                is_active=True,
                is_admin=True,
            )
            session.add(user)
            log.info("Admin created: %s", email)

        await session.commit()
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    finally:
        try:
            asyncio.run(close_db())
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
