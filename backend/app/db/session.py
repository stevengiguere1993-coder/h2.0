"""
Database session configuration for async SQLAlchemy.

Provides:
- Async engine configuration
- Session factory
- Dependency injection for FastAPI
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


# Create async engine
# Use async_database_url to ensure postgresql+asyncpg:// format
engine = create_async_engine(
    settings.async_database_url,
    echo=settings.is_development,  # Log SQL in development
    pool_pre_ping=True,  # Verify connections before use
    pool_size=5,
    max_overflow=10,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides an async database session.

    Usage in FastAPI:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...

    Yields:
        AsyncSession: Database session that auto-closes after use
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database tables.

    Note: In production, use Alembic migrations instead.
    This is primarily for development/testing.
    """
    from app.db.base import Base
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Idempotent column additions for schema evolutions where a new
        # column is added to an already-existing table. `create_all` only
        # creates missing tables, never alters existing ones, so we patch
        # those gaps here until we introduce Alembic migrations.
        additive_columns = (
            ("sous_traitants", "competence_rating", "INTEGER"),
            ("sous_traitants", "availability_rating", "INTEGER"),
            ("sous_traitants", "punctuality_rating", "INTEGER"),
            ("sous_traitants", "quality_rating", "INTEGER"),
        )
        for table, column, col_type in additive_columns:
            await conn.execute(
                text(
                    f'ALTER TABLE {table} '
                    f'ADD COLUMN IF NOT EXISTS {column} {col_type}'
                )
            )


async def close_db() -> None:
    """
    Close database connections.

    Should be called on application shutdown.
    """
    await engine.dispose()
