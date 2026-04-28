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


# === Chunked upload (bypasse la limite ~100 Mo du proxy Render) ===
#
# Le navigateur découpe le ZIP en chunks de 10 Mo via Blob.slice() et
# POST chaque chunk à /upload-chunk. Quand tous les chunks sont reçus,
# le client appelle /upload-finalize qui réassemble + kick off
# l'ingestion en background.

_REQ_UPLOADS_DIR = os.path.join(tempfile.gettempdir(), "req-chunked-uploads")


@router.post(
    "/req/upload-chunk",
    summary="Reçoit un chunk d'un upload chunked. Écrit sur disque sans "
    "tout charger en RAM.",
)
async def req_upload_chunk(
    _: RequireOwner,
    upload_id: str = Form(...),
    chunk_idx: int = Form(...),
    total_chunks: int = Form(...),
    chunk: UploadFile = File(...),
) -> dict:
    if not upload_id or not all(c.isalnum() or c == "-" for c in upload_id):
        raise HTTPException(
            400, "upload_id invalide (alphanum + tirets seulement)."
        )
    if chunk_idx < 0 or chunk_idx >= total_chunks:
        raise HTTPException(
            400, f"chunk_idx hors borne (0..{total_chunks - 1})."
        )

    upload_dir = os.path.join(_REQ_UPLOADS_DIR, upload_id)
    os.makedirs(upload_dir, exist_ok=True)
    chunk_path = os.path.join(upload_dir, f"chunk-{chunk_idx:06d}")

    bytes_written = 0
    try:
        with open(chunk_path, "wb") as out:
            while True:
                buf = await chunk.read(1024 * 1024)
                if not buf:
                    break
                out.write(buf)
                bytes_written += len(buf)
    except Exception as exc:
        try:
            os.unlink(chunk_path)
        except OSError:
            pass
        raise HTTPException(
            500, f"Erreur écriture chunk : {exc}"
        ) from exc

    return {
        "upload_id": upload_id,
        "chunk_idx": chunk_idx,
        "size": bytes_written,
        "received_chunks": len(os.listdir(upload_dir)),
        "total_chunks": total_chunks,
    }


@router.post(
    "/req/upload-finalize",
    summary="Réassemble les chunks reçus et lance l'ingestion REQ en "
    "background.",
)
async def req_upload_finalize(
    _: RequireOwner,
    upload_id: str = Form(...),
    total_chunks: int = Form(...),
    filename: Optional[str] = Form(default=None),
) -> dict:
    if _req_state["status"] == "running":
        raise HTTPException(
            409,
            "Un import REQ est déjà en cours. Attends qu'il termine.",
        )
    upload_dir = os.path.join(_REQ_UPLOADS_DIR, upload_id)
    if not os.path.isdir(upload_dir):
        raise HTTPException(404, "upload_id inconnu.")

    received = sorted(os.listdir(upload_dir))
    if len(received) != total_chunks:
        raise HTTPException(
            400,
            f"Chunks manquants : reçu {len(received)} / {total_chunks}.",
        )

    # Réassemble dans un seul fichier .zip dans /tmp.
    final_path = os.path.join(
        tempfile.gettempdir(), f"req-{upload_id}.zip"
    )
    total_size = 0
    try:
        with open(final_path, "wb") as out:
            for name in received:
                with open(
                    os.path.join(upload_dir, name), "rb"
                ) as src:
                    while True:
                        buf = src.read(1024 * 1024)
                        if not buf:
                            break
                        out.write(buf)
                        total_size += len(buf)
    except Exception as exc:
        raise HTTPException(
            500, f"Erreur réassemblage : {exc}"
        ) from exc
    finally:
        # Nettoyage des chunks individuels — on a tout dans final_path.
        try:
            for name in received:
                os.unlink(os.path.join(upload_dir, name))
            os.rmdir(upload_dir)
        except OSError:
            pass

    _req_state["filename"] = filename or f"chunked-upload-{upload_id}.zip"
    _req_state["_task"] = asyncio.create_task(
        _req_import_worker(final_path, None)
    )
    return {
        "status": "started",
        "size_mb": round(total_size / 1024 / 1024, 1),
        "message": (
            "Réassemblage terminé, ingestion lancée en arrière-plan. "
            "Poll /req/import-status pour le suivi."
        ),
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


# === Scraping annonces de location (Kijiji) ===
#
# État en mémoire similaire à MTL/REQ. Scraping lancé en background
# pour éviter le timeout HTTP, polling pour le suivi.

_rental_state: dict = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "listings_seen": None,
    "listings_new": None,
    "listings_updated": None,
    "error": None,
    "source": None,
}


async def _kijiji_scrape_worker(
    cities: Optional[list], max_pages: int, max_listings: int
) -> None:
    global _rental_state
    _rental_state["status"] = "running"
    _rental_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _rental_state["finished_at"] = None
    _rental_state["error"] = None
    _rental_state["source"] = "kijiji"
    try:
        from app.integrations.rental.kijiji import scrape_kijiji

        async with AsyncSessionLocal() as session:
            result = await scrape_kijiji(
                session,
                cities=cities,
                max_pages_per_city=max_pages,
                max_listings_per_run=max_listings,
            )
            await session.commit()
        _rental_state["status"] = "done"
        _rental_state["listings_seen"] = result.get("listings_seen", 0)
        _rental_state["listings_new"] = result.get("listings_new", 0)
        _rental_state["listings_updated"] = result.get(
            "listings_updated", 0
        )
    except Exception as exc:
        log.exception("kijiji scrape failed: %s", exc)
        _rental_state["status"] = "error"
        _rental_state["error"] = str(exc)[:500]
    finally:
        _rental_state["finished_at"] = datetime.now(
            timezone.utc
        ).isoformat()


@router.post(
    "/rental/scrape-kijiji",
    summary="Lance en arrière-plan un scrape Kijiji des annonces de "
    "location (par ville). Idempotent : déduplication par source_url.",
)
async def scrape_kijiji_endpoint(
    _: RequireOwner,
    cities: Optional[list[str]] = None,
    max_pages_per_city: int = 1,
    max_listings_per_run: int = 50,
) -> dict:
    if _rental_state["status"] == "running":
        raise HTTPException(
            409,
            "Un scrape est déjà en cours. Attends qu'il termine ou "
            "consulte /rental/scrape-status.",
        )
    _rental_state["_task"] = asyncio.create_task(
        _kijiji_scrape_worker(
            cities, max_pages_per_city, max_listings_per_run
        )
    )
    return {
        "status": "started",
        "message": (
            "Scrape Kijiji lancé en arrière-plan. ~5-10 min selon "
            "le nombre de villes/pages. Poll /rental/scrape-status."
        ),
    }


async def _lespac_scrape_worker(
    cities: Optional[list], max_pages: int, max_listings: int
) -> None:
    global _rental_state
    _rental_state["status"] = "running"
    _rental_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _rental_state["finished_at"] = None
    _rental_state["error"] = None
    _rental_state["source"] = "lespac"
    try:
        from app.integrations.rental.lespac import scrape_lespac

        async with AsyncSessionLocal() as session:
            result = await scrape_lespac(
                session,
                cities=cities,
                max_pages_per_city=max_pages,
                max_listings_per_run=max_listings,
            )
            await session.commit()
        _rental_state["status"] = "done"
        _rental_state["listings_seen"] = result.get("listings_seen", 0)
        _rental_state["listings_new"] = result.get("listings_new", 0)
        _rental_state["listings_updated"] = result.get(
            "listings_updated", 0
        )
    except Exception as exc:
        log.exception("lespac scrape failed: %s", exc)
        _rental_state["status"] = "error"
        _rental_state["error"] = str(exc)[:500]
    finally:
        _rental_state["finished_at"] = datetime.now(
            timezone.utc
        ).isoformat()


async def _both_scrape_worker(max_pages: int, max_listings: int) -> None:
    """Scrape Kijiji puis LesPAC en séquence — 1 seul état partagé."""
    global _rental_state
    _rental_state["status"] = "running"
    _rental_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _rental_state["finished_at"] = None
    _rental_state["error"] = None
    _rental_state["source"] = "kijiji+lespac"
    seen = new = updated = 0
    try:
        from app.integrations.rental.kijiji import scrape_kijiji
        from app.integrations.rental.lespac import scrape_lespac

        async with AsyncSessionLocal() as session:
            r1 = await scrape_kijiji(
                session,
                max_pages_per_city=max_pages,
                max_listings_per_run=max_listings,
            )
            await session.commit()
            seen += r1.get("listings_seen", 0)
            new += r1.get("listings_new", 0)
            updated += r1.get("listings_updated", 0)

            r2 = await scrape_lespac(
                session,
                max_pages_per_city=max_pages,
                max_listings_per_run=max_listings,
            )
            await session.commit()
            seen += r2.get("listings_seen", 0)
            new += r2.get("listings_new", 0)
            updated += r2.get("listings_updated", 0)

        _rental_state["status"] = "done"
        _rental_state["listings_seen"] = seen
        _rental_state["listings_new"] = new
        _rental_state["listings_updated"] = updated
    except Exception as exc:
        log.exception("rental scrape (both) failed: %s", exc)
        _rental_state["status"] = "error"
        _rental_state["error"] = str(exc)[:500]
    finally:
        _rental_state["finished_at"] = datetime.now(
            timezone.utc
        ).isoformat()


@router.post(
    "/rental/scrape-lespac",
    summary="Scrape LesPAC en background (même pattern que Kijiji).",
)
async def scrape_lespac_endpoint(
    _: RequireOwner,
    cities: Optional[list[str]] = None,
    max_pages_per_city: int = 1,
    max_listings_per_run: int = 50,
) -> dict:
    if _rental_state["status"] == "running":
        raise HTTPException(409, "Un scrape est déjà en cours.")
    _rental_state["_task"] = asyncio.create_task(
        _lespac_scrape_worker(
            cities, max_pages_per_city, max_listings_per_run
        )
    )
    return {"status": "started", "message": "Scrape LesPAC lancé."}


@router.post(
    "/rental/scrape-all",
    summary="Lance Kijiji + LesPAC en séquence en background. "
    "Bouton « Mise à jour comparables » côté UI.",
)
async def scrape_all_endpoint(
    _: RequireOwner,
    max_pages_per_city: int = 1,
    max_listings_per_run: int = 50,
) -> dict:
    if _rental_state["status"] == "running":
        raise HTTPException(409, "Un scrape est déjà en cours.")
    _rental_state["_task"] = asyncio.create_task(
        _both_scrape_worker(max_pages_per_city, max_listings_per_run)
    )
    return {
        "status": "started",
        "message": (
            "Scrape Kijiji + LesPAC lancé. ~10-20 min total. "
            "Poll /rental/scrape-status."
        ),
    }


@router.get(
    "/rental/scrape-status",
    summary="État du dernier scrape de location en cours ou terminé.",
)
async def rental_scrape_status(_: RequireOwner) -> dict:
    return {
        k: v for k, v in _rental_state.items() if not k.startswith("_")
    }


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
