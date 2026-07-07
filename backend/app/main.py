"""
Construction Management API - Main Application Entry Point

FastAPI application for Horizon Services Immobiliers.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.db.session import (
    close_db,
    ensure_critical_columns,
    ensure_immobilier_aux_tables,
    ensure_project_corrections_tables,
    ensure_raci_tables,
    ensure_relance_tables,
    ensure_role_permissions_tables,
    ensure_timesheet_tables,
    init_db,
)

logger = logging.getLogger(__name__)


async def _run_startup_tasks() -> None:
    """Travail de démarrage : créations de tables idempotentes
    (create_all), colonnes critiques, backfills et seeders.

    Exécuté EN ARRIÈRE-PLAN (cf. ``lifespan``) pour ne PAS bloquer la
    liaison du port. uvicorn lance le startup AVANT de lier le socket :
    sur un cold start Render (BDD free qui se réveille), ce travail
    dépassait le délai de scan de port → « no open ports » → déploiement
    échoué. Tout est déjà best-effort (try/except par étape).
    """
    try:
        import app.models  # noqa: F401
        await init_db()
    except Exception as exc:
        logger.warning("init_db failed during startup: %s", exc)

    # Garantit les colonnes critiques HORS de la grosse transaction
    # init_db : si une étape d'init_db échoue, toute sa transaction est
    # annulée (y compris les ADD COLUMN). Ici chaque colonne est créée
    # dans sa propre transaction → garantie même si init_db a planté.
    try:
        await ensure_critical_columns()
    except Exception as exc:
        logger.warning("ensure_critical_columns failed during startup: %s", exc)

    # Tables RACI (Distribution des tâches) — créées dans leur propre
    # transaction pour survivre à un abort d'init_db.
    try:
        await ensure_raci_tables()
    except Exception as exc:
        logger.warning("ensure_raci_tables failed during startup: %s", exc)

    # Tables auxiliaires immobilier (relances de loyer) — idem, isolées.
    try:
        await ensure_immobilier_aux_tables()
    except Exception as exc:
        logger.warning(
            "ensure_immobilier_aux_tables failed during startup: %s", exc
        )

    # Tables Feuille de temps (Gestion d'entreprise) — transaction isolée.
    try:
        await ensure_timesheet_tables()
    except Exception as exc:
        logger.warning(
            "ensure_timesheet_tables failed during startup: %s", exc
        )

    # Table Corrections/améliorations de projet (Flux A) — transaction
    # isolée. Sans ce filet la table manque en prod → 500 sur l'ajout.
    try:
        await ensure_project_corrections_tables()
    except Exception as exc:
        logger.warning(
            "ensure_project_corrections_tables failed during startup: %s", exc
        )

    # Tables du moteur de relances (cadence + plans + relances par lead) —
    # transaction isolée. Sans ce filet les tables manquent en prod → 500
    # sur l'ajout d'une relance (« Ajout échoué (HTTP 500) »).
    try:
        await ensure_relance_tables()
    except Exception as exc:
        logger.warning(
            "ensure_relance_tables failed during startup: %s", exc
        )

    # Table des permissions configurables (Paramètres → Permissions) +
    # seed des défauts (= comportement actuel). Transaction isolée.
    try:
        await ensure_role_permissions_tables()
    except Exception as exc:
        logger.warning(
            "ensure_role_permissions_tables failed during startup: %s", exc
        )

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

    # Nettoyage anti-spam rétroactif : reclasse en « spam » les demandes
    # NEUVES qui matchent les signaux (spams entrés avant le déploiement
    # du filtre ou pendant un redémarrage). Idempotent, best-effort.
    try:
        from app.db.session import AsyncSessionLocal as _SpamSession
        from app.services.contact_spam import sweep_spam_contact_requests

        async with _SpamSession() as session:
            n = await sweep_spam_contact_requests(session)
            await session.commit()
            if n:
                logger.info(
                    "Anti-spam sweep: %d demande(s) reclassée(s) en spam", n
                )
    except Exception as exc:
        logger.warning("anti-spam sweep failed: %s", exc)

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



@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lie le port IMMÉDIATEMENT et lance le travail de démarrage
    (migrations idempotentes + backfills + seeders) en ARRIÈRE-PLAN.

    Sinon, sur un cold start Render, ce travail bloque la liaison du port
    → Render ne détecte « aucun port ouvert » → le déploiement échoue.
    ``/health`` ne touche pas la BDD, donc la sonde de santé passe dès le
    bind. Filet : pendant quelques secondes après un déploiement, une
    requête pourrait tomber sur une colonne pas encore créée — négligeable
    sur une BDD déjà à jour (les migrations sont idempotentes / no-op)."""
    startup_task = asyncio.create_task(_run_startup_tasks())
    # Filets QBO AUTONOMES (aucune dépendance à un cron externe) :
    # 1ᵉʳ passage ~90 s après le boot (rattrape les factures/dépenses dont
    # le push à l'envoi a échoué en silence), puis toutes les heures.
    from app.services.qbo_nets import qbo_nets_loop

    qbo_nets_task = asyncio.create_task(qbo_nets_loop())
    try:
        yield
    finally:
        if not startup_task.done():
            startup_task.cancel()
        if not qbo_nets_task.done():
            qbo_nets_task.cancel()
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

    # ── Serveur MCP « remote » (connecteur custom Claude) ───────────
    # Montage BEST-EFFORT et TOTALEMENT ISOLÉ : tout import ou montage qui
    # échoue est loggué mais n'empêche JAMAIS le démarrage de l'app. Si ce
    # bloc lève, Kratos démarre normalement, simplement sans /mcp.
    # Le serveur MCP n'expose QUE l'activité en lecture seule, scopée à la
    # clé d'API krts_... passée dans l'URL (/mcp/{key}). Aucun lifespan ni
    # middleware global ajouté : c'est un simple APIRouter.
    try:
        from app.api.v1.endpoints.mcp_server import router as mcp_router

        # Montage direct sur l'app → URL backend : /mcp/{api_key}
        # (atteignable sur https://h2-0.onrender.com/mcp/{key}).
        app.include_router(mcp_router)
        # Montage AUSSI sous /api/v1 → URL sur le domaine propre :
        # https://immohorizon.com/api/v1/mcp/{key}. Le rewrite Next.js du
        # frontend ne proxifie QUE /api/*, donc ce second montage rend le
        # connecteur accessible via le domaine de production (plus robuste
        # côté réseau que *.onrender.com, parfois filtré par des ISP/iOS).
        app.include_router(mcp_router, prefix="/api/v1")
        logger.info(
            "MCP server mounted at /mcp/{api_key} and "
            "/api/v1/mcp/{api_key} (read-only)."
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP server mount skipped (app starts normally): %s", exc)

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
