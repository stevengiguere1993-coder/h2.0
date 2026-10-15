"""Service de scraping standalone — FastAPI + Playwright.

Tourne sur un VPS (Hetzner CX22 4 Go RAM, ~5 $/mois). Exposé via
HTTPS au backend principal sur Render qui n'a pas la RAM pour
Playwright.

Endpoints :
- POST /scrape/evalweb-owners : flow stateful 4 étapes du portail
  montreal.ca/role-evaluation-fonciere
- POST /scrape/centris : recherche multi-logements à vendre
- POST /scrape/numeriq-comparables : comparables vendus du Journal
  de Montréal (API interne numeriq, login QUB + Akamai)

Auth : header `X-API-Key` requis pour tous les endpoints non-public.
La clé est dans la variable d'env `SCRAPING_API_KEY`.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import List, Optional
from urllib.parse import quote_plus

from fastapi import Depends, FastAPI, HTTPException, Header
from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    async_playwright,
)
from pydantic import BaseModel, Field

from evalweb import scrape_owners_via_browser
from centris import (
    LAST_SEARCH_DIAGNOSTIC,
    scrape_detail_via_browser,
    scrape_listings_via_browser,
)
from numeriq_journal import scrape_comparables_via_browser

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
        # Indique si les identifiants QUB (Québecor) sont configurés sur le
        # VPS — c'est ici que le scraper de comparables se connecte. Permet
        # au backend d'afficher un bandeau « source auto » honnête sans avoir
        # à dupliquer le flag côté Render.
        "numeriq_configured": bool(os.environ.get("NUMERIQ_USERNAME")),
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
    #: Rempli seulement quand la liste est vide : pourquoi (titre de la
    #: page, captcha détecté, extrait) — registre des courtiers 2026-10-14.
    diagnostic: Optional[dict] = None


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
        listings=[CentrisListingMini(**l) for l in listings],
        diagnostic=(
            dict(LAST_SEARCH_DIAGNOSTIC)
            if not listings and LAST_SEARCH_DIAGNOSTIC
            else None
        ),
    )


class WebSearchRequest(BaseModel):
    query: str
    max_results: int = 8
    #: Jetons (nom du courtier) : si aucun résultat d'un moteur n'en
    #: contient un (titre / extrait / URL), le moteur suivant est essayé
    #: — Bing sert des pages bidon (sport, boutiques) aux robots.
    must_contain: List[str] = []


def _decoder_redirection(href: str) -> str:
    """Lien de moteur → URL réelle (DuckDuckGo uddg=, Bing ck/a u=a1…)."""
    from urllib.parse import parse_qs, urlparse
    import base64

    h = href or ""
    try:
        if "duckduckgo.com/l/" in h and "uddg=" in h:
            reel = (parse_qs(urlparse(h).query).get("uddg") or [""])[0]
            return reel if reel.startswith("http") else h
        if "bing.com/ck/a" in h:
            u = (parse_qs(urlparse(h).query).get("u") or [""])[0]
            if u.startswith("a1"):
                u = u[2:]
            u += "=" * (-len(u) % 4)
            reel = base64.urlsafe_b64decode(u.encode("ascii")).decode("utf-8", "ignore")
            return reel if reel.startswith("http") else h
    except Exception:  # noqa: BLE001
        return h
    return h


def _pertinents(items: list, jetons: List[str]) -> list:
    jet = [j.lower() for j in jetons if len(j) >= 3]
    if not jet:
        return items
    out = []
    for i in items:
        bas = " ".join(str(i.get(k) or "") for k in ("titre", "extrait", "url")).lower()
        if any(j in bas for j in jet):
            out.append(i)
    return out


class WebSearchResult(BaseModel):
    url: str
    titre: Optional[str] = None
    extrait: Optional[str] = None


class WebSearchResponse(BaseModel):
    results: List[WebSearchResult]
    moteur: Optional[str] = None


@app.post(
    "/scrape/web-search",
    response_model=WebSearchResponse,
    dependencies=[Depends(require_api_key)],
)
async def web_search(req: WebSearchRequest):
    """Résultats web rendus par un vrai navigateur (Bing, puis DuckDuckGo)
    — secours de la recherche du courriel des courtiers (Kratos
    2026-10-14) quand le serveur est bloqué par les moteurs."""
    browser: Browser = app.state.browser
    context = await browser.new_context(locale="fr-CA")
    page = await context.new_page()
    page.set_default_timeout(20_000)
    results: list = []
    moteur = None
    try:
        for moteur_essai, url in (
            ("duckduckgo", "https://html.duckduckgo.com/html/?q=" + quote_plus(req.query) + "&kl=ca-fr"),
            ("bing", "https://www.bing.com/search?q=" + quote_plus(req.query) + "&setlang=fr&cc=CA"),
            ("duckduckgo-lite", "https://lite.duckduckgo.com/lite/?q=" + quote_plus(req.query) + "&kl=ca-fr"),
        ):
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(1200)
                if moteur_essai == "bing":
                    items = await page.evaluate(
                        """() => Array.from(document.querySelectorAll('li.b_algo')).map(li => {
                            const a = li.querySelector('h2 a');
                            const p = li.querySelector('.b_caption p, p');
                            return a ? {url: a.href, titre: a.innerText, extrait: p ? p.innerText : ''} : null;
                        }).filter(Boolean)"""
                    )
                elif moteur_essai == "duckduckgo":
                    items = await page.evaluate(
                        """() => Array.from(document.querySelectorAll('.result')).map(r => {
                            const a = r.querySelector('a.result__a');
                            const s = r.querySelector('.result__snippet');
                            return a ? {url: a.href, titre: a.innerText, extrait: s ? s.innerText : ''} : null;
                        }).filter(Boolean)"""
                    )
                else:
                    items = await page.evaluate(
                        """() => Array.from(document.querySelectorAll('a.result-link')).map(a => {
                            const tr = a.closest('tr');
                            const next = tr ? tr.nextElementSibling : null;
                            return {url: a.href, titre: a.innerText, extrait: next ? next.innerText : ''};
                        })"""
                    )
                items = [i for i in (items or []) if str(i.get("url", "")).startswith("http")]
                for i in items:
                    i["url"] = _decoder_redirection(i["url"])
                items = _pertinents(items, req.must_contain)
                if items:
                    results = items[: max(1, min(20, req.max_results))]
                    moteur = moteur_essai
                    break
            except Exception as exc:  # noqa: BLE001
                log.warning("web-search %s en échec : %s", moteur_essai, exc)
    finally:
        await context.close()
    return WebSearchResponse(
        results=[WebSearchResult(**r) for r in results], moteur=moteur
    )


class PageTextRequest(BaseModel):
    url: str


@app.post(
    "/scrape/page-text",
    dependencies=[Depends(require_api_key)],
)
async def page_text(req: PageTextRequest):
    """Texte visible + liens mailto d'une page rendue (JS exécuté) —
    lecture des pages d'agences / sites de courtiers (Kratos 2026-10-14)."""
    browser: Browser = app.state.browser
    context = await browser.new_context(locale="fr-CA")
    page = await context.new_page()
    page.set_default_timeout(25_000)
    try:
        await page.goto(req.url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        texte = await page.evaluate("() => document.body ? document.body.innerText : ''")
        mailtos = await page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href^=\"mailto:\"]')).map(a => a.getAttribute('href'))"
        )
        title = await page.title()
    except Exception as exc:  # noqa: BLE001
        log.warning("page-text %s en échec : %s", req.url, exc)
        raise HTTPException(502, f"Échec lecture de la page : {exc}")
    finally:
        await context.close()
    return {
        "url": req.url,
        "title": title,
        "texte": (texte or "")[:200_000],
        "mailtos": list(dict.fromkeys(m for m in (mailtos or []) if m)),
    }


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


# ============== Page rendue (générique) ==============
#
# Sert au relevé des prix chez les détaillants qui bloquent un client HTTP
# nu (rona.ca, bmr.ca…) : Kratos envoie l'URL, on renvoie le HTML rendu
# par le navigateur. Aucun contournement agressif : mêmes réglages que
# le reste du service (headed + Xvfb), une page par appel.


class FetchHtmlRequest(BaseModel):
    url: str
    #: Attente après le chargement (ms) pour laisser les prix s'afficher.
    wait_ms: int = Field(default=1500, ge=0, le=15000)
    #: Sélecteur CSS à attendre (optionnel), ex. "[itemprop=price]".
    wait_for: Optional[str] = None


class FetchHtmlResponse(BaseModel):
    html: str
    final_url: str
    status: Optional[int] = None


@app.post(
    "/scrape/fetch-html",
    dependencies=[Depends(require_api_key)],
    response_model=FetchHtmlResponse,
)
async def fetch_html(req: FetchHtmlRequest):
    """HTML rendu d'une page (après JS), pour les parseurs de prix."""
    browser: Browser = app.state.browser
    context = await browser.new_context(
        locale="fr-CA",
        viewport={"width": 1366, "height": 900},
    )
    try:
        page = await context.new_page()
        resp = await page.goto(req.url, wait_until="domcontentloaded", timeout=45000)
        if req.wait_for:
            try:
                await page.wait_for_selector(req.wait_for, timeout=10000)
            except Exception:  # noqa: BLE001
                pass
        if req.wait_ms:
            await page.wait_for_timeout(req.wait_ms)
        html = await page.content()
        return FetchHtmlResponse(
            html=html, final_url=page.url,
            status=(resp.status if resp is not None else None),
        )
    except Exception as exc:
        raise HTTPException(502, f"Échec du rendu de {req.url} : {exc}")
    finally:
        await context.close()


# ============== Numeriq — Comparables vendus (Journal de MTL) ==============


class NumeriqComparablesRequest(BaseModel):
    nom_rue: Optional[str] = None
    municipalite: Optional[str] = None
    region: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=200)


class NumeriqComparable(BaseModel):
    address: Optional[str] = None
    civique: Optional[str] = None
    nom_rue: Optional[str] = None
    municipalite: Optional[str] = None
    region: Optional[str] = None
    price: Optional[float] = None
    date_sold: Optional[str] = None  # "YYYY-MM-DD"
    source_url: Optional[str] = None
    raw: dict = Field(default_factory=dict)


class NumeriqComparablesResponse(BaseModel):
    comparables: List[NumeriqComparable]


@app.post(
    "/scrape/numeriq-comparables",
    response_model=NumeriqComparablesResponse,
    dependencies=[Depends(require_api_key)],
)
async def numeriq_comparables(req: NumeriqComparablesRequest):
    """Récupère les « comparables vendus » de l'outil du Journal de
    Montréal (API interne numeriq, derrière login QUB + Akamai).

    ⚠ SCAFFOLD : à valider avec une vraie session QUB (login flow,
    URL/params de l'API numeriq, mapping des champs). Voir
    numeriq_journal.py. En cas d'échec (credentials absents, login
    KO, API à valider), on renvoie un 502 propre — jamais un crash.
    """
    browser: Browser = app.state.browser
    try:
        comparables = await scrape_comparables_via_browser(
            browser,
            nom_rue=req.nom_rue,
            municipalite=req.municipalite,
            region=req.region,
            limit=req.limit,
        )
    except Exception as exc:
        log.exception("numeriq comparables scrape failed: %s", exc)
        raise HTTPException(502, f"Échec scrape Numeriq : {exc}")
    return NumeriqComparablesResponse(
        comparables=[NumeriqComparable(**c) for c in comparables]
    )
