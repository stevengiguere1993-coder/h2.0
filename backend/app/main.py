"""
Construction Management API - Main Application Entry Point

FastAPI application for Horizon Services Immobiliers.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.db.session import close_db, init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.

    On startup, run a best-effort idempotent table creation
    (create_all only creates tables that don't exist — never drops
    or alters existing ones). Real schema changes will be shipped
    via Alembic once we introduce a baseline migration.
    """
    try:
        import app.models  # noqa: F401
        await init_db()
    except Exception as exc:
        logger.warning("init_db failed during startup: %s", exc)

    yield
    await close_db()


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Horizon Services Immobiliers API",
        description="API publique et interne pour Horizon Services Immobiliers.",
        version="0.2.1",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS — allow the production domains, plus localhost for dev,
    # plus any *.onrender.com preview URL so the Render-assigned
    # temporary domain for h2-0-web can reach the API during setup.
    allowed_origins: list[str] = []
    if settings.is_development:
        allowed_origins = ["*"]
    else:
        raw = getattr(settings, "frontend_origins", "") or ""
        allowed_origins = [o.strip() for o in raw.split(",") if o.strip()]
        if not allowed_origins:
            allowed_origins = [
                "https://immohorizon.com",
                "https://www.immohorizon.com",
                "https://immohorizon.ca",
                "https://www.immohorizon.ca",
            ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=r"^https://[a-z0-9-]+\.onrender\.com$|^http://localhost(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_application()


@app.get("/", tags=["root"])
async def root() -> dict:
    return {
        "message": "Horizon Services Immobiliers API",
        "version": "0.2.1",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "healthy", "environment": settings.env}


@app.get("/api/v1/ping", tags=["health"])
async def api_ping() -> dict:
    """Alias under /api/v1 so uptime monitors pinging a single URL
    (e.g. immohorizon.com/api/v1/ping via the Next.js rewrite) wake up
    both the frontend (which serves /api/*) and the backend (this
    handler). Cheap: no DB, no I/O."""
    return {"status": "ok"}
