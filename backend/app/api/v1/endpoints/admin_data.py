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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from pydantic import BaseModel, Field

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
    "/mtl-roles/purge",
    summary="Supprime toutes les unités d'évaluation MTL "
    "(region='mtl-island' OU NULL). À utiliser avant un import "
    "provincial qui inclut MTL pour éviter les doublons (formats "
    "de matricule différents entre feed VdM et MAMH).",
)
async def purge_mtl_data(_: RequireOwner) -> dict:
    """Retry x4 sur 'recovery mode' / 'connection closed' (Postgres
    Render peut être temporairement indisponible juste après un
    redéploiement)."""
    import asyncio
    from sqlalchemy import delete, or_, select, func
    from app.models.montreal_property_unit import MontrealPropertyUnit

    last_err: Optional[Exception] = None
    for attempt in range(4):
        try:
            async with AsyncSessionLocal() as db:
                count_before = (
                    await db.execute(
                        select(func.count())
                        .select_from(MontrealPropertyUnit)
                        .where(
                            or_(
                                MontrealPropertyUnit.region == "mtl-island",
                                MontrealPropertyUnit.region.is_(None),
                            )
                        )
                    )
                ).scalar() or 0
                await db.execute(
                    delete(MontrealPropertyUnit).where(
                        or_(
                            MontrealPropertyUnit.region == "mtl-island",
                            MontrealPropertyUnit.region.is_(None),
                        )
                    )
                )
                await db.commit()
                return {
                    "deleted": int(count_before),
                    "message": (
                        f"{int(count_before):,} unités MTL supprimées. "
                        "Tu peux maintenant importer le ZIP provincial."
                    ).replace(",", " "),
                }
        except Exception as exc:
            msg = str(exc).lower()
            transient = (
                "recovery mode" in msg
                or "connection" in msg
                and ("closed" in msg or "does not exist" in msg)
            )
            if not transient:
                raise
            last_err = exc
            log.warning(
                "Purge MTL transient error (attempt %d/4): %s",
                attempt + 1,
                exc,
            )
            await asyncio.sleep(3 * (attempt + 1))
    raise HTTPException(
        503,
        "Base de données indisponible (recovery mode). "
        f"Réessaie dans 30 secondes. Détail : {last_err}",
    )


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


# === Import provincial (Rive-Sud / Rive-Nord / Laval) ===
#
# Le rôle d'évaluation provincial est ~3-5 GB compressé. Comme le
# REQ ZIP, on utilise l'upload chunked du browser pour bypasser la
# limite proxy. L'ingestion filtre par région (liste de villes).

_provincial_state: dict = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "rows_processed": None,
    "rows_upserted": None,
    "region": None,
    "error": None,
}

_PROVINCIAL_UPLOADS_DIR = os.path.join(
    tempfile.gettempdir(), "provincial-uploads"
)


@router.post(
    "/provincial/upload-chunk",
    summary="Reçoit un chunk d'upload du CSV provincial.",
)
async def provincial_upload_chunk(
    _: RequireOwner,
    upload_id: str = Form(...),
    chunk_idx: int = Form(...),
    total_chunks: int = Form(...),
    chunk: UploadFile = File(...),
) -> dict:
    if not upload_id or not all(c.isalnum() or c == "-" for c in upload_id):
        raise HTTPException(400, "upload_id invalide.")
    if chunk_idx < 0 or chunk_idx >= total_chunks:
        raise HTTPException(400, "chunk_idx hors borne.")

    upload_dir = os.path.join(_PROVINCIAL_UPLOADS_DIR, upload_id)
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


async def _provincial_ingest_worker(
    final_path: str, region: str, max_rows: Optional[int]
) -> None:
    global _provincial_state
    _provincial_state["status"] = "running"
    _provincial_state["started_at"] = datetime.now(
        timezone.utc
    ).isoformat()
    _provincial_state["finished_at"] = None
    _provincial_state["error"] = None
    _provincial_state["region"] = region
    try:
        from app.integrations.roles_evaluation.quebec_regional import (
            ingest_provincial_csv,
        )

        async with AsyncSessionLocal() as session:
            result = await ingest_provincial_csv(
                session,
                final_path,
                region=region,
                max_rows=max_rows,
            )
            await session.commit()
        _provincial_state["status"] = "done"
        _provincial_state["rows_processed"] = int(
            result.get("rows_processed") or 0
        )
        _provincial_state["rows_upserted"] = int(
            result.get("rows_upserted") or 0
        )
        _provincial_state["diagnostics"] = result.get("diagnostics") or []
    except Exception as exc:
        log.exception("provincial ingest failed: %s", exc)
        _provincial_state["status"] = "error"
        _provincial_state["error"] = str(exc)[:500]
    finally:
        _provincial_state["finished_at"] = datetime.now(
            timezone.utc
        ).isoformat()
        try:
            os.unlink(final_path)
        except OSError:
            pass


@router.post(
    "/provincial/reset",
    summary="Force le state du worker provincial à idle (déblocage manuel).",
)
async def provincial_reset(_: RequireOwner) -> dict:
    """Reset l'état en mémoire du worker. Utile si un import est resté
    bloqué sur 'running' après un crash ou un redéploiement. NE TUE PAS
    le worker en cours s'il existe — celui-ci est tué naturellement par
    le redémarrage du process Render."""
    _provincial_state["status"] = "idle"
    _provincial_state["error"] = None
    return {"status": "idle", "message": "État réinitialisé."}


@router.get(
    "/provincial/import-status",
    summary="État de l'import provincial en cours / dernier terminé.",
)
async def provincial_import_status(_: RequireOwner) -> dict:
    return {
        "status": _provincial_state.get("status", "idle"),
        "started_at": _provincial_state.get("started_at"),
        "finished_at": _provincial_state.get("finished_at"),
        "rows_processed": _provincial_state.get("rows_processed"),
        "rows_upserted": _provincial_state.get("rows_upserted"),
        "region": _provincial_state.get("region"),
        "error": _provincial_state.get("error"),
        "diagnostics": _provincial_state.get("diagnostics") or [],
    }


@router.post(
    "/provincial/upload-finalize",
    summary="Réassemble les chunks reçus et lance l'ingest filtré "
    "par région (rive-sud, laval, rive-nord).",
)
async def provincial_upload_finalize(
    _: RequireOwner,
    upload_id: str = Form(...),
    total_chunks: int = Form(...),
    region: str = Form(
        default="quebec",
        pattern="^(quebec|rive-sud|laval|rive-nord)$",
    ),
    max_rows: Optional[int] = Form(default=None),
) -> dict:
    if _provincial_state["status"] == "running":
        raise HTTPException(
            409, "Un import provincial est déjà en cours."
        )
    upload_dir = os.path.join(_PROVINCIAL_UPLOADS_DIR, upload_id)
    if not os.path.isdir(upload_dir):
        raise HTTPException(404, "upload_id inconnu.")

    received = sorted(os.listdir(upload_dir))
    if len(received) != total_chunks:
        raise HTTPException(
            400,
            f"Chunks manquants : reçu {len(received)} / {total_chunks}.",
        )

    final_path = os.path.join(
        tempfile.gettempdir(), f"provincial-{upload_id}.csv"
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
    finally:
        try:
            for name in received:
                os.unlink(os.path.join(upload_dir, name))
            os.rmdir(upload_dir)
        except OSError:
            pass

    _provincial_state["_task"] = asyncio.create_task(
        _provincial_ingest_worker(final_path, region, max_rows)
    )
    return {
        "status": "started",
        "size_mb": round(total_size / 1024 / 1024, 1),
        "region": region,
    }


@router.get(
    "/provincial/import-status",
    summary="État de l'import provincial en cours ou terminé.",
)
async def provincial_import_status(_: RequireOwner) -> dict:
    return {
        k: v for k, v in _provincial_state.items() if not k.startswith("_")
    }


_centris_state: dict = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "new": None,
    "updated": None,
    "blocked": False,
    "error": None,
}


async def _centris_scrape_worker(category: str, max_pages: int) -> None:
    global _centris_state
    _centris_state["status"] = "running"
    _centris_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _centris_state["finished_at"] = None
    _centris_state["error"] = None
    _centris_state["blocked"] = False
    total_new = 0
    total_updated = 0
    try:
        from app.integrations.centris.scraper import (
            CentrisBlocked,
            SEARCH_URLS,
            parse_listings_html,
            try_fetch_search,
            upsert_listings,
        )

        if category not in SEARCH_URLS:
            raise ValueError(f"Catégorie inconnue : {category}")

        async with AsyncSessionLocal() as session:
            for page in range(1, max_pages + 1):
                try:
                    html = await try_fetch_search(
                        SEARCH_URLS[category], page=page
                    )
                except CentrisBlocked as exc:
                    _centris_state["blocked"] = True
                    _centris_state["error"] = str(exc)
                    break
                listings = parse_listings_html(html)
                if not listings:
                    log.warning(
                        "Centris : page %d vide (parsing failed?)",
                        page,
                    )
                    break
                r = await upsert_listings(session, listings, category)
                total_new += r["new"]
                total_updated += r["updated"]
                await session.commit()

        _centris_state["status"] = (
            "blocked"
            if _centris_state["blocked"]
            else "done"
        )
        _centris_state["new"] = total_new
        _centris_state["updated"] = total_updated

        # Triage auto pour les annonces fraîchement ingérées
        if total_new > 0:
            from app.services.centris_triage import (
                triage_recent_listings,
            )

            try:
                async with AsyncSessionLocal() as session:
                    await triage_recent_listings(
                        session, since_hours=2
                    )
            except Exception as exc:
                log.exception(
                    "Triage post-scrape failed: %s", exc
                )
    except Exception as exc:
        log.exception("Centris scrape failed: %s", exc)
        _centris_state["status"] = "error"
        _centris_state["error"] = str(exc)[:500]
    finally:
        _centris_state["finished_at"] = datetime.now(
            timezone.utc
        ).isoformat()


@router.post(
    "/centris/scrape",
    summary="Lance un scrape Centris (multi-logements à vendre) en "
    "background. Si bloqué par Cloudflare, le status retourne "
    "'blocked' et il faut basculer sur le mode manuel paste.",
)
async def scrape_centris(
    _: RequireOwner,
    category: str = "multiplex_2_5",
    max_pages: int = 2,
) -> dict:
    if _centris_state["status"] == "running":
        raise HTTPException(409, "Un scrape Centris est déjà en cours.")
    _centris_state["_task"] = asyncio.create_task(
        _centris_scrape_worker(category, max_pages)
    )
    return {"status": "started", "category": category}


@router.get("/centris/scrape-status")
async def centris_scrape_status(_: RequireOwner) -> dict:
    return {k: v for k, v in _centris_state.items() if not k.startswith("_")}


class CentrisManualPaste(BaseModel):
    html: str = Field(min_length=100, max_length=2_000_000)
    category: str = Field(
        default="multiplex_2_5",
        pattern="^(multiplex_2_5|immeuble_residentiel_6_plus)$",
    )


@router.post(
    "/centris/manual-paste",
    summary="Fallback : l'utilisateur copie le HTML d'une page Centris "
    "(ouvert dans son navigateur où il est passé Cloudflare) et le "
    "colle ici. On parse comme si c'était venu du scrape direct + "
    "triage auto qui crée des leads pour les annonces rentables.",
)
async def centris_manual_paste(
    body: CentrisManualPaste,
    db: DBSession,
    _: RequireOwner,
) -> dict:
    from app.integrations.centris.scraper import (
        parse_listings_html,
        upsert_listings,
    )
    from app.services.centris_triage import triage_recent_listings

    listings = parse_listings_html(body.html)
    if not listings:
        raise HTTPException(
            400,
            "Aucune annonce détectée dans le HTML collé. Vérifie "
            "que tu as bien copié une page de résultats Centris "
            "(view-source ou clic droit → Voir le code source).",
        )
    result = await upsert_listings(db, listings, body.category)
    await db.commit()

    # Triage auto : pour chaque annonce qui vient d'être ajoutée,
    # on tente de calculer la rentabilité et créer un lead si
    # APH50 ou SCHL gain ≥ 0.
    triage = await triage_recent_listings(db, since_hours=2)
    return {
        "parsed": len(listings),
        **result,
        "triage": triage,
    }


@router.post(
    "/centris/triage-recent",
    summary="Lance le triage auto sur les annonces Centris des N "
    "dernières heures. Crée des leads pour celles dont APH50 ou "
    "SCHL gain ≥ 0 (MDF récupérable via refi).",
)
async def centris_triage_recent(
    db: DBSession,
    _: RequireOwner,
    since_hours: int = 48,
) -> dict:
    from app.services.centris_triage import triage_recent_listings

    return await triage_recent_listings(db, since_hours=since_hours)


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
