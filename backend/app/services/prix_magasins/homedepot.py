"""Home Depot Canada (homedepot.ca) — relevé de prix d'une page produit.

Étude faite le 2026-09-25 depuis le serveur (curl / httpx / Playwright).

URLs produit testées (toutes ``200`` avec un User-Agent navigateur) :

* https://www.homedepot.ca/produit/cgc-sheetrock-1-2-po-x-4-pi-x-8-pi-panneau-de-gypse-ultraleger-resistant-a-la-moisissure/1000152285
  (gypse 1/2 po, prix régulier + promo de volume « ACHETEZ 20 OU PLUS, ÉCONOMISEZ 15% »)
* https://www.homedepot.ca/produit/paulin-vis-a-cloison-seche-6-x-1-1-4-pouces-a-tete-plate-phillips-drive-a-filetage-fin-8000pcs/1000102093
  (vis à gypse, prix régulier)
* https://www.homedepot.ca/produit/glidden-premium-ez-track-rose-a-blanc-peinture-et-appret-d-interieur-pour-plafonds-3-78-l/1000163427
  (peinture EN RABAIS : 35,97 $ au lieu de 57,47 $, badge « Nouveau prix réduit »)
* https://www.homedepot.ca/produit/cgc-sheetrock-compose-a-joints-a-prise-chimique-cgc-20-sac-de-1-25-kg/1000414532
* https://www.homedepot.ca/produit/owens-corning-isolant-rose-next-gen-fiberglas-r-12-15-po-x-47-po-x-3-5-po-97-9-pi2/1000406679
* https://www.homedepot.ca/produit/trafficmaster-latte-pour-plancher-vinyle-de-luxe-12-po-x-36-po-chene-de-yukon-24-pi2-boite/1000120138
* https://www.homedepot.ca/produit/porcupine-cedre-noueux-haut-de-gamme-2x4x8/1000167650

Les URLs se trouvent par les sitemaps (``/sitemap.xml`` →
``sitemap_product_fr.N.xml``, 20 000 produits chacun) ; la recherche du site
(``/fr/accueil/recherche.html?q=…``) est une coquille JavaScript sans lien
produit et interdite par ``robots.txt`` (``Disallow: /*?q=*``). Le code
produit est le nombre à 10 chiffres en fin d'URL (``…/1000152285``).

Ce que contient la page HTML brute (rendu côté serveur, Angular) :

* AUCUN bloc JSON-LD (contrairement à ce qui avait été observé plus tôt) ;
* des microdonnées ``itemprop="price"`` sur une partie des pages seulement
  (présentes sur la fiche de vis, absentes sur la fiche de peinture), avec
  ``priceValidUntil`` = date du jour (sans valeur) ;
* un état Angular ``<script id="hdca-state" type="application/json">``
  (caractères échappés ``&q;`` ``&a;`` ``&s;`` ``&l;`` ``&g;``) dont la clé
  ``product-<code>`` est la réponse de
  ``/api/catalogsvc/v1/products/pip/<code>`` : nom, fabricant, numéro de
  modèle, unité, stock EN LIGNE et un ``price`` de type ``BUY``.
  ATTENTION : ce prix est le prix « national » de la vitrine en ligne, PAS
  celui du magasin. Exemple réel : gypse 1000152285 → 15,86 $ dans la page,
  mais 32,98 $ au magasin 7128 (Montréal St-Henri) et 31,45 $ au 7085 ; la
  peinture 1000163427 → 59,97 $ dans la page, 35,97 $ (rabais) en magasin.

Méthode retenue : **API JSON** (``fetch()``), lisible avec httpx +
``BROWSER_HEADERS`` sans cookie ni jeton :

* ``GET /api/productsvc/v1/products-localized-basic?products=<code>&store=<magasin>&lang=fr``
  → ``optimizedPrice.displayPrice.value`` (prix payé aujourd'hui),
  ``optimizedPrice.wasprice.value`` (prix régulier barré, clé en minuscules),
  ``savingsAmount``, ``percentSaving`` (« 37% »), ``badge.type`` (``NLP`` =
  « Nouveau prix réduit »), ``storeStock.stockLevelStatus`` (stock du
  magasin), ``nationalPromotionMessages``. Sans ``displayPrice`` (statut
  ``OU`` / ``DC``) : le produit n'est pas offert dans ce magasin.
* ``GET /api/promosvc/v1/promotions?products=<code>&store=<magasin>&lang=fr``
  → promotions conditionnelles (``BULK_PRICING`` « Achetez 20 ou plus,
  économisez 15 % », ``BMSM`` « Dépensez 2500 $, obtenez 10 % »…) avec
  ``pipMessage`` / ``accordionMessage``.
* ``GET /api/catalogsvc/v1/products/pip/<code>?lang=fr`` → titre, modèle,
  unité (même contenu que ``hdca-state``).

Le magasin est choisi ainsi : paramètre ``?store=NNNN`` dans l'URL fournie,
sinon variable d'environnement ``HOMEDEPOT_STORE_ID``, sinon ``7128``
(Montréal St-Henri). Codes utiles : 7124 Laval, 7146 Montréal L'Acadie,
7149 Beaubien, 7162 Québec Lebourgneuf, 7163 Ste-Foy, 7189 St-Romuald,
7089 Sherbrooke (``/api/storesvc/v1/stores?lang=fr&currentPage=N``).

Comment la page annonce un rabais : un prix barré « Était 57,47 $ » et
« Économisez 21,50 $ (37 %) » sous le prix courant, plus le badge « Nouveau
prix réduit » ; dans l'API cela correspond à ``wasprice`` / ``savingsAmount``
/ ``percentSaving`` / ``badge.type = "NLP"``.

Date de fin de rabais : Home Depot n'expose AUCUNE date de fin pour un prix
réduit (ni dans l'API, ni dans la page, ni dans le code du site — la seule
clé datée est ``priceValidUntil`` = aujourd'hui). Seuls les messages de
promotions conditionnelles contiennent parfois une date en toutes lettres,
p. ex. ``accordionMessage`` d'une promo BMSM : « L'offre se termine le
1 novembre, 2026. » ou « se termine le 7 octobre, 2026 ». ``sale_end`` est
donc renseigné uniquement à partir de ces messages (« se termine le »,
« jusqu'au », « valide jusqu'au », « until »…), et reste ``None`` pour les
rabais « Nouveau prix réduit ».

Ce qui ne marche pas : la recherche du site et les pages de catégorie
(JavaScript pur), les prix par magasin dans le HTML brut, JSON-LD (absent).
Le rendu Playwright (Chromium headless) n'apporte rien : la page s'hydrate
(1,3 Mo de DOM) mais n'affiche pas le bloc prix sans contexte magasin, et le
site appelle lui-même ``products-localized-basic`` et ``promotions`` — d'où
``NEEDS_BROWSER = False``.

``parse()`` accepte : la chaîne JSON produite par ``fetch()`` (méthode
``api``), sinon une page HTML brute ou rendue (état ``hdca-state`` → prix
national, méthode ``html`` avec ``extra["price_scope"] = "national"`` ;
puis JSON-LD / OpenGraph / microdonnées via ``parse_generic`` ; puis les
libellés « Était … » / « Économisez … » d'un DOM rendu).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import httpx

from . import (
    BROWSER_HEADERS,
    FetchBlocked,
    PrixReleve,
    parse_date_any,
    parse_generic,
    parse_money,
)

DOMAINS: tuple[str, ...] = ("homedepot.ca",)
NEEDS_BROWSER: bool = False

#: Magasin par défaut (Montréal St-Henri) ; surchargé par ``?store=`` dans
#: l'URL ou ``HOMEDEPOT_STORE_ID``.
DEFAULT_STORE = "7128"
BASE = "https://www.homedepot.ca"
SOURCE_TAG = "homedepot-api"

_PRODUCT_ID_RE = re.compile(r"/(\d{10})(?:[/?#]|$)")
_STATE_RE = re.compile(
    r'<script[^>]+id=["\']hdca-state["\'][^>]*>(.*?)</script>', re.S | re.I
)
_TAG_RE = re.compile(r"<[^>]+>")
#: Débuts de phrase qui précèdent une date de fin dans les messages promo.
_END_HINT_RE = re.compile(
    r"\b(?:se termine|prend fin|jusqu[’'] ?(?:au|à|a)|valide jusqu|valable jusqu"
    r"|expire|until|ends?(?: on)?|through)\b\s*(?:le\s+)?[:\s]*([^.<\n]{3,60})",
    re.I,
)
#: Types de promotions qui ne portent aucune information de prix.
_PROMO_TYPES_IGNORED = {"MESSAGE", "ADP"}


# ─────────────────────────── helpers ───────────────────────────


def product_id_from_url(url: str) -> Optional[str]:
    """``…/produit/…/1000152285`` → ``"1000152285"``."""
    m = _PRODUCT_ID_RE.search(urlparse(url).path or "")
    return m.group(1) if m else None


def store_for(url: str) -> str:
    qs = parse_qs(urlparse(url).query or "")
    for key in ("store", "storeId", "magasin"):
        val = (qs.get(key) or [""])[0].strip()
        if val.isdigit():
            return val
    env = (os.environ.get("HOMEDEPOT_STORE_ID") or "").strip()
    return env if env.isdigit() else DEFAULT_STORE


def _money(node: Any) -> Optional[float]:
    """``{"value": 12.5, "formattedValue": "12,50 $"}`` → 12.5."""
    if isinstance(node, dict):
        v = node.get("value")
        if v is None:
            v = node.get("formattedValue")
        return parse_money(v)
    return parse_money(node)


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text or "")).strip()


def date_in_promo_text(text: str):
    """Date de fin lisible dans un message de promotion (« L'offre se
    termine le 1 novembre, 2026. » → 2026-11-01), sinon None."""
    plain = _strip_tags(text)
    for m in _END_HINT_RE.finditer(plain):
        seg = re.sub(r",\s*(20\d{2})", r" \1", m.group(1))
        d = parse_date_any(seg)
        if d:
            return d
    return None


def _stock_flag(status: Any) -> Optional[bool]:
    s = str(status or "").lower()
    if "instock" in s or s == "in_stock":
        return True
    if "outofstock" in s or s == "out_of_stock":
        return False
    return None


# ─────────────────────────── fetch ───────────────────────────


async def fetch(url: str) -> str:
    """Interroge les API JSON de Home Depot pour le produit de ``url`` et
    renvoie une chaîne JSON que ``parse()`` sait lire. Lève ``FetchBlocked``
    sur 403 / 429 / page anti-robot."""
    pid = product_id_from_url(url)
    if not pid:
        return json.dumps(
            {"source": SOURCE_TAG, "url": url,
             "error": "URL Home Depot sans code produit à 10 chiffres."}
        )
    store = store_for(url)
    headers = dict(BROWSER_HEADERS)
    headers["Accept"] = "application/json, text/plain, */*"
    headers["Referer"] = url

    async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
        results = await asyncio.gather(
            client.get(f"{BASE}/api/productsvc/v1/products-localized-basic",
                       params={"products": pid, "store": store, "lang": "fr"}),
            client.get(f"{BASE}/api/promosvc/v1/promotions",
                       params={"products": pid, "store": store, "lang": "fr"}),
            client.get(f"{BASE}/api/catalogsvc/v1/products/pip/{pid}", params={"lang": "fr"}),
            return_exceptions=True,
        )

    out: dict[str, Any] = {
        "source": SOURCE_TAG, "url": url, "product_id": pid, "store": store,
        "lang": "fr", "localized": None, "promotions": [], "pip": None, "errors": [],
    }
    labels = ("localized", "promotions", "pip")
    for label, res in zip(labels, results):
        if isinstance(res, Exception):
            out["errors"].append(f"{label}: {type(res).__name__}: {res}")
            continue
        if res.status_code in (401, 403, 429) or _looks_blocked(res):
            raise FetchBlocked(f"Home Depot a refusé l'appel {label} ({res.status_code}).")
        if res.status_code != 200:
            out["errors"].append(f"{label}: HTTP {res.status_code}")
            continue
        try:
            data = res.json()
        except ValueError:
            out["errors"].append(f"{label}: réponse non JSON")
            continue
        if label == "localized":
            items = data if isinstance(data, list) else [data]
            out["localized"] = next(
                (x for x in items if isinstance(x, dict) and str(x.get("productId")) == pid),
                items[0] if items and isinstance(items[0], dict) else None,
            )
        elif label == "promotions":
            items = data if isinstance(data, list) else [data]
            for x in items:
                if isinstance(x, dict) and str(x.get("productCode", pid)) == pid:
                    out["promotions"] = [
                        {k: v for k, v in p.items() if k != "yArticles"}
                        for p in (x.get("promotions") or []) if isinstance(p, dict)
                    ]
        elif label == "pip" and isinstance(data, dict):
            out["pip"] = _pip_subset(data)
    return json.dumps(out, ensure_ascii=False)


def _looks_blocked(res: httpx.Response) -> bool:
    ctype = res.headers.get("content-type", "")
    if "json" in ctype:
        return False
    body = res.text[:4000].lower()
    return any(w in body for w in ("access denied", "captcha", "are you a human", "incapsula", "akamai"))


_PIP_KEYS = (
    "code", "name", "manufacturer", "modelNumber", "price", "stock", "unitOfMeasure",
    "url", "productStatus", "buyable", "purchasable", "urls", "coverage",
)


def _pip_subset(pip: dict) -> dict:
    return {k: pip.get(k) for k in _PIP_KEYS if k in pip}


# ─────────────────────────── parse ───────────────────────────


def parse(html: str, url: str) -> PrixReleve:
    """JSON de ``fetch()`` ou page HTML → ``PrixReleve`` ; jamais d'exception."""
    try:
        text = (html or "").strip()
        if not text:
            return PrixReleve(error="Page vide.")
        if text[0] in "{[":
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            if isinstance(data, dict) and data.get("source") == SOURCE_TAG:
                return _parse_api(data, url)
            if data is not None:
                return _parse_raw_api(data, url)
        return _parse_html(text, url)
    except Exception as exc:  # noqa: BLE001 — contrat : jamais d'exception
        return PrixReleve(error=f"Lecture Home Depot échouée : {type(exc).__name__}: {exc}")


def _parse_api(data: dict, url: str) -> PrixReleve:
    pid = str(data.get("product_id") or product_id_from_url(url) or "") or None
    store = str(data.get("store") or "")
    if data.get("error") and not data.get("localized"):
        return PrixReleve(sku=pid, error=str(data["error"]), method="api")

    pip = data.get("pip") or {}
    title = _title_from_pip(pip)
    extra: dict[str, Any] = {"store": store, "product_id": pid, "price_scope": "store"}
    if pip.get("modelNumber"):
        extra["model"] = pip["modelNumber"]
    national = _money((pip.get("price") or {}))
    if national is not None:
        extra["national_price"] = national
    if data.get("errors"):
        extra["fetch_errors"] = data["errors"]

    promos = [p for p in (data.get("promotions") or []) if isinstance(p, dict)]
    sale_end = None
    if promos:
        extra["promotions"] = [
            {"type": p.get("promotionType"), "message": p.get("pipMessage") or p.get("stripeMessage")}
            for p in promos
        ]
        for p in promos:
            if str(p.get("promotionType") or "").upper() in _PROMO_TYPES_IGNORED:
                continue
            for key in ("accordionMessage", "pipMessage", "stripeMessage"):
                sale_end = date_in_promo_text(str(p.get(key) or ""))
                if sale_end:
                    break
            if sale_end:
                break

    loc = data.get("localized")
    if not isinstance(loc, dict):
        errs = data.get("errors") or []
        msg = (
            f"Appels API Home Depot échoués : {'; '.join(str(e) for e in errs)}"
            if errs
            else f"Produit {pid} inconnu de l'API de prix du magasin {store}."
        )
        return PrixReleve(title=title, sku=pid, method="api", extra=extra, error=msg)
    op = loc.get("optimizedPrice") or {}
    unit = (op.get("displayPrice") or {}).get("unitOfMeasure") or pip.get("unitOfMeasure")
    if unit:
        extra["unit"] = unit
    cp = op.get("comparablePrice")
    if isinstance(cp, dict) and _money(cp) is not None:
        extra["comparable_price"] = _money(cp)
        extra["comparable_unit"] = cp.get("comparableUnitofMeasure")
    status = op.get("productStatus") or loc.get("productStatus")
    if status:
        extra["product_status"] = status
    stock = _stock_flag((loc.get("storeStock") or {}).get("stockLevelStatus"))
    if stock is None:
        stock = _stock_flag((loc.get("stock") or {}).get("stockLevelStatus"))
    if stock is None:
        stock = _stock_flag((pip.get("stock") or {}).get("stockLevelStatus"))
    npm = loc.get("nationalPromotionMessages") or {}
    if npm.get("stripeMessage"):
        extra["national_promo"] = npm["stripeMessage"]
        if not promos:
            sale_end = date_in_promo_text(" ".join(
                [str(npm.get("stripeMessage") or "")] + [str(x) for x in (npm.get("accordionMessages") or [])]
            ))

    display = _money(op.get("displayPrice"))
    promo_price = _money(op.get("promoPrice"))
    was = _money(op.get("wasprice") or op.get("wasPrice"))
    savings = _money(op.get("savingsAmount"))
    badge = (op.get("badge") or {}).get("type") if isinstance(op.get("badge"), dict) else None
    if badge:
        extra["badge"] = badge
    if op.get("percentSaving"):
        extra["percent_saving"] = op["percentSaving"]

    price = promo_price if (promo_price is not None and promo_price > 0) else display
    if price is None:
        return PrixReleve(
            title=title, sku=pid, in_stock=stock, method="api", extra=extra,
            error=f"Aucun prix pour le magasin {store} (statut {status or '?'}) — produit non offert ou discontinué.",
        )
    regular = None
    if was is not None and was > price:
        regular = was
    elif promo_price is not None and display is not None and display > price:
        regular = display
    on_sale = regular is not None or (savings or 0) > 0 or str(badge or "").upper() in ("NLP", "SAV")
    if on_sale and regular is None and savings:
        regular = round(price + savings, 2)

    if sale_end and not on_sale:
        # Date d'une promo conditionnelle (« dépensez X, obtenez Y % ») :
        # pas la fin d'un rabais sur le prix affiché → information seulement.
        extra["promo_end"] = sale_end.isoformat()
    return PrixReleve(
        price=price,
        regular_price=regular,
        on_sale=on_sale,
        sale_end=(sale_end if on_sale else None),
        currency=str((op.get("displayPrice") or {}).get("currencyIso") or "CAD"),
        title=title,
        sku=pid,
        in_stock=stock,
        method="api",
        extra=extra,
    )


def _parse_raw_api(data: Any, url: str) -> PrixReleve:
    """Réponse brute de ``products-localized-basic`` (liste) ou de
    ``catalogsvc/pip`` (dict) collée telle quelle."""
    pid = product_id_from_url(url)
    if isinstance(data, list):
        cands = [x for x in data if isinstance(x, dict) and "optimizedPrice" in x]
        loc = next((x for x in cands if str(x.get("productId")) == str(pid)), None) or (
            cands[0] if cands and not pid else None
        )
        if loc:
            wrapped = {"source": SOURCE_TAG, "product_id": loc.get("productId") or pid,
                       "store": loc.get("storeId"), "localized": loc, "promotions": [], "pip": None}
            return _parse_api(wrapped, url)
    if isinstance(data, dict) and "price" in data and "code" in data:
        return _releve_from_pip(data, pid)
    return PrixReleve(error="JSON Home Depot non reconnu.")


def _title_from_pip(pip: dict) -> Optional[str]:
    name = str(pip.get("name") or "").strip()
    brand = str(pip.get("manufacturer") or "").strip()
    if not name:
        return brand or None
    if brand and not name.lower().startswith(brand.lower()):
        return f"{brand} {name}"
    return name


def _releve_from_pip(pip: dict, pid: Optional[str]) -> PrixReleve:
    """Prix NATIONAL de la vitrine (bloc ``hdca-state`` / API pip)."""
    price = _money(pip.get("price"))
    extra: dict[str, Any] = {
        "price_scope": "national",
        "warning": "Prix national de la vitrine en ligne (le prix du magasin peut différer) ; utiliser fetch() pour le prix par magasin.",
    }
    if pip.get("modelNumber"):
        extra["model"] = pip["modelNumber"]
    if pip.get("unitOfMeasure"):
        extra["unit"] = pip["unitOfMeasure"]
    stock = _stock_flag((pip.get("stock") or {}).get("stockLevelStatus"))
    sku = str(pip.get("code") or pid or "") or None
    if price is None:
        return PrixReleve(title=_title_from_pip(pip), sku=sku, in_stock=stock, method="html",
                          extra=extra, error="Bloc produit Home Depot sans prix.")
    return PrixReleve(
        price=price,
        currency=str((pip.get("price") or {}).get("currencyIso") or "CAD"),
        title=_title_from_pip(pip),
        sku=sku,
        in_stock=stock,
        method="html",
        extra=extra,
    )


_STATE_UNESCAPE = {"a": "&", "q": '"', "s": "'", "l": "<", "g": ">"}


def _load_state(html: str) -> Optional[dict]:
    m = _STATE_RE.search(html)
    if not m:
        return None
    # Décodage en UNE passe (comme Angular) : « &a;q; » reste « &q; ».
    raw = re.sub(r"&(a|q|s|l|g);", lambda mm: _STATE_UNESCAPE[mm.group(1)], m.group(1).strip())
    try:
        st = json.loads(raw)
    except ValueError:
        return None
    return st if isinstance(st, dict) else None


def _parse_html(html: str, url: str) -> PrixReleve:
    pid = product_id_from_url(url)
    state = _load_state(html)
    if state:
        pip = None
        if pid and isinstance(state.get(f"product-{pid}"), dict):
            pip = state[f"product-{pid}"]
        else:
            pip = next(
                (v for k, v in state.items()
                 if k.startswith("product-") and isinstance(v, dict) and "price" in v),
                None,
            )
        if pip:
            res = _releve_from_pip(pip, pid)
            if res.ok:
                return res

    generic = parse_generic(html, url)
    if generic.ok:
        if not generic.sku and pid:
            generic.sku = pid
        generic.extra.setdefault("price_scope", "national")
        return _enrich_rendered(generic, html)

    rendered = _parse_rendered(html, pid)
    if rendered.ok:
        return rendered
    return PrixReleve(
        sku=pid, method="html",
        error="Page Home Depot sans bloc hdca-state ni prix lisible (page inattendue ou bloquée).",
    )


#: Montant en dollars (« $ 12,99 » ou « 12,99 $ ») — jamais un pourcentage.
_AMT = r"(?:\$\s*(\d[\d\s\u00a0\u202f,.]*\d|\d)|(\d[\d\s\u00a0\u202f,.]*\d|\d)\s*\$)(?!\s*%)"
_WAS_RE = re.compile(r"(?:Était|Was)\s*:?\s*(?:<[^>]+>\s*)*" + _AMT)
_SAVE_RE = re.compile(r"(?:Économisez|Save)\s*:?\s*(?:<[^>]+>\s*)*" + _AMT)
_PRICE_ATTR_RE = re.compile(
    r'(?:data-price|data-display-price|aria-label="[^"]*?prix[^"]*?)[=\s:]*"?\s*\$?\s*([\d\s ,.]+\d)\s*\$?',
    re.I,
)


def _enrich_rendered(res: PrixReleve, html: str) -> PrixReleve:
    """Complète un relevé avec les libellés « Était » / « Économisez » d'un
    DOM rendu, s'ils sont présents."""
    was = _WAS_RE.search(html)
    if was:
        regular = parse_money(was.group(1) or was.group(2))
        if regular is not None and res.price is not None and regular > res.price:
            res.regular_price = regular
            res.on_sale = True
    if not res.on_sale:
        sav = _SAVE_RE.search(html)
        if sav:
            amount = parse_money(sav.group(1) or sav.group(2))
            if amount and res.price is not None:
                res.regular_price = round(res.price + amount, 2)
                res.on_sale = True
    return res


def _parse_rendered(html: str, pid: Optional[str]) -> PrixReleve:
    m = _PRICE_ATTR_RE.search(html)
    price = parse_money(m.group(1)) if m else None
    if price is None:
        return PrixReleve(error="Prix introuvable dans le DOM rendu.")
    res = PrixReleve(price=price, sku=pid, method="html", extra={"price_scope": "unknown"})
    return _enrich_rendered(res, html)


# ───────────── Recherche (prix de base automatique, 2026-09-26) ─────────────

SEARCH_API = "https://www.homedepot.ca/api/search/v1/search"


async def search(query: str, *, store: Optional[str] = None, limit: int = 10) -> list:
    """Moteur de recherche public (JSON) : ``code``, ``name``, ``url``
    (relative) et, en magasin, ``pricing.displayPrice.value``."""
    from .recherche import Candidat

    from urllib.parse import quote

    store = store or store_for("")
    url = f"{SEARCH_API}?q={quote(query)}&lang=fr&pageSize={int(limit)}&store={store}"
    async with httpx.AsyncClient(timeout=25.0, headers=BROWSER_HEADERS, follow_redirects=True) as client:
        r = await client.get(url)
    if r.status_code != 200:
        raise RuntimeError(f"recherche Home Depot : HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError as exc:
        raise RuntimeError("recherche Home Depot : réponse non JSON") from exc
    out = []
    for p in (data.get("products") or [])[:limit]:
        code = str(p.get("code") or "").strip()
        rel = str(p.get("url") or "").strip()
        if not code or not rel:
            continue
        pricing = p.get("pricing") or {}
        disp = pricing.get("displayPrice") if isinstance(pricing, dict) else None
        price = _money(disp.get("value")) if isinstance(disp, dict) else None
        name = " ".join(str(x) for x in (p.get("brand"), p.get("name")) if x).strip()
        stock = (p.get("storeStock") or {}).get("stockLevelStatus") if isinstance(p.get("storeStock"), dict) else None
        out.append(Candidat(
            url=("https://www.homedepot.ca" + rel) if rel.startswith("/") else rel,
            title=name or code, sku=code, price=price,
            in_stock=_stock_flag(stock),
            extra={"brand": p.get("brand"), "badges": p.get("badges")},
        ))
    return out
