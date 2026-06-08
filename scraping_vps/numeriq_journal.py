"""Scraper « comparables vendus » du Journal de Montréal via Playwright.

L'outil de comparables du Journal de Montréal s'appuie sur une API
interne ``recherche-api.numeriq.ca`` qui est derrière un login QUB
(compte Québecor Média) et une protection anti-bot Akamai. On
automatise un vrai navigateur Chromium (mode headed + Xvfb sur le
VPS) pour franchir le login et le challenge Akamai, puis on récupère
les transactions.

═══════════════════════════════════════════════════════════════════
⚠ SCAFFOLD À VALIDER AVEC UNE VRAIE SESSION QUB
───────────────────────────────────────────────────────────────────
Ce module est un SQUELETTE honnête. Au moment de l'écrire on n'a NI
compte QUB NI accès live. Tous les sélecteurs CSS, URLs de pages et
paths/params de l'API interne sont des HYPOTHÈSES marquées
``# ⚠ TODO: valider avec une vraie session QUB``. Il faut une session
réelle pour :
  1. Confirmer le flow de login QUB (URL, sélecteurs des champs,
     bouton submit, éventuel 2FA / consentement cookies).
  2. Confirmer l'URL de l'outil de comparables du Journal.
  3. Confirmer le path + les paramètres exacts de l'API interne
     ``recherche-api.numeriq.ca`` (observés dans l'onglet Réseau).
  4. Confirmer le mapping des champs de la réponse JSON vers le
     CONTRAT (voir ``_map_transaction``).

Le code est néanmoins syntaxiquement correct et importable : il ne
crash PAS à l'import et lève des exceptions claires (jamais un crash
du serveur) tant que le scaffold n'est pas validé.
═══════════════════════════════════════════════════════════════════

CONTRAT (le backend appelle ça en miroir) — chaque comparable :
  {
    "address":      str | None,   # adresse complète "civique nom_rue"
    "civique":      str | None,   # numéro civique
    "nom_rue":      str | None,   # nom de la rue
    "municipalite": str | None,
    "region":       str | None,
    "price":        float | None, # prix de vente numérique
    "date_sold":    str | None,   # "YYYY-MM-DD"
    "source_url":   str | None,
    "raw":          dict,         # dict brut de la source
  }
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import List, Optional

from playwright.async_api import Browser, Page

log = logging.getLogger(__name__)


# ============== Constantes (HYPOTHÈSES à valider) ==============

# Base de l'API interne du moteur de recherche Numeriq (Québecor).
# La base est connue ; le PATH et les PARAMS exacts ne le sont pas.
NUMERIQ_API_BASE = "https://recherche-api.numeriq.ca"

# ⚠ TODO: valider avec une vraie session QUB — path réel de
# l'endpoint de recherche de comparables (observer l'onglet Réseau
# du navigateur quand on lance une recherche dans l'outil).
NUMERIQ_API_SEARCH_PATH = "/v1/comparables/search"  # HYPOTHÈSE

# ⚠ TODO: valider avec une vraie session QUB — URL de la page de
# login QUB (Québecor) et URL de l'outil de comparables du Journal.
QUB_LOGIN_URL = "https://compte.qub.ca/connexion"  # HYPOTHÈSE
JOURNAL_COMPARABLES_URL = (
    "https://www.journaldemontreal.com/comparables"  # HYPOTHÈSE
)

# User-agent réaliste — cohérent avec evalweb.py / centris.py.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


# ============== Helpers de parsing ==============

# Détecte un prix : "450 000 $", "450,000$", "1 250 000 $".
_PRICE_RE = re.compile(r"(\d{1,3}(?:[\s ,]\d{3})+|\d{4,9})")
# Détecte un numéro civique en tête d'adresse : "1234 rue ..." .
_CIVIQUE_RE = re.compile(r"^\s*(\d+[A-Za-z]?)\b")
# Détecte une date ISO ou québécoise courante.
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _parse_price(value) -> Optional[float]:
    """Convertit un prix (str ou nombre) en float. Tolérant aux
    espaces, espaces insécables, virgules de milliers et symbole $."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        return n if 1_000 <= n <= 100_000_000 else None
    m = _PRICE_RE.search(str(value))
    if not m:
        return None
    raw = (
        m.group(1)
        .replace(" ", "")
        .replace(" ", "")
        .replace(",", "")
    )
    try:
        n = float(raw)
    except ValueError:
        return None
    return n if 1_000 <= n <= 100_000_000 else None


def _parse_date_sold(value) -> Optional[str]:
    """Normalise une date de vente vers ``YYYY-MM-DD``.

    ⚠ TODO: valider le format réel renvoyé par l'API numeriq
    (ISO ? timestamp epoch ? "12 mars 2025" ?). Ce helper gère le
    cas ISO + un fallback sur les 10 premiers caractères d'un
    datetime ISO. À étendre une fois le format réel connu.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _ISO_DATE_RE.search(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # Fallback : "2025-03-12T00:00:00Z" → "2025-03-12".
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _split_civique_rue(address: Optional[str]) -> tuple:
    """Sépare "1234 rue Saint-Denis" → ("1234", "rue Saint-Denis").

    Best-effort : si pas de numéro civique en tête, civique=None et
    nom_rue=adresse complète.
    """
    if not address:
        return None, None
    addr = address.strip()
    m = _CIVIQUE_RE.match(addr)
    if not m:
        return None, addr
    civique = m.group(1)
    nom_rue = addr[m.end():].strip(" ,") or None
    return civique, nom_rue


def _map_transaction(
    item: dict,
    *,
    fallback_municipalite: Optional[str] = None,
    fallback_region: Optional[str] = None,
) -> dict:
    """Mappe une transaction brute de l'API numeriq vers le CONTRAT.

    ⚠ TODO: valider avec une vraie session QUB — les clés ci-dessous
    (``address``, ``price``, ``saleDate``, etc.) sont des HYPOTHÈSES.
    Inspecter une vraie réponse JSON et ajuster les ``.get(...)``.
    On garde toujours ``raw`` = item brut pour ne rien perdre et
    permettre un re-parsing côté backend si le mapping évolue.
    """
    # HYPOTHÈSE de clés — plusieurs synonymes tentés par robustesse.
    address = (
        item.get("address")
        or item.get("adresse")
        or item.get("fullAddress")
        or item.get("displayAddress")
    )
    civique = item.get("civicNumber") or item.get("civique")
    nom_rue = item.get("streetName") or item.get("nomRue")
    if not (civique or nom_rue):
        civique, nom_rue = _split_civique_rue(address)

    municipalite = (
        item.get("municipality")
        or item.get("municipalite")
        or item.get("city")
        or item.get("ville")
        or fallback_municipalite
    )
    region = (
        item.get("region")
        or item.get("regionAdministrative")
        or fallback_region
    )

    price = _parse_price(
        item.get("price")
        if item.get("price") is not None
        else item.get("salePrice")
        if item.get("salePrice") is not None
        else item.get("prixVente")
    )

    date_sold = _parse_date_sold(
        item.get("saleDate")
        or item.get("dateSold")
        or item.get("dateVente")
        or item.get("date")
    )

    source_url = (
        item.get("url")
        or item.get("sourceUrl")
        or item.get("detailUrl")
        or JOURNAL_COMPARABLES_URL
    )

    return {
        "address": address,
        "civique": civique,
        "nom_rue": nom_rue,
        "municipalite": municipalite,
        "region": region,
        "price": price,
        "date_sold": date_sold,
        "source_url": source_url,
        "raw": item,
    }


# ============== Scraper principal ==============


async def scrape_comparables_via_browser(
    browser: Browser,
    *,
    nom_rue: Optional[str] = None,
    municipalite: Optional[str] = None,
    region: Optional[str] = None,
    limit: int = 50,
) -> List[dict]:
    """Récupère les comparables vendus depuis l'outil du Journal.

    Flow (scaffold) :
      1. Login QUB avec ``NUMERIQ_USERNAME`` / ``NUMERIQ_PASSWORD``.
      2. Navigue vers l'outil de comparables du Journal.
      3. Idéalement : appelle directement l'API interne
         ``recherche-api.numeriq.ca`` (via ``page.request``, qui
         réutilise les cookies de session du contexte) avec les
         filtres de secteur. Fallback : lecture des réponses réseau
         déclenchées par une recherche dans l'UI.
      4. Mappe les transactions vers le CONTRAT.

    Retourne une liste de dicts conformes au CONTRAT (voir docstring
    du module). Lève une exception claire si les credentials sont
    absents ou si le flow échoue — l'endpoint FastAPI traduit ça en
    HTTP 502, jamais un crash serveur.

    NOTE (réutilisation de session) : on pourrait persister le
    ``storage_state`` (cookies + localStorage) après le premier
    login pour éviter de se reconnecter à chaque appel — utile vu
    qu'Akamai/QUB peut throttle les logins répétés. Pour garder le
    scaffold simple, on fait un login par appel ; voir
    ``# ⚠ TODO: persister storage_state`` plus bas.
    """
    username = os.environ.get("NUMERIQ_USERNAME")
    password = os.environ.get("NUMERIQ_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "QUB credentials manquants "
            "(NUMERIQ_USERNAME/NUMERIQ_PASSWORD)"
        )

    context = await browser.new_context(
        locale="fr-CA",
        user_agent=_USER_AGENT,
        viewport={"width": 1280, "height": 800},
        # ⚠ TODO: persister storage_state — pour réutiliser la
        # session entre appels, charger ici un état sauvegardé :
        #   storage_state="/tmp/numeriq_state.json"
        # et le réécrire après login via context.storage_state(...).
    )
    page = await context.new_page()
    page.set_default_timeout(30_000)

    # On collecte les réponses réseau qui touchent l'API interne :
    # fallback si l'appel direct ``page.request`` ne marche pas
    # (params inconnus) — on capture ce que l'UI déclenche.
    captured_api_payloads: List[dict] = []

    async def _on_response(resp) -> None:
        try:
            if NUMERIQ_API_BASE in resp.url and resp.ok:
                ctype = resp.headers.get("content-type", "")
                if "application/json" in ctype:
                    captured_api_payloads.append(await resp.json())
        except Exception as exc:  # noqa: BLE001
            log.debug("capture API response failed: %s", exc)

    page.on(
        "response",
        lambda r: asyncio.ensure_future(_on_response(r)),
    )

    try:
        # ── Étape 1 : login QUB ─────────────────────────────────
        await _login_qub(page, username, password)

        # ── Étape 2 : ouvrir l'outil de comparables ─────────────
        # ⚠ TODO: valider avec une vraie session QUB — URL réelle.
        log.info("Numeriq : goto %s", JOURNAL_COMPARABLES_URL)
        await page.goto(
            JOURNAL_COMPARABLES_URL,
            wait_until="networkidle",
            timeout=30_000,
        )
        await page.wait_for_timeout(1_500)

        # ── Étape 3 : récupérer les transactions ────────────────
        transactions = await _fetch_transactions(
            page,
            nom_rue=nom_rue,
            municipalite=municipalite,
            region=region,
            limit=limit,
            captured_api_payloads=captured_api_payloads,
        )

        # ── Étape 4 : mapper vers le CONTRAT ────────────────────
        comparables = [
            _map_transaction(
                t,
                fallback_municipalite=municipalite,
                fallback_region=region,
            )
            for t in transactions[: max(0, limit)]
        ]
        log.info(
            "Numeriq : %d comparables extraits (nom_rue=%r, "
            "municipalite=%r, region=%r)",
            len(comparables),
            nom_rue,
            municipalite,
            region,
        )
        return comparables
    finally:
        await context.close()


# ============== Sous-étapes (scaffold) ==============


async def _login_qub(page: Page, username: str, password: str) -> None:
    """Connexion au compte QUB (Québecor).

    ⚠ TODO: valider avec une vraie session QUB — TOUT ce flow est
    une HYPOTHÈSE : URL, sélecteurs des champs, bouton submit,
    bannière de cookies, éventuel 2FA. À reprendre en observant une
    vraie page de connexion.
    """
    log.info("Numeriq : login QUB (user=%s…)", username[:3])
    await page.goto(
        QUB_LOGIN_URL, wait_until="networkidle", timeout=30_000
    )
    await page.wait_for_timeout(1_000)

    # ⚠ TODO: bannière de consentement cookies (Akamai/OneTrust ?).
    # Souvent il faut l'accepter avant de pouvoir taper. Best-effort.
    for sel in (
        "button:has-text('Accepter')",
        "#onetrust-accept-btn-handler",
        "button:has-text('Tout accepter')",
    ):
        try:
            await page.locator(sel).first.click(timeout=2_000)
            log.info("  → bannière cookies acceptée via %s", sel)
            break
        except Exception:  # noqa: BLE001
            continue

    # ⚠ TODO: valider les sélecteurs des champs identifiant/mdp.
    # HYPOTHÈSES — on tente plusieurs sélecteurs courants.
    filled_user = await _try_fill(
        page,
        value=username,
        selectors=(
            "input[type='email']",
            "input[name='username']",
            "input[name='email']",
            "input[autocomplete='username']",
            "#username",
        ),
        what="identifiant",
    )
    filled_pass = await _try_fill(
        page,
        value=password,
        selectors=(
            "input[type='password']",
            "input[name='password']",
            "input[autocomplete='current-password']",
            "#password",
        ),
        what="mot de passe",
    )
    if not (filled_user and filled_pass):
        raise RuntimeError(
            "Login QUB : champs identifiant/mot de passe introuvables "
            "(sélecteurs à valider avec une vraie session QUB)"
        )

    # ⚠ TODO: valider le bouton de soumission.
    submitted = False
    for sel in (
        "button[type='submit']",
        "button:has-text('Se connecter')",
        "button:has-text('Connexion')",
        "input[type='submit']",
    ):
        try:
            await page.locator(sel).first.click(timeout=3_000)
            submitted = True
            log.info("  → login soumis via %s", sel)
            break
        except Exception:  # noqa: BLE001
            continue
    if not submitted:
        raise RuntimeError(
            "Login QUB : bouton de soumission introuvable "
            "(sélecteur à valider avec une vraie session QUB)"
        )

    # Attend la fin de la navigation post-login.
    try:
        await page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(1_500)

    # ⚠ TODO: vérifier un marqueur de session authentifiée (présence
    # d'un avatar, d'un cookie de session, absence du form de login)
    # pour lever une erreur claire si le login a échoué (mauvais
    # credentials, 2FA, captcha Akamai). HYPOTHÈSE ci-dessous :
    if await page.locator("input[type='password']").count() > 0:
        log.warning(
            "Login QUB : un champ mot de passe est encore visible — "
            "le login a peut-être échoué (à valider)."
        )


async def _try_fill(
    page: Page, *, value: str, selectors, what: str
) -> bool:
    """Tente de remplir un champ via une liste de sélecteurs.
    Retourne True dès qu'un remplissage réussit."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.fill(value, timeout=3_000)
            log.info("  ✓ %s rempli via %s", what, sel)
            return True
        except Exception:  # noqa: BLE001
            continue
    log.warning("  ✗ %s : aucun sélecteur n'a fonctionné", what)
    return False


async def _fetch_transactions(
    page: Page,
    *,
    nom_rue: Optional[str],
    municipalite: Optional[str],
    region: Optional[str],
    limit: int,
    captured_api_payloads: List[dict],
) -> List[dict]:
    """Récupère la liste brute des transactions.

    Stratégie A (préférée) : appel direct de l'API interne via
    ``page.request`` — qui réutilise les cookies de session du
    contexte authentifié. Plus rapide et plus stable que de scraper
    le DOM.

    Stratégie B (fallback) : déclencher une recherche dans l'UI et
    lire les réponses JSON capturées par le listener réseau.

    ⚠ TODO: valider avec une vraie session QUB — le path
    (``NUMERIQ_API_SEARCH_PATH``) et les noms des paramètres de
    requête sont des HYPOTHÈSES.
    """
    # ── Stratégie A : appel direct de l'API interne ─────────────
    api_url = f"{NUMERIQ_API_BASE}{NUMERIQ_API_SEARCH_PATH}"
    # ⚠ TODO: valider les noms de params (street/city/region/limit ?).
    params = {
        k: v
        for k, v in {
            "street": nom_rue,
            "city": municipalite,
            "region": region,
            "limit": limit,
        }.items()
        if v is not None
    }
    try:
        log.info("Numeriq : appel direct API %s params=%s", api_url, params)
        resp = await page.request.get(
            api_url, params=params, timeout=20_000
        )
        if resp.ok:
            data = await resp.json()
            txns = _extract_transactions_from_payload(data)
            if txns:
                log.info(
                    "Numeriq : %d transactions via API directe",
                    len(txns),
                )
                return txns
            log.warning(
                "Numeriq : API directe OK mais 0 transaction parsée "
                "(structure JSON à valider)."
            )
        else:
            log.warning(
                "Numeriq : API directe a répondu %s (path/params à "
                "valider avec une vraie session QUB)",
                resp.status,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Numeriq : appel direct API échoué (%s) — fallback UI", exc
        )

    # ── Stratégie B : recherche via l'UI + capture réseau ───────
    # ⚠ TODO: valider avec une vraie session QUB — sélecteurs du
    # formulaire de recherche (champ rue/ville + bouton Rechercher).
    try:
        await _run_ui_search(
            page,
            nom_rue=nom_rue,
            municipalite=municipalite,
            region=region,
        )
        await page.wait_for_timeout(2_500)
    except Exception as exc:  # noqa: BLE001
        log.warning("Numeriq : recherche UI échouée (%s)", exc)

    # Agrège tout ce que le listener réseau a capturé.
    transactions: List[dict] = []
    for payload in captured_api_payloads:
        transactions.extend(_extract_transactions_from_payload(payload))
    if transactions:
        log.info(
            "Numeriq : %d transactions via capture réseau",
            len(transactions),
        )
    else:
        log.warning(
            "Numeriq : 0 transaction capturée — flow/API à valider "
            "avec une vraie session QUB."
        )
    return transactions


async def _run_ui_search(
    page: Page,
    *,
    nom_rue: Optional[str],
    municipalite: Optional[str],
    region: Optional[str],
) -> None:
    """Remplit le formulaire de recherche de l'outil et lance.

    ⚠ TODO: valider avec une vraie session QUB — sélecteurs du champ
    de recherche et du bouton. HYPOTHÈSES ci-dessous.
    """
    query_terms = " ".join(
        t for t in (nom_rue, municipalite, region) if t
    ).strip()
    if not query_terms:
        return
    filled = await _try_fill(
        page,
        value=query_terms,
        selectors=(
            "input[type='search']",
            "input[name='q']",
            "input[placeholder*='rech']",
            "input[placeholder*='adresse']",
        ),
        what="champ de recherche",
    )
    if not filled:
        return
    for sel in (
        "button:has-text('Rechercher')",
        "button[type='submit']",
        "button[aria-label*='rech']",
    ):
        try:
            await page.locator(sel).first.click(timeout=3_000)
            log.info("  → recherche lancée via %s", sel)
            return
        except Exception:  # noqa: BLE001
            continue
    # Fallback : touche Entrée dans le champ.
    try:
        await page.keyboard.press("Enter")
    except Exception:  # noqa: BLE001
        pass


def _extract_transactions_from_payload(payload) -> List[dict]:
    """Extrait la liste de transactions d'une réponse JSON numeriq.

    ⚠ TODO: valider avec une vraie session QUB — la structure réelle
    du JSON est inconnue. On tente plusieurs clés racines courantes
    (``results``, ``data``, ``transactions``, ``hits``…). À ancrer
    sur la vraie structure une fois observée.
    """
    if payload is None:
        return []
    # Cas : la racine est déjà une liste de transactions.
    if isinstance(payload, list):
        return [t for t in payload if isinstance(t, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (
        "results",
        "data",
        "transactions",
        "comparables",
        "items",
        "hits",
        "documents",
    ):
        val = payload.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val
        # Cas imbriqué type Elasticsearch : {"hits": {"hits": [...]}}.
        if isinstance(val, dict):
            nested = val.get("hits") or val.get("results")
            if isinstance(nested, list) and nested:
                return [t for t in nested if isinstance(t, dict)]
    return []
