"""Endpoints d'administration pour ingérer les données externes
nécessaires au module Prospection (rôles d'évaluation municipaux,
corporations REQ).

Ces opérations sont longues (téléchargement + parsing de gros CSV) et
réservées au rôle « owner ». À déclencher manuellement depuis le
dashboard, pas en automatique au démarrage.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import DBSession, RequireOwner
from app.db.session import AsyncSessionLocal
from app.integrations.cmhc.rents import ingest_csv as ingest_cmhc_csv
from app.integrations.req.companies import ingest_zip as ingest_req_zip
from app.integrations.roles_evaluation.montreal import (
    MTL_CSV_URL,
    ingest_csv as ingest_montreal_csv,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/data", tags=["admin-data"])


# État en mémoire de l'import MTL en cours. Mémorisé dans le process
# du worker FastAPI — perdu au reboot, ce qui est OK : un import qui
# tourne au moment du reboot est interrompu (Render Free a 1 worker).
# Pour un setup multi-worker, il faudrait persister dans la DB.
_mtl_state: dict = {
    "status": "idle",  # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "rows_upserted": None,
    "error": None,
}


async def _mtl_import_worker(max_rows: Optional[int]) -> None:
    """Tourne en background : ouvre sa propre session DB (la session
    de la requête HTTP est fermée dès que la réponse 202 est envoyée)."""
    global _mtl_state
    _mtl_state["status"] = "running"
    _mtl_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _mtl_state["finished_at"] = None
    _mtl_state["rows_upserted"] = None
    _mtl_state["error"] = None
    try:
        async with AsyncSessionLocal() as session:
            result = await ingest_montreal_csv(
                session, url=MTL_CSV_URL, max_rows=max_rows
            )
            await session.commit()
        _mtl_state["status"] = "done"
        _mtl_state["rows_upserted"] = int(result.get("rows_upserted") or 0)
    except Exception as exc:
        log.exception("mtl import failed: %s", exc)
        _mtl_state["status"] = "error"
        _mtl_state["error"] = str(exc)[:500]
    finally:
        _mtl_state["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.post(
    "/mtl-roles/import",
    summary="Lance en arrière-plan le téléchargement + ingestion du "
    "CSV du rôle d'évaluation de Montréal",
)
async def import_montreal_roles(
    _: RequireOwner,
    max_rows: Optional[int] = None,
) -> dict:
    """Long (~3-5 min en prod, 150-200 Mo). Render Free coupe les
    requêtes HTTP à 100s, donc on lance le travail en background et
    on retourne immédiatement. L'utilisateur poll
    /mtl-roles/import-status pour voir l'avancement.

    Idempotent : ré-import = UPDATE (matricule = clé primaire).
    """
    if _mtl_state["status"] == "running":
        raise HTTPException(
            409,
            "Un import MTL est déjà en cours. Attends qu'il termine "
            "ou consulte /mtl-roles/import-status.",
        )
    # Fire-and-forget : la coroutine survit au cycle de vie de la
    # requête HTTP. On stocke la tâche pour que le GC ne la réclame pas.
    _mtl_state["_task"] = asyncio.create_task(
        _mtl_import_worker(max_rows)
    )
    return {
        "status": "started",
        "message": (
            "Import lancé en arrière-plan. Recharge la page dans "
            "3-5 minutes ou consulte /mtl-roles/import-status."
        ),
    }


@router.get(
    "/mtl-roles/import-status",
    summary="État de l'import MTL en cours ou récemment terminé",
)
async def mtl_import_status(_: RequireOwner) -> dict:
    return {
        k: v for k, v in _mtl_state.items() if not k.startswith("_")
    }


@router.post(
    "/req/import",
    summary="Ingère un ZIP REQ uploadé manuellement (entreprise.csv "
    "+ adresse.csv optionnel)",
)
async def import_req_zip(
    db: DBSession,
    _: RequireOwner,
    zip_file: UploadFile = File(...),
    max_rows: Optional[int] = Form(default=None),
) -> dict:
    """L'utilisateur télécharge le ZIP depuis donneesquebec.ca dans
    son navigateur (Cloudflare bloque le téléchargement direct côté
    serveur), puis l'envoie ici. ~1 M corporations.
    """
    if not (zip_file.filename or "").lower().endswith(".zip"):
        raise HTTPException(415, "Le fichier doit être un ZIP.")
    blob = await zip_file.read()
    if not blob:
        raise HTTPException(400, "Fichier vide.")
    try:
        result = await ingest_req_zip(db, blob, max_rows=max_rows)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            500, f"Échec ingestion ZIP REQ : {exc}"
        ) from exc
    return {"source": "req", **result}


@router.post(
    "/cmhc/import",
    summary="Ingère un CSV SCHL/CMHC (loyers moyens par zone et "
    "nombre de chambres). Long ou wide format accepté.",
)
async def import_cmhc_csv(
    db: DBSession,
    _: RequireOwner,
    csv_file: UploadFile = File(...),
    default_year: Optional[int] = Form(default=None),
) -> dict:
    """Le portail SCHL HMIP-PIMH exporte des CSV en plusieurs formats
    selon les filtres choisis. Cet endpoint accepte les deux formats
    courants (long = une ligne par bracket, wide = une colonne par
    bracket).
    """
    if not (csv_file.filename or "").lower().endswith(".csv"):
        raise HTTPException(415, "Le fichier doit être un CSV.")
    blob = await csv_file.read()
    if not blob:
        raise HTTPException(400, "Fichier vide.")
    try:
        result = await ingest_cmhc_csv(
            db, blob, default_year=default_year
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            500, f"Échec ingestion CSV SCHL : {exc}"
        ) from exc
    return {"source": "cmhc", **result}


@router.post(
    "/init-db",
    summary="Force-run init_db() (migrations additives + create_all). "
    "Utile si Render n'a pas restart proprement après un deploy.",
)
async def force_init_db(_: RequireOwner) -> dict:
    """init_db() est idempotent : create_all ne crée que les tables
    manquantes, et ADD COLUMN IF NOT EXISTS ne fait rien si la colonne
    existe déjà."""
    from app.db.session import init_db

    try:
        await init_db()
    except Exception as exc:
        raise HTTPException(
            500, f"init_db a échoué : {exc}"
        ) from exc
    return {"ok": True}
