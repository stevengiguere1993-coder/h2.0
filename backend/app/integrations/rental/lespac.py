"""Scraper LesPAC — annonces de location.

LesPAC = pendant francophone québécois de Kijiji. Catégories :
- « Logements à louer » > région

URL pattern : `https://www.lespac.com/categorie/immobilier/location/<region>`

Comme Kijiji, c'est du HTML server-side, anti-bot modéré. Délai
entre requêtes pour rester poli.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rental_listing import RentalListing

from .parsing import (
    extract_address,
    extract_bedrooms,
    extract_phones,
    extract_price,
)

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

REQUEST_DELAY_S = 2.5

# URLs catégories par région LesPAC. Si la structure change, ajuster.
CATEGORY_URLS = {
    "montreal": "https://www.lespac.com/categorie/immobilier/location/montreal-region",
    "laval": "https://www.lespac.com/categorie/immobilier/location/laval-region",
    "rive-sud": "https://www.lespac.com/categorie/immobilier/location/monteregie-region",
    "rive-nord": "https://www.lespac.com/categorie/immobilier/location/laurentides-region",
}

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.5",
}

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


async def fetch_listing_urls(
    client: httpx.AsyncClient, category_url: str, max_pages: int = 1
) -> List[str]:
    """Récupère les URLs d'annonces depuis une page de catégorie LesPAC.

    LesPAC affiche les liens annonces en `<a href="/annonce/...">`.
    """
    all_urls: List[str] = []
    for page in range(1, max_pages + 1):
        url = (
            category_url
            if page == 1
            else f"{category_url}?page={page}"
        )
        log.info("LesPAC liste : %s", url)
        try:
            r = await client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("LesPAC liste error : %s", exc)
            break

        soup = BeautifulSoup(r.text, "html.parser")
        seen: set[str] = set()
        for a in soup.select("a[href*='/annonce/']"):
            href = a.get("href")
            if not href or not isinstance(href, str):
                continue
            full = (
                href if href.startswith("http")
                else f"https://www.lespac.com{href}"
            )
            if full in seen:
                continue
            seen.add(full)
            all_urls.append(full)

        if not seen:
            log.warning(
                "LesPAC : aucun lien d'annonce trouvé sur %s",
                url,
            )
            break

        await asyncio.sleep(REQUEST_DELAY_S)

    return all_urls


async def fetch_listing_detail(
    client: httpx.AsyncClient, url: str
) -> Optional[dict]:
    """Fetch + parse une annonce LesPAC. Retourne None si l'annonce
    n'est plus accessible."""
    try:
        r = await client.get(url)
        if r.status_code in (404, 410):
            return None
        r.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("LesPAC détail error %s : %s", url, exc)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    phones = extract_phones(text)
    bedrooms = extract_bedrooms(text)
    price = extract_price(text)
    address = extract_address(text)

    cp_match = re.search(r"\b([HJK]\d[A-Z]\s*\d[A-Z]\d)\b", text)
    postal = cp_match.group(1).replace(" ", "") if cp_match else None

    return {
        "source_url": url,
        "source": "lespac",
        "address": (
            f"{address['civique']} {address['nom_rue']}"
            if address
            else None
        ),
        "civique": address.get("civique") if address else None,
        "nom_rue": address.get("nom_rue") if address else None,
        "postal_code": postal,
        "price": price,
        "bedrooms": bedrooms,
        "phone": phones[0] if phones else None,
    }


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
            log.info("LesPAC : ville=%s", city)
            urls = await fetch_listing_urls(
                client, cat_url, max_pages=max_pages_per_city
            )
            log.info("  %d URLs trouvées", len(urls))
            for url in urls[:max_listings_per_run]:
                seen += 1
                existing = (
                    await db.execute(
                        select(RentalListing).where(
                            RentalListing.source_url == url
                        )
                    )
                ).scalar_one_or_none()

                if existing is not None:
                    existing.last_seen_at = datetime.now(timezone.utc)
                    updated += 1
                    continue

                detail = await fetch_listing_detail(client, url)
                await asyncio.sleep(REQUEST_DELAY_S)

                if detail is None:
                    continue

                row = RentalListing(
                    source_url=detail["source_url"],
                    source=detail["source"],
                    address=detail.get("address"),
                    civique=detail.get("civique"),
                    nom_rue=detail.get("nom_rue"),
                    postal_code=detail.get("postal_code"),
                    price=detail.get("price"),
                    bedrooms=detail.get("bedrooms"),
                    phone=detail.get("phone"),
                    last_seen_at=datetime.now(timezone.utc),
                )
                db.add(row)
                new += 1

            await db.flush()

    return {
        "listings_seen": seen,
        "listings_new": new,
        "listings_updated": updated,
    }
