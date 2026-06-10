"""Scraper LesPAC — annonces de location (refonte juin 2026).

LesPAC a refait son site : les anciennes URLs `/categorie/...` sont
mortes (404) et les annonces ne sont plus des liens `<a href="/annonce/...">`.
La bonne nouvelle : chaque page de catégorie embarque maintenant un JSON
complet (``var searchResponse = {...}``) avec ~24 annonces par page
(titre, description, prix, ville/quartier, date de parution, URL). On
parse donc CE JSON — plus fiable et plus poli qu'un fetch par annonce
(une seule requête par passage).

La catégorie « Immobilier > Location > Logements » couvre tout le
Québec (tri par distance autour du géo-code de l'URL) — une seule URL
suffit, le champ ``cityLabel`` permet de stocker la vraie ville.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rental_listing import RentalListing

from .parsing import (
    extract_address,
    extract_bedrooms,
    extract_inclusions,
    extract_phones,
    extract_price,
    extract_quartier,
    is_renovated,
)

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

REQUEST_DELAY_S = 2.0

# Catégorie « Location > Logements » (b457). Le géo-code g17567 centre
# le tri sur Montréal mais les résultats couvrent tout le Québec —
# cityLabel donne la vraie localisation de chaque annonce. Conservé en
# dict pour rester compatible avec l'appelant (admin_data).
CATEGORY_URLS = {
    "quebec": (
        "https://www.lespac.com/montreal/"
        "immobilier-location-logements_b457g17567k1R2.jsa"
    ),
}

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.5",
}

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

_SEARCH_RESPONSE_RE = re.compile(r"var searchResponse = (\{.*)", re.DOTALL)


def _extract_search_json(html: str) -> Optional[dict]:
    """Extrait l'objet ``searchResponse`` embarqué dans la page.

    On découpe à l'accolade équilibrée (le JSON est suivi d'autres
    scripts sur la même balise).
    """
    m = _SEARCH_RESPONSE_RE.search(html)
    if not m:
        return None
    raw = m.group(1)
    depth = 0
    for i, ch in enumerate(raw):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[: i + 1])
                except json.JSONDecodeError as exc:
                    log.warning("LesPAC : JSON embarqué illisible : %s", exc)
                    return None
    return None


def _clean_url(url: Optional[str]) -> Optional[str]:
    """URL stable (sans les paramètres de tracking) — clé de dédup."""
    if not url:
        return None
    return url.split("?")[0]


def _item_to_listing(item: dict) -> Optional[dict]:
    """Mappe un item du JSON LesPAC vers un dict prêt pour RentalListing."""
    source_url = _clean_url(item.get("listingDisplayUrl"))
    if not source_url:
        return None

    title = item.get("title") or ""
    description = item.get("description") or ""
    city_label = item.get("cityLabel") or ""
    # cityLabel : « Montréal / Centre-Sud / Centre-Ville » → ville =
    # 1er segment ; le reste aide extract_quartier.
    city_parts = [p.strip() for p in city_label.split("/") if p.strip()]
    city = city_parts[0] if city_parts else None

    text = f"{title}\n{description}\n{city_label}"

    price: Optional[float] = None
    raw_price = item.get("price")
    if raw_price not in (None, ""):
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            price = None
    if price is None:
        price = extract_price(text)

    posted_at = None
    ts = item.get("publicReleaseTimestamp")
    if ts:
        try:
            posted_at = datetime.fromtimestamp(
                int(ts) / 1000, tz=timezone.utc
            )
        except (TypeError, ValueError, OSError):
            posted_at = None

    address = extract_address(text)
    phones = extract_phones(text)
    cp_match = re.search(r"\b([HJK]\d[A-Z]\s*\d[A-Z]\d)\b", text)

    return {
        "source_url": source_url,
        "source": "lespac",
        "address": (
            f"{address['civique']} {address['nom_rue']}" if address else None
        ),
        "civique": address.get("civique") if address else None,
        "nom_rue": address.get("nom_rue") if address else None,
        "city": city,
        "postal_code": (
            cp_match.group(1).replace(" ", "") if cp_match else None
        ),
        "quartier": extract_quartier(text),
        "price": price,
        "bedrooms": extract_bedrooms(text),
        "phone": phones[0] if phones else None,
        "inclusions": extract_inclusions(text),
        "is_renovated": is_renovated(text),
        "posted_at": posted_at,
    }


async def fetch_listings(
    client: httpx.AsyncClient, category_url: str, max_pages: int = 1
) -> List[dict]:
    """Récupère les annonces (dicts mappés) depuis la/les page(s)."""
    out: List[dict] = []
    # La pagination du nouveau site passe par XHR (pas d'URL ?page=N
    # fiable) — on se contente de la première page par passage : ~24
    # annonces fraîches, le cron quotidien accumule.
    _ = max_pages
    log.info("LesPAC liste : %s", category_url)
    try:
        r = await client.get(category_url)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("LesPAC liste error : %s", exc)
        return out

    data = _extract_search_json(r.text)
    if not data:
        log.warning(
            "LesPAC : searchResponse introuvable sur %s — structure "
            "peut-être encore modifiée.",
            category_url,
        )
        return out

    for item in data.get("searchResults", []):
        mapped = _item_to_listing(item)
        if mapped:
            out.append(mapped)
    return out


async def scrape_lespac(
    db: AsyncSession,
    *,
    cities: Optional[List[str]] = None,
    max_pages_per_city: int = 1,
    max_listings_per_run: int = 50,
) -> dict:
    """Scrape LesPAC + upsert. Idempotent par source_url."""
    cities = cities or list(CATEGORY_URLS.keys())
    seen = 0
    new = 0
    updated = 0

    async with httpx.AsyncClient(
        headers=_HEADERS,
        timeout=_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for city in cities:
            cat_url = CATEGORY_URLS.get(city)
            if not cat_url:
                continue
            log.info("LesPAC : secteur=%s", city)
            listings = await fetch_listings(
                client, cat_url, max_pages=max_pages_per_city
            )
            log.info("  %d annonces dans le JSON", len(listings))

            for detail in listings[:max_listings_per_run]:
                seen += 1
                existing = (
                    await db.execute(
                        select(RentalListing).where(
                            RentalListing.source_url
                            == detail["source_url"]
                        )
                    )
                ).scalar_one_or_none()

                if existing is not None:
                    existing.last_seen_at = datetime.now(timezone.utc)
                    updated += 1
                    continue

                row = RentalListing(
                    source_url=detail["source_url"],
                    source=detail["source"],
                    address=detail.get("address"),
                    civique=detail.get("civique"),
                    nom_rue=detail.get("nom_rue"),
                    city=detail.get("city"),
                    postal_code=detail.get("postal_code"),
                    quartier=detail.get("quartier"),
                    price=detail.get("price"),
                    bedrooms=detail.get("bedrooms"),
                    phone=detail.get("phone"),
                    is_renovated=bool(detail.get("is_renovated")),
                    inclusions_json=json.dumps(
                        detail.get("inclusions") or []
                    ),
                    posted_at=detail.get("posted_at"),
                    last_seen_at=datetime.now(timezone.utc),
                )
                db.add(row)
                new += 1

            await db.flush()
            await asyncio.sleep(REQUEST_DELAY_S)

    return {
        "listings_seen": seen,
        "listings_new": new,
        "listings_updated": updated,
    }
