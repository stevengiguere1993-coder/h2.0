"""Client HTTP vers le service de scraping externe (VPS Hetzner).

Quand `SCRAPING_VPS_URL` est défini en env, on délègue les scrapes
qui demandent un vrai navigateur (EvalWeb, Centris) au VPS qui a
Playwright installé.

Si la var d'env n'est pas définie, les fonctions retournent None
pour permettre au caller de fallback sur la logique httpx direct
(scrapers locaux best-effort).
"""

from __future__ import annotations

import logging
import os
from typing import Any, List, Optional

import httpx

log = logging.getLogger(__name__)

VPS_URL = os.environ.get("SCRAPING_VPS_URL", "").rstrip("/")
VPS_KEY = os.environ.get("SCRAPING_VPS_KEY", "")

# Timeout généreux pour Playwright (le flow EvalWeb 4 étapes peut
# prendre 15-25s, Centris pareil).
_TIMEOUT = httpx.Timeout(45.0, connect=10.0)


def vps_available() -> bool:
    """True si le VPS est configuré (URL + clé). Si False, le caller
    doit fallback sur les scrapers httpx locaux."""
    return bool(VPS_URL and VPS_KEY)


def _headers() -> dict:
    return {
        "X-API-Key": VPS_KEY,
        "Content-Type": "application/json",
    }


async def scrape_evalweb_owners(matricule: str) -> Optional[List[dict]]:
    """Appelle le VPS pour scraper les propriétaires d'un matricule.

    Retourne la liste de dicts owners, ou None si le VPS n'est pas
    configuré, ou lève si erreur réseau / 5xx.
    """
    if not vps_available():
        return None
    url = f"{VPS_URL}/scrape/evalweb-owners"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            url,
            headers=_headers(),
            json={"matricule": matricule},
        )
        if r.status_code == 502:
            # VPS a essayé mais a échoué (ex: site down) — on renvoie
            # une liste vide pour que le caller puisse fallback.
            log.warning(
                "VPS scraping returned 502 for matricule %s: %s",
                matricule,
                r.text[:200],
            )
            return []
        r.raise_for_status()
        data = r.json()
        return data.get("owners", [])


async def scrape_centris_search(
    *,
    category: str = "multiplex_2_5",
    region: Optional[str] = None,
    max_pages: int = 2,
) -> Optional[List[dict]]:
    """Appelle le VPS pour scraper la liste Centris."""
    if not vps_available():
        return None
    url = f"{VPS_URL}/scrape/centris-search"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            url,
            headers=_headers(),
            json={
                "category": category,
                "region": region,
                "max_pages": max_pages,
            },
        )
        r.raise_for_status()
        return r.json().get("listings", [])


async def scrape_centris_detail(listing_url: str) -> Optional[dict]:
    """Scrape une page de détail Centris."""
    if not vps_available():
        return None
    url = f"{VPS_URL}/scrape/centris-detail"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            url,
            headers=_headers(),
            json={"url": listing_url},
        )
        r.raise_for_status()
        return r.json()


async def is_vps_healthy() -> bool:
    """Health check vers le VPS. Utilisé par le diagnostics endpoint."""
    if not VPS_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            r = await client.get(f"{VPS_URL}/health")
            return r.status_code == 200 and r.json().get("ok") is True
    except Exception:
        return False
