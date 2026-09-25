"""Canac (canac.ca) — relevé de prix sur les pages produit.

Résumé de l'enquête (2026-09-25, depuis le serveur, ``curl`` + Playwright) :

* Le site est une **SPA Angular (SAP Commerce Cloud / Spartacus)** lancée en
  2026. Un ``GET`` HTTP sur une page produit répond **200** mais renvoie
  seulement la coquille de l'application (~30 Ko, ``<app-root>`` vide,
  aucun JSON-LD, aucun prix). Tout le contenu vient du back-end **OCC**
  ``https://apisapcc.canac.ca/occ/v2/canac/…`` interrogé en XHR par la page.
* Cette API est **publique et accessible avec httpx** (aucune clé, aucun
  jeton : la page l'appelle en anonyme) → ``NEEDS_BROWSER = False`` et
  ``fetch()`` l'interroge directement :
  ``GET /occ/v2/canac/products/<code>?lang=fr&curr=CAD&store=<magasin>&fields=…``
  (il faut ``Accept: application/json`` : avec l'``Accept`` HTML de
  ``BROWSER_HEADERS`` l'API répond en XML). Le code produit est le dernier
  segment de l'URL, le magasin le segment après la langue (``2`` =
  L'Ancienne-Lorette, magasin par défaut du site ; ``49`` = Laval…).
  Un code inconnu → HTTP 400 ``{"errors":[{"type":"UnknownIdentifierError"…}]}``.
* URLs produit : ``https://www.canac.ca/canac/fr/<magasin>/p/<slug>/<code>``
  (le sitemap ``https://www.canac.ca/canac/sitemaps/Product-fr-CAD.xml``
  en liste ~17 600). Exemples réels utilisés :
    - https://www.canac.ca/canac/fr/2/p/gypse-regulier-leger-1-2-po-x-4-pi-x-8-pi/1248
      (gypse 1/2 po 4x8, prix régulier 16,75 $, en inventaire)
    - https://www.canac.ca/canac/fr/2/p/vis-a-gypse-1-1-4-po-n-6-pqt-8-000/1801
      (vis à gypse, 49,99 $)
    - https://www.canac.ca/canac/fr/2/p/compose-a-joints-de-gypse-a-prise-rapide-rapid-joint-90-8-17-kg/11
      (composé à joints, 23,49 $)
    - https://www.canac.ca/canac/fr/2/p/compose-a-joints-de-gypse-platinum-lite-17-l/55001606
      (composé à joints, LIQUIDATION : 20,00 $ au lieu de 22,99 $)
    - https://www.canac.ca/canac/fr/2/p/epinette-de-construction-2-po-x-4-po-x-8-pi-sec/248S
      (2x4x8, 3,79 $ le morceau)
    - https://www.canac.ca/canac/fr/2/p/boudin-de-mousse-isolante-1-po-x-10-pi/7201046
      (isolant, EN CIRCULAIRE : 2,49 $ au lieu de 3,89 $)
    - https://www.canac.ca/canac/fr/2/p/panneau-isolant-foamular-ngx-f-1000-2-po-x-2-pi-x-8-pi/100228
      (isolant rigide, 101,03 $)
    - https://www.canac.ca/canac/fr/2/p/peinture-au-latex-interieur-luxura-portes-moulures-blanc-et-couleurs-3-7-l/5011057
      (peinture, 48,95 $)
    - https://www.canac.ca/canac/fr/2/p/plancher-de-vinyle-spc-hesonite/22001769
      (plancher vinyle SPC, LIQUIDATION : 40,43 $ la boîte au lieu de 68,36 $,
      soit 1,65 $/pi² au lieu de 2,79 $/pi²)
  La recherche et les listes de catégorie passent par **Coveo**
  (``…org.coveo.com/rest/organizations/canacproductionhlzhy20d/commerce/v2/listing``)
  avec un jeton anonyme obtenu par ``/occ/v2/canac/coveo/token`` ; l'endpoint
  OCC ``products/search`` répond ``NullPointerError`` (inutilisable). Pour
  découvrir des URLs sans navigateur : le sitemap produit.

Méthode retenue : **API** (JSON OCC) via ``fetch()`` ; ``parse()`` lit aussi
le **HTML rendu** (capturé par Playwright / le VPS) au cas où.

Où sont les données :

* JSON OCC : ``price.value`` = prix régulier (condition SAP ``VKP0``) ;
  ``specialPrice.value`` = prix de vente courant quand il y a un rabais
  (condition ``VKA0``) — absent sinon. ``dividedPrice`` /
  ``dividedSpecialPrice`` = prix ramené à l'unité de mesure (ex. « /pi² »
  pour un plancher vendu à la boîte). ``tag`` / ``tagList`` : ``C`` = « En
  circulaire », ``L`` = « Liquidation », ``S`` = « Spécial », ``W`` =
  « Commande spéciale », ``PQ``/``FQ``/``CQ`` = produit du Québec.
  ``stock.stockLevelStatus`` : ``inStock`` / ``lowStock`` / ``outOfStock`` /
  ``availableByRequest`` (sur commande). ``name``, ``code`` (= SKU Canac,
  suffixe de l'URL), ``manufacturer``, ``modelID``, ``upcs``.
  ``belowMap`` = prix masqué sur le site (« Prix en magasin »).
  Exemple réel (boudin de mousse isolante 7201046, 2026-09-25) :
  ``price.formattedValue = "3,89 $"``, ``specialPrice.formattedValue = "2,49 $"``,
  ``tag = "C"``.
* HTML rendu : ``<canac-product-details-price>`` contient le badge
  ``<span class="canac-product-tag__text canac-product-tag__text--c">En circulaire</span>``
  puis ``<canac-product-price>`` avec ``<p class="canac-product-price__price">``
  → ``<span class="canac-product-price__price-number">2,49 $</span>``,
  ``<span class="canac-product-price__price-unit">/ Chaque</span>`` et, en
  rabais, le prix régulier barré ``<s class="canac-product-price__price-before">3,89 $</s>``.
  Quand le produit a un prix « divisé » (plancher), le premier ``<p>`` est le
  prix à l'unité de mesure (« 1,65 $ / Pied carré ») et un second
  ``<p class="… canac-product-price__price-secondary">`` porte le prix de
  l'unité vendue (« 40,43 $ / Boîte ») : on prend ce dernier comme ``price``
  (cohérent avec l'API) et l'autre va dans ``extra["divided_price"]``.
  Titre : ``<h1 class="canac-product-details-title__heading">`` ; SKU :
  « Code produit: 7201046 » dans ``canac-product-details-title__info`` ;
  stock : ``<p class="canac-product-stock … canac-product-stock--in-stock">``
  + libellés « En inventaire » / « Inventaire faible » / « Inventaire
  épuisé » / « Sur commande ». La page rendue ajoute aussi
  ``<meta property="product:price:amount" content="16,75 $">`` (repli).

Date de fin de rabais : **non affichée** sur la page produit du nouveau
site (ni dans l'API : aucun champ de date ; ``promotionDescription``, rendu
sous le titre « Promotion », était absent (``null``) sur tous les produits vérifiés,
y compris ceux « En circulaire »). Les dates de la circulaire hebdomadaire
ne vivent que dans l'iframe Flipp de la page « Circulaire ». L'ancien site
affichait « Prix régulier » barré et « jusqu'au … » ; par prudence,
``parse()`` cherche encore « jusqu'au <date> » / « valide jusqu'au … » /
« du … au … » / « until … » dans ``promotionDescription`` et dans la zone
prix/promotion du HTML, et renvoie la date si elle réapparaît un jour.
``on_sale`` est vrai quand ``specialPrice < price`` ou quand le badge
« En circulaire » / « Spécial » est présent.

Limites connues :

* Prix du magasin de l'URL (``store``) ; sur les produits testés le prix
  est le même dans tous les magasins, seul le stock diffère.
* ``purchasable = false`` signifie « pas vendu en ligne » (ex. gypse,
  liquidation), pas « indisponible » : on se fie à ``stockLevelStatus``.
* Montants HT (taxes ajoutées au panier), en CAD.
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import date
from typing import Any, Optional
from urllib.parse import urlparse

from . import BROWSER_HEADERS, FetchBlocked, PrixReleve, parse_date_any, parse_money

DOMAINS: tuple[str, ...] = ("canac.ca",)
#: Les balises OpenGraph de Canac portent le prix régulier : pas de repli générique.
GENERIC_FALLBACK: bool = False
NEEDS_BROWSER: bool = False

API_BASE = "https://apisapcc.canac.ca/occ/v2/canac"
DEFAULT_STORE = "2"  # L'Ancienne-Lorette (magasin par défaut du site)
API_FIELDS = (
    "code,name,url,urlSlug,manufacturer,modelID,ean,belowMap,purchasable,"
    "sapAddToCartDisabled,price(FULL),specialPrice(FULL),dividedPrice(FULL),"
    "dividedSpecialPrice(FULL),promotionDescription,tag,tagList,"
    "stock(stockLevelStatus,stockLevel,storeName),upcs(upc,main),"
    "xdChainStatusCode,xdChainStatusName,baseUnit,priceDivisorUnit,metaTitle"
)

TAG_LABELS = {
    "C": "En circulaire",
    "L": "Liquidation",
    "S": "Spécial",
    "W": "Commande spéciale",
    "PQ": "Produit du Québec",
    "FQ": "Fabriqué au Québec",
    "CQ": "Conçu au Québec",
}
_SALE_TAGS = {"C", "S"}

_TAG_RE = re.compile(r"<[^>]+>")
_PRICE_BLOCK_RE = re.compile(
    r"<canac-product-details-price\b.*?</canac-product-details-price>", re.S | re.I
)
_PRICE_COMP_RE = re.compile(r"<canac-product-price\b.*?</canac-product-price>", re.S | re.I)
_PRICE_P_RE = re.compile(
    r'<p[^>]+class="([^"]*canac-product-price__price[^"]*)"[^>]*>(.*?)</p>', re.S | re.I
)
_PRICE_NUMBER_RE = re.compile(
    r'<span[^>]+class="[^"]*canac-product-price__price-number[^"]*"[^>]*>(.*?)</span>', re.S | re.I
)
_PRICE_UNIT_RE = re.compile(
    r'<span[^>]+class="[^"]*canac-product-price__price-unit[^"]*"[^>]*>(.*?)</span>', re.S | re.I
)
_PRICE_BEFORE_RE = re.compile(
    r'<s[^>]+class="[^"]*canac-product-price__price-before[^"]*"[^>]*>(.*?)</s>', re.S | re.I
)
_BADGE_RE = re.compile(
    r'<span[^>]+class="([^"]*canac-product-tag__text[^"]*)"[^>]*>(.*?)</span>', re.S | re.I
)
_BADGE_CODE_RE = re.compile(r"canac-product-tag__text--([a-z]+)", re.I)
_TITLE_RE = re.compile(
    r'<h1[^>]+class="[^"]*canac-product-details-title__heading[^"]*"[^>]*>(.*?)</h1>', re.S | re.I
)
_INFO_RE = re.compile(
    r'<div[^>]+class="[^"]*canac-product-details-title__info[^"]*"[^>]*>(.*?)</div>', re.S | re.I
)
_STOCK_P_RE = re.compile(
    r'<p[^>]+class="([^"]*canac-product-stock[^"]*)"[^>]*>(.*?)</p>', re.S | re.I
)
_PROMO_BLOCK_RE = re.compile(
    r"<canac-product-details-promotion\b.*?</canac-product-details-promotion>", re.S | re.I
)
_OG_PRICE_RE = re.compile(
    r'<meta[^>]+property="product:price:amount"[^>]+content="([^"]*)"', re.I
)
_OG_TITLE_RE = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', re.I)

# « jusqu'au 2 octobre », « valide jusqu'au 2 octobre 2026 »,
# « du 25 septembre au 1er octobre », « until Oct 2 », « 2026-10-02 ».
_SALE_END_RE = re.compile(
    r"(?:jusqu['’]\s*au|jusqu['’]\s*à|valide\s+jusqu['’]\s*au|until|through|"
    r"du\s+\d{1,2}(?:er)?\s+[a-zéû]+\s+au)\s+"
    r"(\d{1,2}(?:er)?\s+[a-zéû]+\.?(?:\s+20\d{2})?|[a-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?,?(?:\s+20\d{2})?|20\d{2}-\d{2}-\d{2})",
    re.I,
)


# ───────────────────────── URL / API ─────────────────────────


def product_code_from_url(url: str) -> Optional[str]:
    """``…/p/<slug>/<code>`` → ``<code>`` (ex. ``1248``, ``248S``)."""
    path = urlparse(url).path.rstrip("/")
    m = re.search(r"/p/[^/]+/([A-Za-z0-9_.-]+)$", path)
    if m:
        return m.group(1)
    # URL courte ``/p/<code>`` (sans slug)
    m = re.search(r"/p/([A-Za-z0-9_.-]+)$", path)
    return m.group(1) if m else None


def store_from_url(url: str) -> str:
    """``/canac/fr/49/p/…`` → ``49`` ; sinon le magasin par défaut."""
    m = re.search(r"/canac/(?:fr|en)/(\d+)(?:/|$)", urlparse(url).path)
    return m.group(1) if m else DEFAULT_STORE


def api_url(url: str) -> Optional[str]:
    code = product_code_from_url(url)
    if not code:
        return None
    lang = "en" if re.search(r"/canac/en/", url) else "fr"
    return (
        f"{API_BASE}/products/{code}?lang={lang}&curr=CAD"
        f"&store={store_from_url(url)}&fields={API_FIELDS}"
    )


async def fetch(url: str) -> str:
    """Interroge l'API OCC publique de Canac (JSON) pour l'URL produit.
    Lève ``FetchBlocked`` si le site refuse (403 / captcha)."""
    import httpx  # dépendance du backend ; import local pour rester importable partout

    target = api_url(url)
    if not target:
        raise ValueError(f"URL produit Canac non reconnue (attendu …/p/<slug>/<code>) : {url}")
    headers = {**BROWSER_HEADERS, "Accept": "application/json", "Referer": "https://www.canac.ca/"}
    async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(target)
    if resp.status_code in (401, 403, 429) or "cf-chl" in resp.text[:2000] or "challenge-platform" in resp.text[:4000]:
        raise FetchBlocked(f"Canac API HTTP {resp.status_code} pour {target}")
    if resp.status_code >= 500:
        resp.raise_for_status()
    return resp.text


# ───────────────────────── parse ─────────────────────────


def parse(html: str, url: str = "") -> PrixReleve:
    """Lit prix / prix régulier / rabais / titre / SKU / stock d'un JSON OCC
    (``fetch()``) ou d'une page produit Canac **rendue**. Ne lève jamais."""
    try:
        return _parse(html or "", url or "")
    except Exception as exc:  # noqa: BLE001
        return PrixReleve(error=f"Lecture de la page Canac échouée : {exc}")


def _parse(text: str, url: str) -> PrixReleve:
    stripped = text.lstrip()
    if not stripped:
        return PrixReleve(error="Page vide.")
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return PrixReleve(error="JSON Canac illisible.")
        if isinstance(data, list):
            data = next((d for d in data if isinstance(d, dict)), None)
        if not isinstance(data, dict):
            return PrixReleve(error="JSON Canac inattendu.")
        return _parse_api(data, url)
    if stripped.startswith("<?xml") and "<product>" in stripped[:200]:
        return PrixReleve(error="Réponse XML de l'API Canac : demander Accept: application/json.")
    return _parse_html(text, url)


def _clean(s: str) -> str:
    """Espaces insécables et blancs multiples → espace simple."""
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _text(fragment: str) -> str:
    return _clean(_html.unescape(_TAG_RE.sub(" ", fragment)))


def _sale_end_from_text(text: str, *, today: Optional[date] = None) -> Optional[date]:
    if not text:
        return None
    m = _SALE_END_RE.search(text)
    return parse_date_any(m.group(1), today=today) if m else None


def _stock_from_status(status: str) -> Optional[bool]:
    s = (status or "").lower()
    if s in ("instock", "lowstock"):
        return True
    if s == "outofstock":
        return False
    return None  # availableByRequest (sur commande), inconnu…


def _parse_api(data: dict, url: str) -> PrixReleve:
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        e = errors[0] if isinstance(errors[0], dict) else {}
        return PrixReleve(error=f"API Canac : {e.get('message') or e.get('type') or errors[0]}")
    if "price" not in data and "code" not in data:
        return PrixReleve(error="JSON Canac sans produit (ni code ni prix).")

    price_o = data.get("price") if isinstance(data.get("price"), dict) else {}
    special_o = data.get("specialPrice") if isinstance(data.get("specialPrice"), dict) else {}
    regular = parse_money(price_o.get("value") if price_o.get("value") is not None else price_o.get("formattedValue"))
    special = parse_money(special_o.get("value") if special_o.get("value") is not None else special_o.get("formattedValue"))

    tag = str(data.get("tag") or "").upper() or None
    tags = [str(t).upper() for t in (data.get("tagList") or []) if t] or ([tag] if tag else [])
    extra: dict[str, Any] = {}
    if tags:
        extra["tag"] = tags[0]
        extra["tag_label"] = TAG_LABELS.get(tags[0], tags[0])
        if len(tags) > 1:
            extra["tags"] = tags
    if price_o.get("unit"):
        extra["unit"] = price_o.get("unit")
        extra["unit_name"] = price_o.get("unitName")
    if price_o.get("storeName"):
        extra["store"] = str(price_o["storeName"])
    for key, dst in (("dividedPrice", "divided_price"), ("dividedSpecialPrice", "divided_special_price")):
        d = data.get(key)
        v = parse_money(d.get("value")) if isinstance(d, dict) else None
        if v is not None:
            extra[dst] = v
            extra["divided_unit"] = d.get("unitName") or d.get("unit")
    if data.get("manufacturer"):
        extra["brand"] = data["manufacturer"]
    if data.get("modelID"):
        extra["model"] = data["modelID"]
    upcs = data.get("upcs")
    if isinstance(upcs, list):
        main = next((u.get("upc") for u in upcs if isinstance(u, dict) and u.get("main")), None) or next(
            (u.get("upc") for u in upcs if isinstance(u, dict) and u.get("upc")), None
        )
        if main:
            extra["upc"] = str(main)
    elif data.get("ean"):
        extra["upc"] = str(data["ean"])
    if data.get("purchasable") is not None:
        extra["vente_en_ligne"] = bool(data.get("purchasable"))
    if data.get("belowMap"):
        extra["prix_en_magasin"] = True
    if data.get("xdChainStatusName"):
        extra["chain_status"] = data["xdChainStatusName"]

    promo_desc = data.get("promotionDescription")
    promo_text = _text(str(promo_desc)) if promo_desc else ""
    if promo_text:
        extra["promotion"] = promo_text

    price: Optional[float]
    reg_out: Optional[float] = None
    on_sale = False
    if special is not None and regular is not None and special < regular:
        price, reg_out, on_sale = special, regular, True
    elif special is not None and regular is None:
        price = special
    else:
        price = regular
    if any(t in _SALE_TAGS for t in tags):
        on_sale = True

    title = _clean(str(data.get("name"))) if data.get("name") else None
    sku = str(data.get("code")) if data.get("code") else product_code_from_url(url)
    stock = data.get("stock") if isinstance(data.get("stock"), dict) else {}
    if stock.get("stockLevelStatus"):
        extra["availability"] = stock["stockLevelStatus"]
    if stock.get("stockLevel") is not None:
        extra["stock_level"] = stock["stockLevel"]

    if price is None or price <= 0:
        return PrixReleve(
            title=title,
            sku=sku,
            in_stock=_stock_from_status(stock.get("stockLevelStatus", "")),
            error="Aucun prix dans la réponse de l'API Canac (prix en magasin seulement ?).",
            extra=extra,
        )

    sale_end = _sale_end_from_text(promo_text) if on_sale or promo_text else None

    return PrixReleve(
        price=price,
        regular_price=reg_out,
        on_sale=on_sale,
        sale_end=sale_end,
        currency=str(price_o.get("currencyIso") or special_o.get("currencyIso") or "CAD"),
        title=title,
        sku=sku,
        in_stock=_stock_from_status(stock.get("stockLevelStatus", "")),
        method="api",
        extra=extra,
    )


def _price_rows(fragment: str) -> list[dict[str, Any]]:
    """Chaque ``<p class="canac-product-price__price …">`` → {number, unit, before, secondary}."""
    rows = []
    for classes, inner in _PRICE_P_RE.findall(fragment):
        num_m = _PRICE_NUMBER_RE.search(inner)
        if not num_m:
            continue
        unit_m = _PRICE_UNIT_RE.search(inner)
        before_m = _PRICE_BEFORE_RE.search(inner)
        rows.append(
            {
                "number": parse_money(_text(num_m.group(1))),
                "unit": _text(unit_m.group(1)).lstrip("/ ").strip() if unit_m else None,
                "before": parse_money(_text(before_m.group(1))) if before_m else None,
                "secondary": "price-secondary" in classes,
            }
        )
    return rows


def _parse_html(html: str, url: str) -> PrixReleve:
    extra: dict[str, Any] = {}
    # Repli sur le premier <canac-product-price> UNIQUEMENT avant le
    # carrousel de produits liés (sinon on lirait le prix d'un autre article).
    head = re.split(r"canac-product-list-item|<canac-product-carousel\b", html, 1)[0]
    block_m = _PRICE_BLOCK_RE.search(html) or _PRICE_COMP_RE.search(head)
    fragment = block_m.group(0) if block_m else ""

    badge_m = _BADGE_RE.search(fragment) if fragment else None
    if badge_m:
        code_m = _BADGE_CODE_RE.search(badge_m.group(1))
        code = code_m.group(1).upper() if code_m else ""
        label = _text(badge_m.group(2))
        if code:
            extra["tag"] = code
        extra["tag_label"] = label or TAG_LABELS.get(code, code)

    rows = _price_rows(fragment)
    main = next((r for r in rows if r["secondary"]), None)
    divided = None
    if main is not None:
        divided = next((r for r in rows if not r["secondary"]), None)
    else:
        main = rows[0] if rows else None

    price: Optional[float] = None
    regular: Optional[float] = None
    method = "html"
    if main is not None and main["number"] is not None and main["number"] > 0:
        price = main["number"]
        if main["before"] is not None and main["before"] > price:
            regular = main["before"]
        if main["unit"]:
            extra["unit_name"] = main["unit"]
    if divided is not None and divided["number"] is not None:
        if divided["before"] is not None:
            extra["divided_price"] = divided["before"]
            extra["divided_special_price"] = divided["number"]
        else:
            extra["divided_price"] = divided["number"]
        if divided["unit"]:
            extra["divided_unit"] = divided["unit"]

    if price is None:
        # Sur Canac, product:price:amount est le prix RÉGULIER, jamais le
        # prix payé : indice seulement, pas un prix.
        og = _OG_PRICE_RE.search(html)
        if og:
            extra["og_regular_price"] = parse_money(_html.unescape(og.group(1)))

    # Titre / SKU / modèle.
    title = None
    m = _TITLE_RE.search(html)
    if m:
        title = _text(m.group(1)) or None
    if not title:
        m = _OG_TITLE_RE.search(html)
        if m:
            title = re.sub(r"\s+-\s+Canac$", "", _text(m.group(1))).strip() or None
    sku = None
    for info in _INFO_RE.findall(html):
        t = _text(info)
        mm = re.match(r"Code produit\s*:\s*(\S+)", t, re.I)
        if mm:
            sku = mm.group(1)
            continue
        mm = re.match(r"Mod[èe]le\s*:\s*(.+)$", t, re.I)
        if mm:
            extra["model"] = mm.group(1).strip()
    if not sku:
        sku = product_code_from_url(url)

    # Disponibilité.
    in_stock: Optional[bool] = None
    sm = _STOCK_P_RE.search(html)
    if sm:
        classes, inner = sm.group(1).lower(), _text(sm.group(2))
        extra["availability"] = inner
        if "--in-stock" in classes or "--low-stock" in classes:
            in_stock = True
        elif "--out-of-stock" in classes:
            in_stock = False
        else:
            low = inner.lower()
            if "épuisé" in low or "epuise" in low or "out of stock" in low:
                in_stock = False
            elif "en inventaire" in low or "inventaire faible" in low or "in stock" in low:
                in_stock = True

    if price is None:
        if "<app-root" in html and not fragment and not title:
            return PrixReleve(
                sku=sku,
                error="Page Canac non rendue (coquille Angular sans prix) : utiliser fetch() (API OCC) ou le HTML rendu par navigateur.",
                extra=extra,
            )
        if fragment or title:
            return PrixReleve(
                title=title, sku=sku, in_stock=in_stock,
                error="Aucun prix affiché sur la page produit Canac (prix en magasin ?).",
                extra=extra,
            )
        return PrixReleve(error="Page inattendue : pas une fiche produit Canac.", extra=extra)

    on_sale = regular is not None or extra.get("tag") in _SALE_TAGS

    sale_end: Optional[date] = None
    promo_m = _PROMO_BLOCK_RE.search(html)
    promo_text = _text(promo_m.group(0)) if promo_m else ""
    if promo_text:
        extra["promotion"] = promo_text
        sale_end = _sale_end_from_text(promo_text)
    if sale_end is None and on_sale:
        sale_end = _sale_end_from_text(_text(fragment))

    return PrixReleve(
        price=price,
        regular_price=regular,
        on_sale=on_sale,
        sale_end=sale_end,
        currency="CAD",
        title=title,
        sku=sku,
        in_stock=in_stock,
        method=method,
        extra=extra,
    )


# ───────────── Recherche (prix de base automatique, 2026-09-26) ─────────────

COVEO_ORG = "canacproductionhlzhy20d"
COVEO_SEARCH = f"https://{COVEO_ORG}.org.coveo.com/rest/search/v2?organizationId={COVEO_ORG}"
_COVEO_TOKEN: dict[str, Any] = {"token": None, "exp": 0.0}


async def _coveo_token(client: "httpx.AsyncClient") -> str:
    import time

    if _COVEO_TOKEN["token"] and _COVEO_TOKEN["exp"] > time.time() + 300:
        return _COVEO_TOKEN["token"]
    r = await client.get(f"{API_BASE}/coveo/token")
    if r.status_code != 200:
        raise RuntimeError(f"jeton Coveo Canac : HTTP {r.status_code}")
    tok = str((r.json() or {}).get("token") or "")
    if not tok:
        raise RuntimeError("jeton Coveo Canac absent")
    _COVEO_TOKEN.update(token=tok, exp=time.time() + 6 * 3600)
    return tok


async def search(query: str, *, limit: int = 10) -> list:
    """Recherche Coveo du site (jeton anonyme public) : ``clickUri`` =
    page produit, ``raw.ec_name``, ``raw.ec_price`` (régulier),
    ``raw.ec_promo_price`` / ``ec_prd_discount_price`` (rabais). On relève
    ensuite le prix exact par l'API OCC du magasin."""
    import httpx

    from .recherche import Candidat

    body = {
        "q": query, "numberOfResults": int(limit), "locale": "fr-CA",
        "fieldsToInclude": [
            "ec_name", "ec_price", "ec_promo_price", "ec_prd_discount_price",
            "ec_product_id", "ec_brand", "ec_in_stock", "clickableuri",
        ],
    }
    async with httpx.AsyncClient(timeout=25.0, headers=BROWSER_HEADERS) as client:
        for tentative in (1, 2):
            tok = await _coveo_token(client)
            r = await client.post(
                COVEO_SEARCH, json=body,
                headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            )
            if r.status_code in (401, 403, 419) and tentative == 1:
                _COVEO_TOKEN.update(token=None, exp=0.0)  # jeton périmé → on en reprend un
                continue
            break
    if r.status_code != 200:
        raise RuntimeError(f"recherche Canac : HTTP {r.status_code}")
    try:
        results = r.json().get("results") or []
    except ValueError as exc:
        raise RuntimeError("recherche Canac : réponse non JSON") from exc
    out = []
    for res in results:
        uri = str(res.get("clickUri") or res.get("uri") or "")
        if not uri.startswith("http") or "/p/" not in uri:
            continue  # ex. « akeneo://… » (fiche interne sans page)
        raw = res.get("raw") or {}
        reg = parse_money(raw.get("ec_price"))
        promo = parse_money(raw.get("ec_promo_price")) or parse_money(raw.get("ec_prd_discount_price"))
        price = promo if (promo is not None and reg is not None and promo < reg) else reg
        title = str(raw.get("ec_name") or res.get("title") or "").replace(" ", " ").strip()
        out.append(Candidat(
            url=uri, title=title or uri, sku=(str(raw.get("ec_product_id")) if raw.get("ec_product_id") else None),
            price=price, regular_price=(reg if price is not None and reg is not None and reg > price else None),
            on_sale=bool(price is not None and reg is not None and price < reg),
            extra={"brand": raw.get("ec_brand")},
        ))
    return out
