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
3. Backend cache par matricule (10 min TTL) + persiste sur la unit
4. Frontend modale h2.0 polle GET /extension/evalweb-owners/{matricule}
5. Modale affiche les owners scrapés automatiquement

Flow Centris :
1. User navigate sur centris.ca/.../{mls_id}-...
2. Extension parse l'annonce, POST /extension/centris-listing
3. Backend cache + crée/update le CentrisListing en DB
4. Triage automatique → si profitable, lead créé avec tag "centris-interessant"
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/extension", tags=["extension"])

# Token partagé entre l'extension et le backend. Set via env var
# EXTENSION_API_KEY. Si pas set, l'extension est désactivée
# (toutes les requêtes renvoient 401).
EXTENSION_API_KEY = os.environ.get("EXTENSION_API_KEY", "")

# Cache en mémoire process-local. Pour multi-process / multi-pod il
# faudrait Redis, mais le free Render n'a pas de Redis et ce cache
# est juste une optimisation : si le cache miss, on lit la DB.
_owners_cache: Dict[str, Dict[str, Any]] = {}
_listings_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 600  # 10 min


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
    # Garbage collect entries plus vieilles que TTL
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
    x_extension_key: Optional[str] = Header(default=None),
):
    """Reçoit les owners scrapés par l'extension depuis montreal.ca.

    Stocke en cache + persiste sur la unit MTL si elle existe.
    """
    _check_extension_key(x_extension_key)
    matricule = payload.matricule.strip()
    log.info(
        "Extension EvalWeb reçu : %s (%d owners)",
        matricule, len(payload.owners),
    )
    _cache_set(_owners_cache, matricule, payload.model_dump())
    # TODO : persister sur la unit MTL si elle existe (futur PR)
    return {
        "ok": True,
        "matricule": matricule,
        "owners_count": len(payload.owners),
    }


@router.get("/evalweb-owners/{matricule}")
async def get_cached_owners(
    matricule: str,
    x_extension_key: Optional[str] = Header(default=None),
):
    """Le frontend polle ici pour récupérer les owners scrapés."""
    _check_extension_key(x_extension_key)
    cached = _cache_get(_owners_cache, matricule.strip())
    if not cached:
        raise HTTPException(404, "Pas encore scrapé pour ce matricule")
    return cached


@router.post("/centris-listing")
async def receive_centris_listing(
    payload: CentrisPayload,
    x_extension_key: Optional[str] = Header(default=None),
):
    """Reçoit une annonce Centris scrapée par l'extension."""
    _check_extension_key(x_extension_key)
    log.info(
        "Extension Centris reçu : MLS %s @ %s ($%s, %s logs)",
        payload.mls_id, payload.address, payload.price, payload.nb_units,
    )
    _cache_set(_listings_cache, payload.mls_id, payload.model_dump())
    # TODO : créer/update CentrisListing + lancer triage automatique
    return {"ok": True, "mls_id": payload.mls_id}


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
