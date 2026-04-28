"""Endpoints d'administration pour ingérer les données externes
nécessaires au module Prospection (rôles d'évaluation municipaux,
corporations REQ).

Ces opérations sont longues (téléchargement + parsing de gros CSV) et
réservées au rôle « owner ». À déclencher manuellement depuis le
dashboard, pas en automatique au démarrage.
"""

import asyncio
import logging
import os
import tempfile
import uuid
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


# Même pattern pour l'import REQ. Géré séparément du MTL pour qu'on
# puisse lancer les deux en parallèle si nécessaire.
_req_state: dict = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "rows_upserted": None,
    "error": None,
    "filename": None,
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
    summary="Lance en arrière-plan l'ingestion d'un ZIP REQ uploadé "
    "manuellement (entreprise.csv + adresse.csv optionnel)",
)
async def import_req_zip(
    _: RequireOwner,
    zip_file: UploadFile = File(...),
    max_rows: Optional[int] = Form(default=None),
) -> dict:
    """L'utilisateur télécharge le ZIP depuis donneesquebec.ca dans
    son navigateur (Cloudflare bloque le téléchargement direct côté
    serveur), puis l'envoie ici. ~1 M corporations, ZIP ~225 Mo.

    Pour éviter le timeout HTTP de 100s sur Render Free :
    - Upload streamé sur disque par chunks de 1 Mo (RAM bornée)
    - Ingestion en arrière-plan (asyncio.create_task)
    - Le client poll /req/import-status pour voir l'avancement
    """
    if _req_state["status"] == "running":
        raise HTTPException(
            409,
            "Un import REQ est déjà en cours. Attends qu'il termine "
            "ou consulte /req/import-status.",
        )
    if not (zip_file.filename or "").lower().endswith(".zip"):
        raise HTTPException(415, "Le fichier doit être un ZIP.")

    # Stream l'upload vers /tmp par chunks pour éviter de matérialiser
    # les 225 Mo en RAM. FastAPI buffer déjà sur disque pour les gros
    # uploads mais on prend pas de risque.
    temp_path = os.path.join(
        tempfile.gettempdir(), f"req-upload-{uuid.uuid4().hex}.zip"
    )
    bytes_written = 0
    try:
        with open(temp_path, "wb") as out:
            while True:
                chunk = await zip_file.read(1024 * 1024)  # 1 Mo
                if not chunk:
                    break
                out.write(chunk)
                bytes_written += len(chunk)
    except Exception as exc:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise HTTPException(
            500, f"Erreur de réception du ZIP : {exc}"
        ) from exc

    if bytes_written == 0:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise HTTPException(400, "Fichier vide.")

    # Fire-and-forget : ingestion en background.
    _req_state["filename"] = zip_file.filename
    _req_state["_task"] = asyncio.create_task(
        _req_import_worker(temp_path, max_rows)
    )
    return {
        "status": "started",
        "size_mb": round(bytes_written / 1024 / 1024, 1),
        "message": (
            "ZIP reçu, ingestion lancée en arrière-plan. Recharge la "
            "page dans 2-5 minutes ou consulte /req/import-status."
        ),
    }


async def _req_import_worker(
    temp_path: str, max_rows: Optional[int]
) -> None:
    """Tourne en background : ouvre sa propre session DB, ingère le
    ZIP depuis /tmp, puis nettoie le fichier temporaire."""
    global _req_state
    _req_state["status"] = "running"
    _req_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _req_state["finished_at"] = None
    _req_state["rows_upserted"] = None
    _req_state["error"] = None
    try:
        with open(temp_path, "rb") as fh:
            blob = fh.read()
        async with AsyncSessionLocal() as session:
            result = await ingest_req_zip(
                session, blob, max_rows=max_rows
            )
            await session.commit()
        _req_state["status"] = "done"
        _req_state["rows_upserted"] = int(
            result.get("rows_upserted") or 0
        )
    except Exception as exc:
        log.exception("REQ import failed: %s", exc)
        _req_state["status"] = "error"
        _req_state["error"] = str(exc)[:500]
    finally:
        _req_state["finished_at"] = datetime.now(timezone.utc).isoformat()
        try:
            os.unlink(temp_path)
        except OSError:
            pass


@router.get(
    "/req/import-status",
    summary="État de l'import REQ en cours ou récemment terminé",
)
async def req_import_status(_: RequireOwner) -> dict:
    return {
        k: v for k, v in _req_state.items() if not k.startswith("_")
    }


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
