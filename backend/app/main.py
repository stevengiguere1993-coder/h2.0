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

    # Backfill : crée le projet (+ facture d'acompte DRAFT) pour les
    # soumissions ACCEPTED qui n'en ont pas encore. Rattrape les
    # acceptations antérieures à l'auto-création (PR #45). Best-effort,
    # silencieux en cas d'échec — le service tourne quand même.
    try:
        from app.api.v1.endpoints.soumission_to_project import (
            backfill_accepted_soumissions,
        )
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            n = await backfill_accepted_soumissions(session)
            if n:
                logger.info(
                    "Startup backfill: %d project(s) created from "
                    "previously-accepted soumissions",
                    n,
                )
    except Exception as exc:
        logger.warning("backfill_accepted_soumissions failed: %s", exc)

    # Drive Conventions — seeder idempotent. Crée les 4 conventions
    # par défaut (Deal Pipeline, DevlogClient, DevlogProject,
    # ConstructionProject) si elles n'existent pas encore en BDD.
    # Toutes inactives par défaut, Phil les active une à une après
    # configuration du parent_folder_drive_id. Best-effort silencieux.
    try:
        from app.db.session import AsyncSessionLocal as _DriveSeedSession
        from app.services.drive_conventions_seed import (
            seed_default_drive_conventions,
        )

        async with _DriveSeedSession() as session:
            n = await seed_default_drive_conventions(session)
            if n:
                logger.info(
                    "Drive conventions seed: %d convention(s) creee(s)",
                    n,
                )
    except Exception as exc:
        logger.warning("drive_conventions seed failed: %s", exc)

    # Drive Page Modules — seeder idempotent Phase 7. Crée une ligne
    # inactive par type de page (ProspectionDeal, DevlogClient, ...) si
    # absente. Phil active chaque section Drive via /parametres/drive.
    # Best-effort silencieux.
    try:
        from app.db.session import AsyncSessionLocal as _DrivePageSeedSession
        from app.services.drive_page_modules_seed import (
            seed_default_drive_page_modules,
        )

        async with _DrivePageSeedSession() as session:
            n = await seed_default_drive_page_modules(session)
            if n:
                logger.info(
                    "Drive page modules seed: %d module(s) cree(s)",
                    n,
                )
    except Exception as exc:
        logger.warning("drive_page_modules seed failed: %s", exc)

    # Drive Auto-Upload — seeder idempotent Phase 6. Crée 5 règles
    # "document généré → sous-dossier Drive de l'entité" inactives par
    # défaut (fiche d'analyse, offre PPTX, NDA signé, soumission,
    # facture). Phil active chaque règle via /parametres/drive après
    # vérification. Best-effort silencieux.
    try:
        from app.db.session import AsyncSessionLocal as _DriveAutoUploadSession
        from app.services.drive_auto_upload_seed import (
            seed_default_drive_auto_uploads,
        )

        async with _DriveAutoUploadSession() as session:
            n = await seed_default_drive_auto_uploads(session)
            if n:
                logger.info(
                    "Drive auto-uploads seed: %d regle(s) creee(s)",
                    n,
                )
    except Exception as exc:
        logger.warning("drive_auto_uploads seed failed: %s", exc)

    # Téléphonie — auto-bootstrap Twilio : si les credentials et le
    # numéro sont configurés en env, on s'assure que la ligne existe en
    # DB et que le webhook URL pointe sur ce backend. Idempotent ;
    # fast-path < 5 ms quand déjà bootstrapé (juste un SELECT).
    try:
        from app.scripts.twilio_bootstrap import bootstrap_twilio

        rc = await bootstrap_twilio()
        if rc == 0:
            logger.info("Twilio bootstrap OK")
    except Exception as exc:
        logger.warning("twilio bootstrap failed: %s", exc)

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
        # Le regex couvre les preview Render, localhost et l'origin
        # `chrome-extension://...` utilisé par l'extension navigateur
        # Horizon h2.0 (qui POST sur /api/v1/extension/*).
        allow_origin_regex=(
            r"^https://[a-z0-9-]+\.onrender\.com$|"
            r"^http://localhost(:\d+)?$|"
            r"^chrome-extension://[a-z]+$"
        ),
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

