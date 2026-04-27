"""Endpoints d'administration pour ingérer les données externes
nécessaires au module Prospection (rôles d'évaluation municipaux,
corporations REQ).

Ces opérations sont longues (téléchargement + parsing de gros CSV) et
réservées au rôle « owner ». À déclencher manuellement depuis le
dashboard, pas en automatique au démarrage.
"""

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import DBSession, RequireOwner
from app.integrations.cmhc.rents import ingest_csv as ingest_cmhc_csv
from app.integrations.req.companies import ingest_zip as ingest_req_zip
from app.integrations.roles_evaluation.montreal import (
    MTL_CSV_URL,
    ingest_csv as ingest_montreal_csv,
)

router = APIRouter(prefix="/admin/data", tags=["admin-data"])


@router.post(
    "/mtl-roles/import",
    summary="Télécharge et ingère le CSV du rôle d'évaluation de Montréal",
)
async def import_montreal_roles(
    db: DBSession,
    _: RequireOwner,
    max_rows: Optional[int] = None,
) -> dict:
    """Long (~3-5 min en prod). Idempotent : ré-import = UPDATE.

    Optionnel: `max_rows` pour limiter (utile pour tester
    l'intégration sans attendre).
    """
    try:
        result = await ingest_montreal_csv(
            db, url=MTL_CSV_URL, max_rows=max_rows
        )
    except Exception as exc:
        raise HTTPException(
            502, f"Échec import Montréal : {exc}"
        ) from exc
    return {"source": "ville-de-montreal", **result}


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
