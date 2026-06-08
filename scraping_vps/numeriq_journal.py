"""Scraper « comparables vendus » du Journal de Montréal via Playwright.

═══════════════════════════════════════════════════════════════════
CONTRAT D'API RÉEL (découvert en inspectant l'outil EN VRAI, session
QUB authentifiée — 2026)
───────────────────────────────────────────────────────────────────
L'outil « Transactions immobilières » du Journal de Montréal vit à :

    https://www.journaldemontreal.com/argent/immobilier/transactions-immobilieres

Cette page parente est protégée par **Akamai Bot Manager** (d'où le
besoin d'un vrai Chromium headed + Xvfb, déjà géré par app.py sur le
VPS). L'outil lui-même tourne dans une **iframe** qui affiche une
**carte Mapbox** :

    https://www.journaldemontreal.com/iframe-transactions-immobilieres/index.html

Le backend de données réel est l'API QUB (Québecor) :

    base = https://api.qub.ca/real-estate-service/v1

Deux endpoints connus :
  • GET /real-estate-service/v1/locations/all
        → liste des localités/quartiers ; sert l'autocomplete du
          champ de recherche de l'outil.
  • GET /real-estate-service/v1/map
        → LES TRANSACTIONS d'une zone (le cœur). Paramètres observés
          dans le bundle de l'app : bornes de la carte
          (north/south/east/west — variantes possibles
          neLat/neLng/swLat/swLng), zoom, propertyType,
          startDate/endDate, limit/offset/page.

AUTH = **session QUB par cookies**. Il suffit que le navigateur soit
connecté à QUB (compte Québecor Média) ; AUCUN Bearer token séparé
n'a été observé. Une fois le navigateur authentifié, l'app fait ses
appels à api.qub.ca avec les cookies de session.

⚠ Les fetch manuels cross-origin vers api.qub.ca échouent (CORS). On
NE rejoue donc PAS l'appel à la main. La BONNE stratégie est de
laisser l'app charger la carte et d'**INTERCEPTER** les réponses de
``/real-estate-service/v1/map`` via Playwright ``page.on("response")``.

⚠ Le domaine ``recherche-api.numeriq.ca`` ne sert PAS aux données
(uniquement au consentement cookies). Aucune référence à numeriq
comme source de données.
═══════════════════════════════════════════════════════════════════

CONTRAT DE SORTIE (inchangé — le backend appelle ça en miroir) —
chaque comparable :
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

═══════════════════════════════════════════════════════════════════
3 INCONNUES RESTANTES (à valider une fois sur le VPS avec session QUB)
  1. URL exacte du login QUB + sélecteurs des champs identifiant/mdp
     et du bouton de soumission (constantes QUB_LOGIN_*).
  2. Sélecteurs du champ de recherche de l'outil + des suggestions
     d'autocomplete (qui s'appuie sur /locations/all).
  3. Mapping exact des champs depuis la structure JSON réelle de
     /map vers le CONTRAT (voir _map_transaction, défensif).
Tout le reste (domaine, endpoints, params, auth par session,
stratégie d'interception) est CERTAIN.
═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import List, Optional

from playwright.async_api import Browser, Page

log = logging.getLogger(__name__)


# ============== Constantes (CONTRAT D'API RÉEL) ==============

# Base de l'API QUB (Québecor) — source de données réelle.
QUB_API_BASE = "https://api.qub.ca/real-estate-service/v1"

# Endpoint autocomplete des localités/quartiers (alimente la
# recherche de l'outil).
LOCATIONS_ENDPOINT = QUB_API_BASE + "/locations/all"

# Fragment d'URL qui identifie l'endpoint des transactions d'une
# zone. On filtre les réponses réseau là-dessus (interception).
MAP_ENDPOINT_FRAGMENT = "real-estate-service/v1/map"

# Page parente de l'outil (Akamai Bot Manager + iframe Mapbox).
JOURNAL_TOOL_URL = (
    "https://www.journaldemontreal.com/argent/immobilier/"
    "transactions-immobilieres"
)

# ── 3 INCONNUES — login QUB ──────────────────────────────────────
# ⚠ TODO: valider sur le VPS avec session QUB — l'URL de login QUB
# exacte et les sélecteurs des champs ne sont PAS confirmés. Ce sont
# des points de départ raisonnables, à ajuster en observant la vraie
# page de connexion. NE PAS les considérer comme certains.
QUB_LOGIN_URL = "https://qub.ca/connexion"  # ⚠ à valider
QUB_LOGIN_USER_SELECTORS = (  # ⚠ à valider
    "input[type='email']",
    "input[name='username']",
    "input[name='email']",
    "input[autocomplete='username']",
    "#username",
)
QUB_LOGIN_PASS_SELECTORS = (  # ⚠ à valider
    "input[type='password']",
    "input[name='password']",
    "input[autocomplete='current-password']",
    "#password",
)
QUB_LOGIN_SUBMIT_SELECTORS = (  # ⚠ à valider
    "button[type='submit']",
    "button:has-text('Se connecter')",
    "button:has-text('Connexion')",
    "input[type='submit']",
)

# ── 3 INCONNUES — champ de recherche de l'outil ──────────────────
# ⚠ TODO: valider sur le VPS avec session QUB — sélecteurs du champ
# de recherche de l'outil (autocomplete sur /locations/all) et des
# items de suggestion. Le champ peut être DANS l'iframe Mapbox.
TOOL_SEARCH_INPUT_SELECTORS = (  # ⚠ à valider
    "input[type='search']",
    "input[placeholder*='rech']",
    "input[placeholder*='adresse']",
    "input[placeholder*='localité']",
    "input[name='q']",
)
TOOL_SEARCH_SUGGESTION_SELECTORS = (  # ⚠ à valider
    "[role='option']",
    "li[role='option']",
    ".autocomplete-suggestion",
    "ul[role='listbox'] li",
)

# Délai max d'attente d'au moins une réponse /map capturée.
MAP_CAPTURE_TIMEOUT_MS = 30_000

# User-agent réaliste — cohérent avec evalweb.py / centris.py.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


# ============== Helpers de parsing ==============

# Détecte un prix : "450 000 $", "450,000$", "1 250 000 $".
_PRICE_RE = re.compile(r"(\d{1,3}(?:[\s ,]\d{3})+|\d{4,9})")
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
        .replace(" ", "")
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

    Gère le cas ISO (``2025-03-12``), un datetime ISO
    (``2025-03-12T00:00:00Z`` → ``2025-03-12``) et un timestamp
    epoch (secondes ou millisecondes).

    ⚠ TODO: valider sur le VPS avec session QUB — le format réel
    renvoyé par /map reste à confirmer ; étendre au besoin.
    """
    if value is None:
        return None
    # Timestamp epoch (int/float) — secondes ou millisecondes.
    if isinstance(value, (int, float)):
        try:
            import datetime as _dt

            ts = float(value)
            if ts > 1_000_000_000_000:  # millisecondes
                ts /= 1000.0
            return _dt.datetime.utcfromtimestamp(ts).strftime(
                "%Y-%m-%d"
            )
        except Exception:  # noqa: BLE001
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


def _first(item: dict, *keys):
    """Retourne la 1re valeur non-None parmi plusieurs clés
    synonymes d'un dict (clés inconnues côté /map → on tente
    plusieurs orthographes FR/EN)."""
    for k in keys:
        if k in item and item[k] is not None:
            return item[k]
    return None


def _map_transaction(
    item: dict,
    *,
    fallback_municipalite: Optional[str] = None,
    fallback_region: Optional[str] = None,
) -> dict:
    """Mappe une transaction brute de /map vers le CONTRAT.

    ⚠ TODO: valider sur le VPS avec session QUB — le mapping des
    champs depuis la structure JSON réelle de /map reste à finaliser
    une fois la 1re réponse capturée. Ce helper est DÉFENSIF : il
    tente plusieurs clés synonymes (FR/EN) et met toujours
    ``raw`` = item brut pour ne rien perdre et permettre un
    re-parsing côté backend si le mapping évolue.
    """
    address = _first(
        item,
        "address",
        "adresse",
        "fullAddress",
        "displayAddress",
        "adresseComplete",
    )
    civique = _first(
        item, "civicNumber", "civique", "noCivique", "streetNumber"
    )
    nom_rue = _first(
        item, "streetName", "nomRue", "rue", "street"
    )
    if not (civique or nom_rue):
        civique, nom_rue = _split_civique_rue(address)

    municipalite = (
        _first(
            item,
            "municipality",
            "municipalite",
            "city",
            "ville",
            "locality",
        )
        or fallback_municipalite
    )
    region = (
        _first(
            item,
            "region",
            "regionAdministrative",
            "quartier",
            "neighborhood",
        )
        or fallback_region
    )

    price = _parse_price(
        _first(
            item,
            "price",
            "prix",
            "montant",
            "salePrice",
            "prixVente",
            "soldPrice",
            "amount",
        )
    )

    date_sold = _parse_date_sold(
        _first(
            item,
            "date",
            "dateVente",
            "saleDate",
            "dateSold",
            "soldDate",
            "transactionDate",
        )
    )

    source_url = (
        _first(item, "url", "sourceUrl", "detailUrl", "lien")
        or JOURNAL_TOOL_URL
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


def _extract_transactions_from_payload(payload) -> List[dict]:
    """Extrait la liste de transactions d'une réponse JSON /map.

    ⚠ TODO: valider sur le VPS avec session QUB — la structure
    racine réelle de /map est inconnue. On tente plusieurs clés
    racines courantes (``results``, ``data``, ``transactions``,
    ``features`` style GeoJSON, ``items``…). À ancrer sur la vraie
    structure une fois observée.
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
        "features",  # GeoJSON (Mapbox)
        "hits",
        "documents",
    ):
        val = payload.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            # GeoJSON : les vraies données sont sous .properties.
            if key == "features":
                out = []
                for feat in val:
                    props = feat.get("properties")
                    out.append(
                        props if isinstance(props, dict) else feat
                    )
                return out
            return val
        # Cas imbriqué type Elasticsearch : {"hits": {"hits": [...]}}.
        if isinstance(val, dict):
            nested = val.get("hits") or val.get("results")
            if isinstance(nested, list) and nested:
                return [t for t in nested if isinstance(t, dict)]
    return []


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

    STRATÉGIE (reflète le contrat d'API réel — voir docstring module) :
      1. Créer un contexte/page (locale fr-CA, UA réaliste ;
         headed + Xvfb déjà géré par app.py pour franchir Akamai).
      2. Login QUB (cookies de session) avec QUB_USERNAME/PASSWORD
         (fallback NUMERIQ_USERNAME/PASSWORD pour compat).
      3. Enregistrer un handler page.on("response") qui capture le
         JSON de toute réponse dont l'URL contient
         MAP_ENDPOINT_FRAGMENT (= /real-estate-service/v1/map).
      4. Naviguer vers JOURNAL_TOOL_URL, attendre la carte/iframe,
         rechercher le secteur (tape nom_rue/municipalite dans le
         champ → autocomplete /locations/all → sélectionne une
         suggestion → la carte se recentre → l'app appelle /map →
         le handler capture).
      5. Attendre qu'au moins une réponse /map soit capturée (timeout
         MAP_CAPTURE_TIMEOUT_MS) ; sinon lever une exception claire.
      6. Parser les payloads capturés vers le CONTRAT.
      7. try/finally : toujours fermer le contexte.

    On NE rejoue PAS l'appel /map à la main (CORS cross-origin
    échoue) — on intercepte ce que l'app déclenche.

    Lève une exception claire si les credentials sont absents ou si
    rien n'est capturé — l'endpoint FastAPI traduit ça en HTTP 502,
    jamais un crash serveur.
    """
    # Identifiants : QUB_* en priorité, fallback NUMERIQ_* (compat
    # avec le reste du système qui nomme déjà ces variables).
    username = os.environ.get("QUB_USERNAME") or os.environ.get(
        "NUMERIQ_USERNAME"
    )
    password = os.environ.get("QUB_PASSWORD") or os.environ.get(
        "NUMERIQ_PASSWORD"
    )
    if not username or not password:
        raise RuntimeError(
            "Identifiants QUB manquants "
            "(QUB_USERNAME/QUB_PASSWORD ou "
            "NUMERIQ_USERNAME/NUMERIQ_PASSWORD)"
        )

    # ── Étape 1 : contexte/page ─────────────────────────────────
    context = await browser.new_context(
        locale="fr-CA",
        user_agent=_USER_AGENT,
        viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()
    page.set_default_timeout(30_000)

    # ── Étape 3 : interception des réponses /map ────────────────
    # On enregistre le handler AVANT toute navigation pour ne rien
    # rater. Chaque réponse dont l'URL contient MAP_ENDPOINT_FRAGMENT
    # est parsée en JSON et accumulée dans `captured`.
    captured: List[dict] = []

    async def _on_response(resp) -> None:
        try:
            if MAP_ENDPOINT_FRAGMENT in resp.url:
                # On ne filtre pas trop strictement le content-type :
                # certaines API renvoient application/json sans charset
                # ou un type générique. response.json() lèvera si ce
                # n'est pas du JSON — on l'attrape ci-dessous.
                data = await resp.json()
                captured.append(data)
                log.info("QUB : réponse /map capturée (%s)", resp.url)
        except Exception as exc:  # noqa: BLE001
            log.debug("capture /map response failed: %s", exc)

    page.on(
        "response",
        lambda r: asyncio.ensure_future(_on_response(r)),
    )

    try:
        # ── Étape 2 : login QUB (session par cookies) ───────────
        await _login_qub(page, username, password)

        # ── Étape 4 : ouvrir l'outil + cibler le secteur ────────
        log.info("QUB : goto %s", JOURNAL_TOOL_URL)
        await page.goto(
            JOURNAL_TOOL_URL,
            wait_until="networkidle",
            timeout=30_000,
        )
        # Laisse la carte Mapbox + l'iframe s'initialiser.
        await page.wait_for_timeout(2_500)

        await _search_sector(
            page,
            nom_rue=nom_rue,
            municipalite=municipalite,
        )

        # ── Étape 5 : attendre au moins une réponse /map ────────
        await _wait_for_capture(captured, MAP_CAPTURE_TIMEOUT_MS)

        # ── Étape 6 : parser les payloads capturés ──────────────
        transactions: List[dict] = []
        for payload in captured:
            transactions.extend(
                _extract_transactions_from_payload(payload)
            )

        if not transactions:
            raise RuntimeError(
                "QUB : réponse(s) /map capturée(s) mais 0 transaction "
                "parsée — structure JSON à valider sur le VPS "
                "(voir _extract_transactions_from_payload)."
            )

        comparables = [
            _map_transaction(
                t,
                fallback_municipalite=municipalite,
                fallback_region=region,
            )
            for t in transactions[: max(0, limit)]
        ]
        log.info(
            "QUB : %d comparables extraits (nom_rue=%r, "
            "municipalite=%r, region=%r)",
            len(comparables),
            nom_rue,
            municipalite,
            region,
        )
        return comparables
    finally:
        # ── Étape 7 : toujours fermer proprement ────────────────
        await context.close()


# ============== Sous-étapes ==============


async def _login_qub(page: Page, username: str, password: str) -> None:
    """Connexion au compte QUB (Québecor) — établit la session par
    cookies réutilisée ensuite par les appels à api.qub.ca.

    ⚠ TODO: valider sur le VPS avec session QUB — l'URL de login
    exacte (QUB_LOGIN_URL) et les sélecteurs des champs
    (QUB_LOGIN_*_SELECTORS) ne sont PAS confirmés. On tente d'abord
    de partir de la page de l'outil et de suivre un éventuel bouton
    de connexion ; à défaut on va directement sur QUB_LOGIN_URL.
    NE PAS considérer ces sélecteurs comme certains.
    """
    log.info("QUB : login (user=%s…)", username[:3])

    # On passe par la page de l'outil : si un bouton « Se connecter »
    # mène à QUB, on le suit ; sinon on va direct sur QUB_LOGIN_URL.
    # ⚠ TODO: valider le sélecteur du bouton de connexion sur la page
    # du Journal une fois sur le VPS.
    followed_login_link = False
    try:
        await page.goto(
            JOURNAL_TOOL_URL,
            wait_until="networkidle",
            timeout=30_000,
        )
        await page.wait_for_timeout(1_000)
        await _accept_cookie_banner(page)
        for sel in (  # ⚠ à valider
            "a:has-text('Se connecter')",
            "button:has-text('Se connecter')",
            "a:has-text('Connexion')",
            "a[href*='connexion']",
        ):
            try:
                await page.locator(sel).first.click(timeout=2_500)
                followed_login_link = True
                log.info("  → bouton de connexion suivi via %s", sel)
                break
            except Exception:  # noqa: BLE001
                continue
    except Exception as exc:  # noqa: BLE001
        log.debug("  ouverture page outil avant login: %s", exc)

    if not followed_login_link:
        # ⚠ TODO: valider QUB_LOGIN_URL sur le VPS.
        log.info("  → goto login QUB direct %s", QUB_LOGIN_URL)
        await page.goto(
            QUB_LOGIN_URL, wait_until="networkidle", timeout=30_000
        )

    await page.wait_for_timeout(1_000)
    await _accept_cookie_banner(page)

    filled_user = await _try_fill(
        page,
        value=username,
        selectors=QUB_LOGIN_USER_SELECTORS,
        what="identifiant",
    )
    filled_pass = await _try_fill(
        page,
        value=password,
        selectors=QUB_LOGIN_PASS_SELECTORS,
        what="mot de passe",
    )
    if not (filled_user and filled_pass):
        raise RuntimeError(
            "Login QUB : champs identifiant/mot de passe introuvables "
            "(sélecteurs à valider sur le VPS avec session QUB)"
        )

    submitted = False
    for sel in QUB_LOGIN_SUBMIT_SELECTORS:
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
            "(sélecteur à valider sur le VPS avec session QUB)"
        )

    # Attend la fin de la navigation post-login.
    try:
        await page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(1_500)

    # Marqueur d'échec best-effort : un champ mot de passe encore
    # visible suggère que le login n'a pas abouti (mauvais creds,
    # 2FA, captcha Akamai).
    try:
        if await page.locator("input[type='password']").count() > 0:
            log.warning(
                "Login QUB : un champ mot de passe est encore visible "
                "— le login a peut-être échoué (à valider sur le VPS)."
            )
    except Exception:  # noqa: BLE001
        pass


async def _accept_cookie_banner(page: Page) -> None:
    """Accepte une bannière de consentement cookies si présente
    (best-effort). Le consentement passe par recherche-api.numeriq.ca
    côté front mais ne nous intéresse pas comme source de données."""
    for sel in (
        "#onetrust-accept-btn-handler",
        "button:has-text('Tout accepter')",
        "button:has-text('Accepter')",
        "button:has-text(\"J'accepte\")",
    ):
        try:
            await page.locator(sel).first.click(timeout=2_000)
            log.info("  → bannière cookies acceptée via %s", sel)
            return
        except Exception:  # noqa: BLE001
            continue


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


async def _search_sector(
    page: Page,
    *,
    nom_rue: Optional[str],
    municipalite: Optional[str],
) -> None:
    """Recherche le secteur dans l'outil : tape un terme dans le
    champ de recherche (autocomplete sur /locations/all) et
    sélectionne une suggestion → la carte se recentre → l'app
    appelle /map → le handler d'interception capture la réponse.

    ⚠ TODO: valider sur le VPS avec session QUB — les sélecteurs du
    champ de recherche et des suggestions ne sont PAS confirmés, et
    le champ peut se trouver DANS l'iframe Mapbox (auquel cas il
    faut cibler le frame). NE PAS considérer ces sélecteurs comme
    certains.
    """
    query_terms = " ".join(
        t for t in (nom_rue, municipalite) if t
    ).strip()
    if not query_terms:
        # Sans terme de recherche, la carte se charge sur sa zone par
        # défaut et déclenche tout de même un /map ; on laisse faire.
        log.info(
            "QUB : pas de terme de recherche — capture de la zone "
            "par défaut de la carte."
        )
        return

    # Le champ peut être dans la page OU dans l'iframe de l'outil.
    # On tente la page principale d'abord, puis chaque frame.
    targets = [page] + list(page.frames)
    filled = False
    for target in targets:
        for sel in TOOL_SEARCH_INPUT_SELECTORS:
            try:
                loc = target.locator(sel).first
                await loc.fill(query_terms, timeout=2_500)
                log.info(
                    "  ✓ terme de recherche '%s' tapé via %s",
                    query_terms,
                    sel,
                )
                filled = True
                break
            except Exception:  # noqa: BLE001
                continue
        if filled:
            # Laisse l'autocomplete (/locations/all) répondre.
            await page.wait_for_timeout(1_500)
            # Sélectionne la 1re suggestion, sinon Entrée.
            picked = False
            for sel in TOOL_SEARCH_SUGGESTION_SELECTORS:
                try:
                    await target.locator(sel).first.click(timeout=2_500)
                    log.info("  → suggestion sélectionnée via %s", sel)
                    picked = True
                    break
                except Exception:  # noqa: BLE001
                    continue
            if not picked:
                try:
                    await target.locator(
                        TOOL_SEARCH_INPUT_SELECTORS[0]
                    ).first.press("Enter")
                    log.info("  → recherche validée (Entrée)")
                except Exception:  # noqa: BLE001
                    pass
            break

    if not filled:
        log.warning(
            "QUB : champ de recherche introuvable (sélecteurs à "
            "valider sur le VPS) — on capture la zone par défaut."
        )


async def _wait_for_capture(
    captured: List[dict], timeout_ms: int
) -> None:
    """Attend qu'au moins une réponse /map soit capturée (polling
    léger). Lève une exception claire au timeout — l'endpoint
    transforme ça en HTTP 502.
    """
    deadline = asyncio.get_event_loop().time() + (timeout_ms / 1000.0)
    while asyncio.get_event_loop().time() < deadline:
        if captured:
            return
        await asyncio.sleep(0.25)
    if not captured:
        raise RuntimeError(
            "QUB : aucune réponse /real-estate-service/v1/map "
            "capturée dans le délai imparti — login/flow de recherche "
            "à valider sur le VPS avec session QUB."
        )
