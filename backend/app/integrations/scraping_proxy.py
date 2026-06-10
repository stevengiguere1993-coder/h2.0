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

# L'URL du VPS n'est pas un secret — on fournit un fallback par défaut
# pour que le lien fonctionne même si la var d'env n'est pas déclarée
# dans le dashboard Render. La clé, elle, reste sans défaut (secret).
VPS_URL = os.environ.get(
    "SCRAPING_VPS_URL", "https://scraper.immohorizon.com"
).rstrip("/")
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


async def scrape_numeriq_comparables(
    *,
    nom_rue: Optional[str] = None,
    municipalite: Optional[str] = None,
    region: Optional[str] = None,
    limit: int = 50,
) -> Optional[List[dict]]:
    """Appelle le VPS pour scraper les comparables de vente (journal
    des ventes Numériq) pour un secteur donné.

    Retourne la liste de dicts comparables, ou None si le VPS n'est
    pas configuré. Toute réponse non-200 (404/500/502) renvoie une
    liste vide : l'endpoint /scrape/numeriq-comparables n'existe
    peut-être pas encore côté VPS, et un scrape qui échoue ne doit
    JAMAIS faire planter la recherche (le cache + le manuel suffisent).
    """
    if not vps_available():
        return None
    url = f"{VPS_URL}/scrape/numeriq-comparables"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                url,
                headers=_headers(),
                json={
                    "nom_rue": nom_rue,
                    "municipalite": municipalite,
                    "region": region,
                    "limit": limit,
                },
            )
            if r.status_code != 200:
                log.warning(
                    "VPS numeriq-comparables returned %s for %s/%s: %s",
                    r.status_code,
                    municipalite,
                    nom_rue,
                    r.text[:200],
                )
                return []
            return r.json().get("comparables", [])
    except Exception as exc:  # noqa: BLE001
        # Réseau KO / VPS down / JSON invalide — on ne fait jamais
        # planter la recherche : le cache + le manuel répondent.
        log.warning(
            "VPS numeriq-comparables failed for %s/%s: %s",
            municipalite,
            nom_rue,
            exc,
        )
        return []


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


async def get_vps_health() -> Optional[dict]:
    """Retourne le JSON complet du ``/health`` du VPS, ou ``None`` si
    injoignable.

    Contient au minimum ``ok`` et ``browser_connected`` ; les images
    récentes exposent aussi ``numeriq_configured`` (présence des
    identifiants QUB là où le scraper de comparables se connecte). Permet
    au backend de bâtir un statut « source auto » fidèle à la réalité.
    """
    if not VPS_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            r = await client.get(f"{VPS_URL}/health")
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, dict) else None
    except Exception:
        return None
