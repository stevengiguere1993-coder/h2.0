"""
Construction Management API - Main Application Entry Point

FastAPI application for construction company management.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.db.session import close_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.

    Handles startup and shutdown events.
    """
    # Startup
    yield
    # Shutdown
    await close_db()


def create_application() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance
    """
    app = FastAPI(
        title="Construction Management API",
        description="API pour la gestion d'entreprise de construction",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS middleware configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routers
    app.include_router(api_router, prefix="/api/v1")

    return app


# Create application instance
app = create_application()


@app.get("/", tags=["root"])
async def root() -> dict:
    """
    Root endpoint - Welcome message.

    Returns basic API information.
    """
    return {
        "message": "Construction Management API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """
    Health check endpoint.

    Used by Render and other services to verify the API is running.
    """
    return {
        "status": "healthy",
        "environment": settings.env,
    }
