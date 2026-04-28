"""Scraper Centris : tentative HTTP + parser HTML.

URL pattern de recherche multi-logements :
- Multiplex 2-5 unités : `/fr/multiplex~immeuble-residentiel-a-vendre`
- Immeuble résidentiel 6+ : pareil avec filtre #units
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Endpoints search list pour différentes catégories. La pagination se
# fait via `?page=N`. Région par défaut : Province de Québec, mais on
# peut filtrer par grande ville.
SEARCH_URLS = {
    "multiplex_2_5": (
        "https://www.centris.ca/fr/multiplex~immeuble-residentiel-a-vendre"
    ),
    "immeuble_residentiel_6_plus": (
        "https://www.centris.ca/fr/immeuble-residentiel-a-vendre"
    ),
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class CentrisBlocked(Exception):
    """Cloudflare/Datadome a bloqué la requête. Le user doit
    fallback sur le mode manuel (paste HTML)."""


async def try_fetch_search(
    url: str, page: int = 1
) -> str:
    """Tente de fetch une page de résultats Centris en HTTP direct.

    Retourne le HTML si succès. Lève `CentrisBlocked` si la page
    est un challenge Cloudflare (typiquement HTML <1500 bytes ou
    titre « Just a moment »).
    """
    page_url = url if page <= 1 else f"{url}?uc=1&page={page}"
    async with httpx.AsyncClient(
        headers=_HEADERS,
        timeout=_TIMEOUT,
        follow_redirects=True,
    ) as client:
        r = await client.get(page_url)
        if r.status_code == 403:
            raise CentrisBlocked(
                "403 Forbidden — Cloudflare actif. Bascule sur le "
                "mode manuel (paste HTML)."
            )
        r.raise_for_status()
        body = r.text
        if (
            len(body) < 2000
            or "Just a moment" in body
            or "challenge-platform" in body
        ):
            raise CentrisBlocked(
                "Page Centris remplacée par un challenge anti-bot. "
                "Utilise le mode manuel."
            )
        return body


# ============== Parser HTML ==============


# Nombre d'unités : « 4 logement(s) », « 3 plex », « Bloc 6 logements »
_UNITS_RE = re.compile(
    r"(\d+)\s*(?:logements?|unités?|appartements?|plex)",
    re.IGNORECASE,
)
# Année construction
_YEAR_RE = re.compile(r"(?:Année|Built)[\s:]*\b(\d{4})\b")
# Prix : « 1 250 000 $ »
_PRICE_RE = re.compile(
    r"(\d{1,3}(?:[\s,]\d{3})+|\d{4,8})\s*\$"
)
# MLS : 8 chiffres, parfois préfixé
_MLS_RE = re.compile(r"\b(\d{8})\b")
# Code postal
_POSTAL_RE = re.compile(r"\b([HJK]\d[A-Z]\s*\d[A-Z]\d)\b")
# Adresse civique « 4520 boul. Saint-Laurent »
_ADDR_RE = re.compile(
    r"(\d{1,5})\s*[-–]?\s*(\d{0,5})?[\s,]+"
    r"(?:rue|boul|boulevard|av|avenue|ch|chemin|place|route|rang|terrasse|côte)"
    r"\.?\s+([A-ZÀÂÉÊËÎÔÙÛÜÇ][\w\-\s'.àâéêëîïôùûüç]{2,80}?)"
    r"(?=,|\s+(?:H\d|Montr|Laval|Longueuil|Brossard|qc|québec)|$)",
    re.IGNORECASE,
)


def _parse_price(s: str) -> Optional[float]:
    if not s:
        return None
    m = _PRICE_RE.search(s)
    if not m:
        return None
    raw = m.group(1).replace(" ", "").replace(",", "")
    try:
        n = int(raw)
    except ValueError:
        return None
    if 50_000 <= n <= 50_000_000:
        return float(n)
    return None


def _parse_units(s: str) -> Optional[int]:
    if not s:
        return None
    m = _UNITS_RE.search(s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _parse_year(s: str) -> Optional[int]:
    if not s:
        return None
    m = _YEAR_RE.search(s)
    if not m:
        return None
    try:
        y = int(m.group(1))
        if 1800 <= y <= datetime.now().year + 1:
            return y
    except ValueError:
        pass
    return None


def _parse_address(s: str) -> Optional[dict]:
    m = _ADDR_RE.search(s or "")
    if not m:
        return None
    return {
        "civique": m.group(1).strip(),
        "nom_rue": m.group(3).strip(),
    }


def parse_listings_html(html: str) -> List[dict]:
    """Parse une page de résultats Centris. Tolère les variantes
    de structure HTML (Centris change régulièrement).

    Stratégie :
    1. Cherche le bloc JSON `__NEXT_DATA__` ou `window.__APOLLO_STATE__`
       (Centris est une SPA Next.js).
    2. Fallback : parse les cards HTML par sélecteur.
    """
    soup = BeautifulSoup(html, "html.parser")
    listings: List[dict] = []

    # 1) Tente extraction JSON depuis Next.js
    next_data_tag = soup.find(
        "script", id="__NEXT_DATA__", type="application/json"
    )
    if next_data_tag and next_data_tag.string:
        try:
            data = json.loads(next_data_tag.string)
            extracted = _extract_from_next_data(data)
            if extracted:
                return extracted
        except Exception as exc:
            log.debug("Centris __NEXT_DATA__ parse failed: %s", exc)

    # 2) Fallback : cards HTML directes
    cards = soup.select(
        "[itemtype*='Product'], .property-thumbnail-item, "
        ".thumbnailItem, article.cac"
    )
    for card in cards[:50]:
        listing = _parse_card(card)
        if listing and listing.get("source_url"):
            listings.append(listing)

    return listings


def _extract_from_next_data(data: dict) -> List[dict]:
    """Tente d'extraire les annonces depuis le payload Next.js.
    Format historique : data.props.pageProps.searchResults.results."""
    listings: List[dict] = []
    try:
        props = data.get("props", {}).get("pageProps", {}) or {}
        results = (
            props.get("searchResults", {}).get("results")
            or props.get("results")
            or []
        )
        for item in results:
            mls = (
                item.get("mlsNumber")
                or item.get("mls")
                or item.get("MlsNumber")
            )
            url_path = (
                item.get("url")
                or item.get("uri")
                or item.get("link")
                or ""
            )
            if not url_path:
                continue
            full_url = (
                url_path
                if url_path.startswith("http")
                else f"https://www.centris.ca{url_path}"
            )
            address = (
                item.get("address")
                or item.get("display_address")
                or item.get("Address")
                or ""
            )
            price_raw = (
                item.get("price")
                or item.get("Price")
                or item.get("priceFormatted")
                or ""
            )
            price = (
                float(price_raw)
                if isinstance(price_raw, (int, float))
                else _parse_price(str(price_raw))
            )
            nb = item.get("nbUnits") or item.get("UnitsCount")
            try:
                nb_units = int(nb) if nb else None
            except (TypeError, ValueError):
                nb_units = None

            listings.append(
                {
                    "mls_id": str(mls) if mls else None,
                    "source_url": full_url,
                    "address": address or None,
                    "price": price,
                    "nb_units": nb_units,
                    "year_built": item.get("yearBuilt"),
                    "city": item.get("city"),
                }
            )
    except Exception as exc:
        log.debug("Centris next_data extraction error: %s", exc)
    return listings


def _parse_card(card) -> Optional[dict]:
    """Parse une card de résultat HTML (fallback quand pas de
    __NEXT_DATA__). Sélecteurs basés sur le markup Centris d'avril 2026."""
    text = card.get_text(" ", strip=True)
    if not text:
        return None

    # URL vers le détail
    a = card.find("a", href=True)
    href = a.get("href") if a else None
    full_url = None
    if href:
        full_url = (
            href if href.startswith("http")
            else f"https://www.centris.ca{href}"
        )

    mls_match = _MLS_RE.search(text)
    addr = _parse_address(text)
    postal_m = _POSTAL_RE.search(text)

    return {
        "source_url": full_url,
        "mls_id": mls_match.group(1) if mls_match else None,
        "address": (
            f"{addr['civique']} {addr['nom_rue']}"
            if addr
            else None
        ),
        "civique": addr.get("civique") if addr else None,
        "nom_rue": addr.get("nom_rue") if addr else None,
        "postal_code": (
            postal_m.group(1).replace(" ", "") if postal_m else None
        ),
        "price": _parse_price(text),
        "nb_units": _parse_units(text),
        "year_built": _parse_year(text),
    }


# ============== Persistence helper ==============


async def upsert_listings(
    db, listings: List[dict], category: str
) -> dict:
    """Upsert une liste d'annonces parsées dans `centris_listings`.
    Idempotent par source_url.

    Match les leads existants par matricule pour mettre à jour
    automatiquement leur prix demandé (Centris).
    """
    from sqlalchemy import select

    from app.models.centris_listing import CentrisListing

    new = 0
    updated = 0
    now = datetime.now(timezone.utc)

    for L in listings:
        url = L.get("source_url")
        if not url:
            continue
        existing = (
            await db.execute(
                select(CentrisListing).where(
                    CentrisListing.source_url == url
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.last_seen_at = now
            if L.get("price"):
                existing.price = L["price"]
            updated += 1
            continue

        row = CentrisListing(
            mls_id=L.get("mls_id"),
            source_url=url,
            category=category,
            address=L.get("address"),
            civique=L.get("civique"),
            nom_rue=L.get("nom_rue"),
            city=L.get("city"),
            postal_code=L.get("postal_code"),
            price=L.get("price"),
            nb_units=L.get("nb_units"),
            year_built=L.get("year_built"),
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(row)
        new += 1

    await db.flush()
    return {"new": new, "updated": updated, "total": len(listings)}
