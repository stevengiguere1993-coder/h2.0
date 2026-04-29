"""Endpoints qui reçoivent les données scrapées par l'extension navigateur.

L'extension Chrome/Edge tourne dans le vrai navigateur de l'utilisateur,
ce qui contourne les protections anti-bot (reCAPTCHA v3, Cloudflare,
Datadome) qui bloquent notre Playwright VPS.

Auth : header X-Extension-Key (token partagé set par l'admin dans
l'env var EXTENSION_API_KEY). Pas d'auth JWT user — l'extension
tourne en arrière-plan sans user session.

Flow EvalWeb :
1. User navigate sur montreal.ca/role-evaluation-fonciere/.../detail
2. Extension parse la fiche, POST /extension/evalweb-owners
3. Backend :
   - Enrichit (REQ + Canada411)
   - Persiste sur MontrealPropertyUnit.owners_json
   - Propagate vers les leads liés au matricule
4. Frontend modale h2.0 polle GET /extension/evalweb-owners/{matricule}

Flow Centris :
1. User navigate sur centris.ca/.../{mls_id}-...
2. Extension parse l'annonce, POST /extension/centris-listing
3. Backend :
   - Crée/update CentrisListing
   - Lance triage automatique → si rentable, lead créé avec tag
     "centris-interessant"
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DBSession
from app.models.centris_listing import CentrisListing
from app.models.montreal_property_unit import MontrealPropertyUnit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/extension", tags=["extension"])

# Token partagé entre l'extension et le backend. Set via env var
# EXTENSION_API_KEY. Si pas set, l'extension est désactivée
# (toutes les requêtes renvoient 401).
EXTENSION_API_KEY = os.environ.get("EXTENSION_API_KEY", "")

# Cache en mémoire process-local (TTL 10 min). Le frontend polle ici
# pour récupérer les données récentes avant de tomber sur la DB.
_owners_cache: Dict[str, Dict[str, Any]] = {}
_listings_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 600


def _check_extension_key(x_extension_key: Optional[str]) -> None:
    if not EXTENSION_API_KEY:
        raise HTTPException(
            503,
            "Extension désactivée (EXTENSION_API_KEY non configuré côté serveur)",
        )
    if x_extension_key != EXTENSION_API_KEY:
        raise HTTPException(401, "X-Extension-Key invalide")


def _cache_set(cache: Dict, key: str, value: Dict[str, Any]) -> None:
    cache[key] = {"data": value, "ts": time.time()}
    cutoff = time.time() - _CACHE_TTL_SECONDS
    expired = [k for k, v in cache.items() if v["ts"] < cutoff]
    for k in expired:
        cache.pop(k, None)


def _cache_get(cache: Dict, key: str) -> Optional[Dict[str, Any]]:
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry["ts"] > _CACHE_TTL_SECONDS:
        cache.pop(key, None)
        return None
    return entry["data"]


# =========================================================================
# Modèles
# =========================================================================


class EvalWebOwner(BaseModel):
    name: str
    statut: Optional[str] = None
    postal_address: Optional[str] = None
    inscription_date: Optional[str] = None
    conditions: Optional[str] = None


class EvalWebPayload(BaseModel):
    matricule: str = Field(min_length=10, max_length=32)
    owners: List[EvalWebOwner] = Field(default_factory=list)
    identification: Dict[str, Any] = Field(default_factory=dict)
    url: Optional[str] = None
    scraped_at: Optional[str] = None


class CentrisPayload(BaseModel):
    mls_id: str
    url: str
    address: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    nb_units: Optional[int] = None
    year_built: Optional[int] = None
    living_area: Optional[float] = None
    lot_area: Optional[float] = None
    gross_revenue: Optional[float] = None
    municipal_assessment: Optional[float] = None
    municipal_taxes: Optional[float] = None
    school_taxes: Optional[float] = None
    matricule: Optional[str] = None
    description: Optional[str] = None
    broker_name: Optional[str] = None
    broker_phone: Optional[str] = None


# =========================================================================
# Endpoints
# =========================================================================


@router.post("/ping")
async def ping(x_extension_key: Optional[str] = Header(default=None)):
    """Test de connexion. Retourne 200 si la clé est valide."""
    _check_extension_key(x_extension_key)
    return {"ok": True, "service": "h2.0 extension API"}


@router.post("/evalweb-owners")
async def receive_evalweb_owners(
    payload: EvalWebPayload,
    db: DBSession,
    x_extension_key: Optional[str] = Header(default=None),
):
    """Reçoit les owners scrapés par l'extension depuis montreal.ca.

    Enrichit (REQ + Canada411), persiste sur la unit MTL, propage
    aux leads liés.
    """
    _check_extension_key(x_extension_key)
    matricule = payload.matricule.strip()
    log.info(
        "Extension EvalWeb reçu : %s (%d owners)",
        matricule, len(payload.owners),
    )

    owners_dicts = [o.model_dump() for o in payload.owners]

    # Enrichissement REQ + Canada411 (best-effort, ne fait pas échouer
    # la requête si les services externes sont down).
    enriched = owners_dicts
    try:
        from app.services.owner_enrichment import enrich_owners as _enrich
        enriched = await _enrich(db, owners_dicts)
    except Exception as exc:
        log.warning("Enrichissement EvalWeb échoué : %s", exc)

    # Cache mémoire (pour le polling rapide depuis le frontend)
    cache_payload = {
        **payload.model_dump(),
        "owners": enriched,
    }
    _cache_set(_owners_cache, matricule, cache_payload)

    # Persiste sur la unit MTL si elle existe
    persisted = False
    try:
        result = await db.execute(
            select(MontrealPropertyUnit).where(
                MontrealPropertyUnit.matricule == matricule
            )
        )
        unit = result.scalar_one_or_none()
        if unit:
            unit.owners_json = json.dumps(enriched, ensure_ascii=False)
            unit.owners_fetched_at = datetime.now(timezone.utc)
            persisted = True
            # Propage aux leads (best-effort)
            try:
                from app.api.v1.endpoints.mtl_properties import (
                    _propagate_owners_to_lead,
                )
                await _propagate_owners_to_lead(db, matricule, enriched)
            except Exception as exc:
                log.warning(
                    "Propagation aux leads échouée : %s", exc
                )
            await db.flush()
            await db.commit()
        else:
            log.info(
                "Unit MTL pour %s n'existe pas en DB — owners cachés "
                "10 min seulement",
                matricule,
            )
    except Exception as exc:
        log.warning("Persistance unit MTL échouée : %s", exc)
        await db.rollback()

    return {
        "ok": True,
        "matricule": matricule,
        "owners_count": len(enriched),
        "persisted_to_db": persisted,
    }


@router.get("/evalweb-owners/{matricule}")
async def get_cached_owners(
    matricule: str,
    db: DBSession,
    x_extension_key: Optional[str] = Header(default=None),
):
    """Le frontend polle ici. Retourne le cache si présent, sinon
    lit la DB (owners_json de la unit MTL)."""
    _check_extension_key(x_extension_key)
    matricule = matricule.strip()

    cached = _cache_get(_owners_cache, matricule)
    if cached:
        return {**cached, "source": "cache"}

    # Fallback DB
    result = await db.execute(
        select(MontrealPropertyUnit).where(
            MontrealPropertyUnit.matricule == matricule
        )
    )
    unit = result.scalar_one_or_none()
    if unit and unit.owners_json:
        try:
            owners = json.loads(unit.owners_json)
            return {
                "matricule": matricule,
                "owners": owners,
                "source": "database",
                "fetched_at": (
                    unit.owners_fetched_at.isoformat()
                    if unit.owners_fetched_at else None
                ),
            }
        except Exception:
            pass

    raise HTTPException(404, "Pas encore scrapé pour ce matricule")


@router.post("/centris-listing")
async def receive_centris_listing(
    payload: CentrisPayload,
    db: DBSession,
    x_extension_key: Optional[str] = Header(default=None),
):
    """Reçoit une annonce Centris scrapée par l'extension.

    Crée/update CentrisListing, lance le triage automatique → si
    rentable, lead créé avec tag "centris-interessant".
    """
    _check_extension_key(x_extension_key)
    log.info(
        "Extension Centris reçu : MLS %s @ %s ($%s, %s logs)",
        payload.mls_id, payload.address, payload.price, payload.nb_units,
    )

    # Cache rapide pour pollings éventuels du frontend
    _cache_set(_listings_cache, payload.mls_id, payload.model_dump())

    # Crée ou update le CentrisListing en DB
    persisted = False
    triage_result: Optional[Dict[str, Any]] = None
    try:
        result = await db.execute(
            select(CentrisListing).where(
                CentrisListing.mls_id == payload.mls_id
            )
        )
        listing = result.scalar_one_or_none()
        is_new = listing is None

        if listing is None:
            listing = CentrisListing(mls_id=payload.mls_id)
            db.add(listing)

        # Map les champs payload → modèle DB
        listing.source_url = payload.url
        if payload.address:
            listing.address = payload.address
        if payload.price is not None:
            listing.price = payload.price
        if payload.nb_units is not None:
            listing.nb_units = payload.nb_units
        if payload.year_built is not None:
            listing.year_built = payload.year_built
        if payload.gross_revenue is not None:
            listing.revenus_annuels = payload.gross_revenue
        if payload.matricule:
            listing.matricule = payload.matricule
        if payload.broker_name:
            listing.broker_name = payload.broker_name
        if payload.broker_phone:
            listing.broker_phone = payload.broker_phone

        await db.flush()

        # Lance le triage : enrichit + lance le calculateur + crée
        # un lead si profitable. Best-effort.
        try:
            from app.services.centris_triage import triage_listing
            triage_result = await triage_listing(db, listing)
        except Exception as exc:
            log.warning(
                "Triage Centris échoué pour %s : %s",
                payload.mls_id, exc,
            )

        await db.commit()
        persisted = True
        log.info(
            "Centris %s : %s, triage=%s",
            payload.mls_id,
            "créé" if is_new else "mis à jour",
            triage_result,
        )
    except Exception as exc:
        log.warning(
            "Persistance CentrisListing échouée : %s", exc
        )
        await db.rollback()

    return {
        "ok": True,
        "mls_id": payload.mls_id,
        "persisted": persisted,
        "triage": triage_result,
    }


@router.get("/centris-listing/{mls_id}")
async def get_cached_listing(
    mls_id: str,
    x_extension_key: Optional[str] = Header(default=None),
):
    _check_extension_key(x_extension_key)
    cached = _cache_get(_listings_cache, mls_id.strip())
    if not cached:
        raise HTTPException(404, "Pas encore scrapé pour ce MLS")
    return cached
