"""Scraper Centris via Playwright — multi-logements à vendre.

Bypass Cloudflare/Datadome en utilisant un vrai navigateur Chromium
qui exécute le JS challenge. Beaucoup plus fiable que httpx direct.

Endpoints exposés :
- scrape_listings_via_browser : recherche par catégorie + région
- scrape_detail_via_browser : détail d'une annonce
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from playwright.async_api import Browser, Page

log = logging.getLogger(__name__)

CATEGORY_URLS = {
    "multiplex_2_5": (
        "https://www.centris.ca/fr/multiplex~immeuble-residentiel-a-vendre"
    ),
    "immeuble_residentiel_6_plus": (
        "https://www.centris.ca/fr/immeuble-residentiel-a-vendre"
    ),
}


async def scrape_listings_via_browser(
    browser: Browser,
    *,
    category: str = "multiplex_2_5",
    region: Optional[str] = None,
    max_pages: int = 2,
) -> List[dict]:
    """Lance Playwright sur la page de catégorie Centris, scroll
    pour charger toutes les annonces, extrait les listings.
    """
    base_url = CATEGORY_URLS.get(category)
    if not base_url:
        raise ValueError(f"Catégorie inconnue : {category}")

    context = await browser.new_context(
        locale="fr-CA",
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()
    page.set_default_timeout(20_000)

    listings: List[dict] = []
    try:
        for page_num in range(1, max_pages + 1):
            url = (
                base_url
                if page_num == 1
                else f"{base_url}?uc=1&page={page_num}"
            )
            log.info("Centris page %d : %s", page_num, url)
            await page.goto(url, wait_until="networkidle")

            # Scroll pour déclencher le lazy-loading
            for _ in range(3):
                await page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
                await page.wait_for_timeout(800)

            # Extrait les listings via __NEXT_DATA__ ou cards HTML
            html = await page.content()
            page_listings = _parse_listings_html(html)
            if not page_listings:
                log.warning(
                    "Centris page %d : 0 listings parsés", page_num
                )
                break
            listings.extend(page_listings)
    finally:
        await context.close()
    return listings


async def scrape_detail_via_browser(
    browser: Browser, url: str
) -> dict:
    """Ouvre une page de détail Centris, exécute le JS, déplie les
    sections repliables et retourne le HTML rendu complet.

    La section « Détails financiers » de Centris (évaluation
    municipale, taxes municipales/scolaires, dépenses) est injectée
    en JavaScript : un fetch httpx direct ne la voit pas. Le HTML
    rendu renvoyé dans la clé ``html`` contient tout le DOM après
    exécution JS — le backend peut alors y extraire ces champs
    financiers avec ses propres parsers ancrés sur les libellés.
    """
    context = await browser.new_context(locale="fr-CA")
    page = await context.new_page()
    page.set_default_timeout(20_000)
    try:
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_timeout(1500)
        # Scroll progressif : déclenche le lazy-loading des sections
        # basses de la fiche (dont « Détails financiers »).
        for _ in range(6):
            await page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await page.wait_for_timeout(600)
        # Déplie les panneaux repliés (détails financiers, voir plus).
        await _expand_all_sections(page)
        await page.wait_for_timeout(1000)
        html = await page.content()
        detail = _parse_detail_html(html, url)
        # HTML rendu complet → le backend lance parse_text dessus pour
        # récupérer la section financière chargée en JS.
        detail["html"] = html
        return detail
    finally:
        await context.close()


async def _expand_all_sections(page: Page) -> None:
    """Clique les déclencheurs qui déplient les sections repliées
    d'une fiche Centris — surtout « Détails financiers » (évaluation
    municipale, taxes, dépenses) affiché à la demande.

    Best-effort : toute erreur de clic (élément absent, hors écran,
    non cliquable) est silencieusement ignorée.
    """
    triggers = [
        "text=/d[ée]tails financiers/i",
        "text=/[ée]valuation municipale/i",
        "text=/voir (tous les |plus)/i",
        "[class*='financial'] button",
        "[class*='financial'] a",
        "button[aria-expanded='false']",
    ]
    for sel in triggers:
        try:
            elements = await page.query_selector_all(sel)
        except Exception:  # noqa: BLE001
            continue
        for el in elements[:8]:
            try:
                await el.scroll_into_view_if_needed(timeout=1500)
                await el.click(timeout=2000)
                await page.wait_for_timeout(350)
            except Exception:  # noqa: BLE001
                continue


# ============== Parsers ==============


_PRICE_RE = re.compile(r"(\d{1,3}(?:[\s,]\d{3})+|\d{4,8})\s*\$")
_UNITS_RE = re.compile(
    r"(\d+)\s*(?:logements?|unités?|appartements?|plex)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"(?:Année|Built)[\s:]*\b(\d{4})\b")
_MLS_RE = re.compile(r"\b(\d{8})\b")
_POSTAL_RE = re.compile(r"\b([HJK]\d[A-Z]\s*\d[A-Z]\d)\b")


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


def _parse_listings_html(html: str) -> List[dict]:
    """Tente d'abord __NEXT_DATA__ JSON, fallback sur cards HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    listings: List[dict] = []

    # 1) Next.js JSON
    next_data = soup.find(
        "script", id="__NEXT_DATA__", type="application/json"
    )
    if next_data and next_data.string:
        try:
            data = json.loads(next_data.string)
            extracted = _extract_from_next_data(data)
            if extracted:
                return extracted
        except Exception as exc:
            log.debug("__NEXT_DATA__ parse failed: %s", exc)

    # 2) Cards HTML (fallback)
    cards = soup.select(
        "[itemtype*='Product'], .property-thumbnail-item, "
        ".thumbnailItem, article.cac"
    )
    for card in cards[:50]:
        text = card.get_text(" ", strip=True)
        if not text:
            continue
        a = card.find("a", href=True)
        href = a.get("href") if a else None
        full_url = (
            href
            if href and href.startswith("http")
            else f"https://www.centris.ca{href}" if href else None
        )
        if not full_url:
            continue
        mls_m = _MLS_RE.search(text)
        postal_m = _POSTAL_RE.search(text)
        units_m = _UNITS_RE.search(text)
        year_m = _YEAR_RE.search(text)
        listings.append(
            {
                "source_url": full_url,
                "mls_id": mls_m.group(1) if mls_m else None,
                "address": None,
                "postal_code": (
                    postal_m.group(1).replace(" ", "")
                    if postal_m else None
                ),
                "price": _parse_price(text),
                "nb_units": (
                    int(units_m.group(1)) if units_m else None
                ),
                "year_built": (
                    int(year_m.group(1)) if year_m else None
                ),
            }
        )
    return listings


def _extract_from_next_data(data: dict) -> List[dict]:
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
            price_raw = (
                item.get("price")
                or item.get("Price")
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
                    "address": (
                        item.get("address")
                        or item.get("display_address")
                    ),
                    "price": price,
                    "nb_units": nb_units,
                    "year_built": item.get("yearBuilt"),
                    "city": item.get("city"),
                }
            )
    except Exception as exc:
        log.debug("next_data extraction error: %s", exc)
    return listings


def _parse_detail_html(html: str, url: str) -> dict:
    """Extrait les infos détaillées d'une page Centris : prix,
    revenus annuels, courtier, etc. Best-effort."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Revenus annuels (parfois affichés)
    revenus_m = re.search(
        r"Revenus?\s*(?:annuels?|brut)[^\d$]{0,30}"
        r"(\d{1,3}(?:[\s,]\d{3})+)\s*\$",
        text,
        re.IGNORECASE,
    )
    revenus = None
    if revenus_m:
        try:
            revenus = float(
                revenus_m.group(1).replace(" ", "").replace(",", "")
            )
        except ValueError:
            pass

    # Courtier (souvent dans .broker-name ou similaire)
    broker_el = soup.select_one(
        ".broker-info__name, .broker__name, [data-broker]"
    )
    broker_name = (
        broker_el.get_text(" ", strip=True) if broker_el else None
    )

    return {
        "source_url": url,
        "price": _parse_price(text),
        "revenus_annuels": revenus,
        "broker_name": broker_name,
        "mls_id": (
            _MLS_RE.search(text).group(1)
            if _MLS_RE.search(text)
            else None
        ),
    }
