"""Service de scraping standalone — FastAPI + Playwright.

Tourne sur un VPS (Hetzner CX22 4 Go RAM, ~5 $/mois). Exposé via
HTTPS au backend principal sur Render qui n'a pas la RAM pour
Playwright.

Endpoints :
- POST /scrape/evalweb-owners : flow stateful 4 étapes du portail
  montreal.ca/role-evaluation-fonciere
- POST /scrape/centris : recherche multi-logements à vendre

Auth : header `X-API-Key` requis pour tous les endpoints non-public.
La clé est dans la variable d'env `SCRAPING_API_KEY`.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Header
from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    async_playwright,
)
from pydantic import BaseModel, Field

from evalweb import scrape_owners_via_browser
from centris import scrape_listings_via_browser, scrape_detail_via_browser

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("scraping")

API_KEY = os.environ.get("SCRAPING_API_KEY", "")


# ============== Lifecycle ==============


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Démarre Playwright au boot, ferme au shutdown."""
    log.info("Démarrage Playwright…")
    pw = await async_playwright().start()
    # headless=False + Xvfb : le navigateur tourne réellement en mode
    # headed dans un display virtuel — score reCAPTCHA v3 beaucoup
    # plus élevé qu'en headless pur (qui est blacklisté).
    browser = await pw.chromium.launch(
        headless=False,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ],
    )
    app.state.playwright = pw
    app.state.browser = browser
    log.info("Playwright prêt.")
    yield
    log.info("Arrêt Playwright…")
    await browser.close()
    await pw.stop()


app = FastAPI(
    title="Horizon Scraping Service",
    lifespan=lifespan,
)


# ============== Auth ==============


def require_api_key(x_api_key: Optional[str] = Header(default=None)):
    if not API_KEY:
        # Pas de clé configurée = mode dev, on laisse passer.
        return
    if x_api_key != API_KEY:
        raise HTTPException(401, "Invalid X-API-Key")


# ============== Health ==============


@app.get("/health")
async def health():
    return {
        "ok": True,
        "browser_connected": app.state.browser.is_connected(),
    }


# ============== EvalWeb (rôle MTL) ==============


class EvalWebRequest(BaseModel):
    matricule: str = Field(min_length=10, max_length=32)


class EvalWebOwner(BaseModel):
    name: str
    statut: Optional[str] = None
    postal_address: Optional[str] = None
    inscription_date: Optional[str] = None
    conditions: Optional[str] = None


class EvalWebResponse(BaseModel):
    matricule: str
    owners: List[EvalWebOwner]
    raw_text: Optional[str] = None


@app.post(
    "/scrape/evalweb-owners",
    response_model=EvalWebResponse,
    dependencies=[Depends(require_api_key)],
)
async def evalweb_owners(req: EvalWebRequest):
    """Flow stateful 4 étapes du portail montreal.ca pour
    récupérer les propriétaires d'un matricule.
    """
    browser: Browser = app.state.browser
    try:
        owners, raw = await scrape_owners_via_browser(browser, req.matricule)
    except Exception as exc:
        log.exception("evalweb scrape failed: %s", exc)
        raise HTTPException(502, f"Échec scrape EvalWeb : {exc}")

    return EvalWebResponse(
        matricule=req.matricule,
        owners=[EvalWebOwner(**o) for o in owners],
        raw_text=raw if not owners else None,
    )


# ============== Centris ==============


class CentrisSearchRequest(BaseModel):
    category: str = Field(
        default="multiplex_2_5",
        pattern="^(multiplex_2_5|immeuble_residentiel_6_plus)$",
    )
    region: Optional[str] = None  # ex. "Montréal/Île-des-Sœurs"
    max_pages: int = Field(default=2, ge=1, le=10)


class CentrisListingMini(BaseModel):
    mls_id: Optional[str] = None
    source_url: str
    address: Optional[str] = None
    civique: Optional[str] = None
    nom_rue: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    price: Optional[float] = None
    nb_units: Optional[int] = None
    year_built: Optional[int] = None


class CentrisSearchResponse(BaseModel):
    listings: List[CentrisListingMini]


@app.post(
    "/scrape/centris-search",
    response_model=CentrisSearchResponse,
    dependencies=[Depends(require_api_key)],
)
async def centris_search(req: CentrisSearchRequest):
    """Lance une recherche Centris + extrait les listings de la page.
    Bypass Cloudflare/Datadome via Playwright."""
    browser: Browser = app.state.browser
    try:
        listings = await scrape_listings_via_browser(
            browser,
            category=req.category,
            region=req.region,
            max_pages=req.max_pages,
        )
    except Exception as exc:
        log.exception("centris scrape failed: %s", exc)
        raise HTTPException(502, f"Échec scrape Centris : {exc}")
    return CentrisSearchResponse(
        listings=[CentrisListingMini(**l) for l in listings]
    )


class CentrisDetailRequest(BaseModel):
    url: str


@app.post(
    "/scrape/centris-detail",
    dependencies=[Depends(require_api_key)],
)
async def centris_detail(req: CentrisDetailRequest):
    """Détail d'une annonce Centris (revenus, courtier, descriptions)."""
    browser: Browser = app.state.browser
    try:
        detail = await scrape_detail_via_browser(browser, req.url)
    except Exception as exc:
        raise HTTPException(502, f"Échec détail Centris : {exc}")
    return detail
