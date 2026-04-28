"""Scraper Kijiji — annonces de location.

Stratégie en 2 niveaux :
1. **Liste** : on scrape la page de catégorie « Apartments and condos
   for rent » filtrée par ville (Montréal, Laval, Longueuil…). On
   récupère les URLs des nouvelles annonces du jour.
2. **Détail** : pour chaque URL, on fetch la page complète, on extrait
   prix / chambres / adresse / téléphone via regex sur le texte plat.

Pas d'API officielle, pas de session/login requis. Anti-bot Kijiji
est modéré — on respecte un délai de 2-3s entre requêtes pour rester
en dessous des seuils.

⚠ ToS Kijiji interdit techniquement le scraping automatisé. Risques :
ban IP (rare à petit volume), notification cease-and-desist (très
rare pour usage non-commercial). À utiliser de manière respectueuse :
volume raisonnable + User-Agent honnête.
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

# Délai entre 2 requêtes vers Kijiji (politesse + évite le ban).
REQUEST_DELAY_S = 2.5

# URLs de catégorie par grande ville. Les codes proviennent de Kijiji
# (l1700281 = Grand Montréal, etc.).
CATEGORY_URLS = {
    "grand-montreal": "https://www.kijiji.ca/b-appartement-condo-louer/grand-montreal/c37l1700281",
    "laval": "https://www.kijiji.ca/b-appartement-condo-louer/laval/c37l1700277",
    "longueuil": "https://www.kijiji.ca/b-appartement-condo-louer/longueuil-rive-sud/c37l1700278",
    "rive-nord": "https://www.kijiji.ca/b-appartement-condo-louer/laurentides/c37l1700375",
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
    """Récupère les URLs d'annonces depuis une page de catégorie.

    Kijiji rend les liens en HTML server-side (pas de JS requis).
    Pattern actuel : `<a class="title" href="/v-...">…</a>` ou
    `data-listing-id` sur certains éléments.
    """
    all_urls: List[str] = []
    for page in range(1, max_pages + 1):
        url = (
            category_url
            if page == 1
            else f"{category_url}/page-{page}"
        )
        log.info("Kijiji liste : %s", url)
        try:
            r = await client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Kijiji liste error : %s", exc)
            break

        soup = BeautifulSoup(r.text, "html.parser")
        # Patterns possibles : <a class="title …" href="/v-..."> OU
        # <a data-listing-id="123" href="/v-...">. On prend tout lien
        # qui commence par /v-.
        seen: set[str] = set()
        for a in soup.select("a[href^='/v-']"):
            href = a.get("href")
            if not href or not isinstance(href, str):
                continue
            full = (
                href if href.startswith("http")
                else f"https://www.kijiji.ca{href}"
            )
            if full in seen:
                continue
            seen.add(full)
            all_urls.append(full)

        if not seen:
            log.warning(
                "Kijiji : aucun lien d'annonce trouvé sur %s — "
                "structure HTML peut-être modifiée.",
                url,
            )
            break

        # Politesse : pause avant la page suivante.
        await asyncio.sleep(REQUEST_DELAY_S)

    return all_urls


async def fetch_listing_detail(
    client: httpx.AsyncClient, url: str
) -> Optional[dict]:
    """Fetch + parse une annonce détaillée. Retourne un dict avec
    les champs extraits, ou None si l'annonce n'est plus accessible
    (404, 410…)."""
    try:
        r = await client.get(url)
        if r.status_code in (404, 410):
            return None
        r.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Kijiji détail error %s : %s", url, exc)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    # Texte plat de la page entière — les regex de parsing.py se
    # débrouillent à partir de là.
    text = soup.get_text(" ", strip=True)

    phones = extract_phones(text)
    bedrooms = extract_bedrooms(text)
    price = extract_price(text)
    address = extract_address(text)
    quartier = extract_quartier(text)
    inclusions = extract_inclusions(text)
    renovated = is_renovated(text)

    # Code postal canadien dans le texte
    cp_match = re.search(r"\b([HJK]\d[A-Z]\s*\d[A-Z]\d)\b", text)
    postal = cp_match.group(1).replace(" ", "") if cp_match else None

    return {
        "source_url": url,
        "source": "kijiji",
        "address": (
            f"{address['civique']} {address['nom_rue']}"
            if address
            else None
        ),
        "civique": address.get("civique") if address else None,
        "nom_rue": address.get("nom_rue") if address else None,
        "postal_code": postal,
        "quartier": quartier,
        "price": price,
        "bedrooms": bedrooms,
        "phone": phones[0] if phones else None,
        "inclusions": inclusions,
        "is_renovated": renovated,
    }


async def scrape_kijiji(
    db: AsyncSession,
    *,
    cities: Optional[List[str]] = None,
    max_pages_per_city: int = 1,
    max_listings_per_run: int = 50,
) -> dict:
    """Scrape Kijiji et upsert dans `rental_listings`. Idempotent :
    on déduplique par `source_url`.

    Retourne un résumé { listings_seen, listings_new, listings_updated }.
    """
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
            log.info("Kijiji : ville=%s", city)
            urls = await fetch_listing_urls(
                client, cat_url, max_pages=max_pages_per_city
            )
            log.info("  %d URLs trouvées", len(urls))
            for url in urls[:max_listings_per_run]:
                seen += 1
                # Déduplication : si déjà en DB et scraped récemment,
                # on saute (mais on met à jour last_seen_at).
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

                import json as _json

                row = RentalListing(
                    source_url=detail["source_url"],
                    source=detail["source"],
                    address=detail.get("address"),
                    civique=detail.get("civique"),
                    nom_rue=detail.get("nom_rue"),
                    postal_code=detail.get("postal_code"),
                    quartier=detail.get("quartier"),
                    price=detail.get("price"),
                    bedrooms=detail.get("bedrooms"),
                    phone=detail.get("phone"),
                    is_renovated=bool(detail.get("is_renovated")),
                    inclusions_json=_json.dumps(
                        detail.get("inclusions") or []
                    ),
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
