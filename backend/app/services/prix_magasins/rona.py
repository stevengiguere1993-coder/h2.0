"""Rona / Réno-Dépôt (rona.ca, renodepot.com) — relevé de prix d'une page
produit.

Étude faite le 2026-09-25 depuis le serveur Kratos (curl / httpx /
Playwright headless / archives).

Accès depuis le serveur
-----------------------
* ``https://www.rona.ca/…`` répond **403** à tout client HTTP, même avec
  ``BROWSER_HEADERS`` complets (Accept, Accept-Language, Referer) : la
  réponse est la page « Un instant… / Just a moment… » de Cloudflare
  (challenge Turnstile, ``/cdn-cgi/challenge-platform/…``). Seul
  ``robots.txt`` et le CDN d'images (``cdn.rona.ca``) passent.
* Chromium headless (Playwright) reste bloqué sur le challenge après 60 s
  (Turnstile détecte le navigateur automatisé). Aucun contournement n'a
  été tenté (pas de résolution de captcha, pas de rotation de proxy).
* Aucune API JSON publique n'est atteignable sans passer le challenge :
  les servlets WebSphere Commerce du site (``RonaProdDetailStoresInventory
  Overlay``, ``RonaAjaxCatalogSearchView``…) renvoient le même 403.
* ``https://www.renodepot.com`` est injoignable d'ici (le proxy de sortie
  refuse le CONNECT). Réno-Dépôt tourne sur la même plateforme que Rona
  (même groupe, même WebSphere Commerce « RONAStorefrontAssetStore ») ;
  le parseur est écrit pour les deux mais n'a pu être vérifié que sur
  des pages rona.ca.

→ ``NEEDS_BROWSER = True`` : le serveur passe par le VPS Playwright (vrai
navigateur) et envoie ici le HTML **rendu**. Pas de ``fetch()``.

Pages étudiées
--------------
Faute d'accès direct, l'analyse et les fixtures reposent sur des captures
**réelles** des pages produit rona.ca faites par la Wayback Machine les
21-23 octobre 2025 (``web.archive.org/web/<ts>id_/<url>`` = HTML brut tel
que servi par rona.ca, magasin sélectionné « RONA+ Galeries d'Anjou »,
n° 41110). URLs (le code produit est le nombre en fin d'URL) :

* https://www.rona.ca/fr/produit/gypse-resistant-au-feu-1-2-x-4-x-8-640242-0932006
  (gypse 1/2 po x 4 x 8 → 26,98 $ « Chacun », prix régulier)  [fixture rona_1]
* https://www.rona.ca/fr/produit/2-po-x-4-po-x-8-pi-bois-depinette-grade-stud-ep248s-0971047
  (2x4x8 → 3,81 $, prix régulier)
* https://www.rona.ca/fr/produit/panneau-de-cloison-seche-en-gypse-leger-1-2-po-x-4-pi-x-10-pi-easi-lite-par-certainteed-640251-61635036
  (gypse 1/2 x 4 x 10 → 21,26 $)
* https://www.rona.ca/fr/produit/clous-a-gypse-a-tete-plate-duchesne-electrogalvanises-275-par-paquet-1-1-4-po-l-20410760-22645122
  (clous à gypse → 6,79 $ « Boite »)
* https://www.rona.ca/fr/produit/compose-a-joints-leger-premelange-tout-usage-le-secret-des-pros-par-c…-09935151
  (composé à joints → 39,54 $)
* https://www.rona.ca/fr/produit/isolant-de-construction-en-fibre-de-verre-johns-manville-r12-106-67-pi2-20-morceaux-murs-a-ossature-dacier-90017881-54835734
  (isolant R12 → 57,86 $)
* https://www.rona.ca/fr/produit/peinture-a-email-teintable-pour-meubles-et-armoires-valspar-base-1-satine-acrylique-3-78-l-14495983
  (peinture → 91,99 $)
* https://www.rona.ca/fr/produit/plancher-stratifie-alara-oak-de-mono-serra-systeme-dencliquetage-fibres-haute-densite-grade-ac3-boite-de-10-80205-84666038
  (plancher stratifié EN RABAIS : 31,71 $ la boîte au lieu de 39,64 $,
  « Rabais de 20% jusqu'au 5 nov. 2025 »)  [fixture rona_2]
* https://www.rona.ca/fr/produit/aspirateur-balai-cordzero-thinq-kompressor-de-lg-sans-fil-44-po-a927kgms-30895353
  (LIQUIDATION : 399,50 $ au lieu de 799,00 $, « Rabais de 399,50 $ »,
  sans date de fin)  [fixture rona_3]
* Autres promos vues : « Rabais de 100 $ jusqu'au 5 nov. 2025 »
  (00277973, 179 $ / 279 $), « Rabais de 44,99 $ jusqu'au 29 oct. 2025 »
  (22465115, 109 $ / 153,99 $), « Rabais de 300 $ jusqu'au 5 août 2026 »
  (11975498).

Ce que contient la page HTML (rendu côté serveur, WebSphere Commerce)
---------------------------------------------------------------------
* JSON-LD : seulement un ``BreadcrumbList`` — **pas de Product/Offer**.
* Microdonnées ``itemprop="offers"`` (``price``, ``priceCurrency``,
  ``availability``) : **prix NON fiable** — il diffère souvent du prix
  affiché (1,69 vs 1,87 $ ; 2,99 vs 6,79 $ ; 349,99 vs 399,50 $), sans
  doute un prix d'un autre magasin / de la vitrine. Pas utilisé ici (seul
  ``parse_generic`` y recourt en dernier ressort).
* ``<script type="application/json" id="js-product-ddo">`` : objet
  analytique du produit — ``partNumber`` (SKU), ``name``, ``brand``,
  ``manufacturerPartNumber``, ``effectivePrice`` (prix payé),
  ``regularPrice``, ``rebateAmout`` (sic). C'est la source principale.
  Absent sur les pages « famille » à variantes (ex. 332016078).
* ``ddo_price_obj["productSellingPrice"] = '31.71'`` et
  ``["productWasPrice"] = '39.64'`` (script inline) : même information.
* Bloc prix ``<!-- BEGIN RonaProdDetailPriceSnippet.jsp -->`` :
  ``.price-box`` (classe ``price-box--rebate`` si rabais),
  ``.price-box__price__amount__integer`` / ``__decimal`` (prix affiché),
  ``.price-box__price__spec`` (unité : « Chacun », « Boite », « pi ca »),
  ``.price-box__regularPrice`` (prix régulier barré, « 39,64 $ »),
  ``.price-box__rebate`` → ``__Label`` « Rabais de », ``__amount``
  (« 20% », « 100 $ », « 399,50 $ »), ``__enddate`` (« jusqu'au 5 nov.
  2025 »). Pour les planchers, le prix principal est au pi² et le prix de
  la boîte (celui qu'on paie, = ``effectivePrice``) est dans
  ``.price-box__secondaryUomPrimaryPrice--rebate`` / ``--no-rebate`` avec
  ``--regularPrice`` et ``--spec`` (« Boite »).
* Icônes : ``page-product__image-container__clearance`` (liquidation),
  ``__special-value`` avec ``price_drop_fr.png`` (baisse de prix).
* Disponibilité : commentaire de débogage ``ProductDisplayRuleResult
  [… inventoryAvailable=true … inventoryQuantity=52 …]`` (stock du magasin
  sélectionné) et ``Offer[… Type:P …]`` (P = promo, L = liquidation,
  null = régulier). Le magasin : ``selectedStoreId = "41110"`` et
  ``var _selectedStore = { name:"RONA+ Galeries d'Anjou" … }``.

Comment la page annonce un rabais et sa date de fin
---------------------------------------------------
Sous le prix, en rouge : « Rabais de 20% jusqu'au 5 nov. 2025 » ou
« Rabais de 100 $ jusqu'au 5 nov. 2025 » (``.price-box__rebate__amount``
+ ``.price-box__rebate__enddate``), le prix régulier barré à côté du prix
courant. Une liquidation affiche « Rabais de 399,50 $ » sans date. Les
dates sont lues par ``parse_date_any`` (« jusqu'au 5 nov. 2025 »,
« until Nov. 5, 2025 » côté anglais — non vérifié sur une page /en/).

Cas sans prix (erreur explicite, jamais d'exception)
-----------------------------------------------------
* « Voir prix et détails en magasin » (``priceDisplayable=false``,
  ``productSellingPrice = ''``) : Rona masque le prix en ligne
  (ex. gypse extérieur GlasRoc 09935154) → ``extra["price_hidden"]``.
* Famille à variantes (``itemtype=AggregateOffer`` avec ``lowPrice`` /
  ``highPrice`` / ``offerCount``, pas de ``js-product-ddo``) : le prix
  n'apparaît qu'après le choix d'une variante par JavaScript (ex. vis à
  bois Reliable 1399402, 8 articles de 3,09 à 4,49 $) →
  ``extra["price_range"]`` ; il faut l'URL de l'article précis.
* Page de challenge Cloudflare → ``extra["blocked"]``.

Validation : sur 201 pages produit rona.ca capturées (oct. 2025), 181
sont lues (prix = ``effectivePrice`` dans 100 % des cas où il existe,
9 rabais dont 8 avec date de fin), 19 sont des familles à variantes et
1 a le prix masqué.

Ce qui ne marche pas : tout accès HTTP direct depuis le serveur
(Cloudflare), Chromium headless d'ici, la recherche du site
(``/fr/recherche`` interdite par robots.txt), le prix des microdonnées.
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import date
from typing import Any, Optional
from urllib.parse import urlparse

from . import PrixReleve, parse_date_any, parse_money

DOMAINS: tuple[str, ...] = ("rona.ca", "renodepot.com")
#: Cloudflare Turnstile bloque httpx ET Chromium headless depuis le serveur.
#: Les microdonnées itemprop=price de Rona sont un prix d'une autre vitrine : jamais de repli générique.
GENERIC_FALLBACK: bool = False
NEEDS_BROWSER: bool = True

_CHALLENGE_MARKERS = (
    "challenges.cloudflare.com",
    "cdn-cgi/challenge-platform",
    "<title>un instant",
    "<title>just a moment",
    "attention required! | cloudflare",
)

_SNIPPET_BEGIN = "<!-- BEGIN RonaProdDetailPriceSnippet.jsp -->"
_SNIPPET_END = "<!-- END RonaProdDetailPriceSnippet.jsp -->"

_DATE_HINT_RE = re.compile(
    r"(?:jusqu[’']au|jusqu[’']à|valide jusqu[’']au|se termine le|until|valid until|ends)\s*"
    r"(?:le\s+)?([^<\n]{3,40})",
    re.IGNORECASE,
)


# ───────────────────────── utilitaires ─────────────────────────


def is_blocked_page(html: str) -> bool:
    """Page de challenge Cloudflare (« Un instant… ») plutôt qu'une fiche."""
    head = (html or "")[:20000].lower()
    return any(m in head for m in _CHALLENGE_MARKERS)


def product_id_from_url(url: str) -> Optional[str]:
    """``…/produit/gypse-…-640242-0932006`` → ``0932006``."""
    path = urlparse(url or "").path.rstrip("/")
    m = re.search(r"-(\d{5,12})$", path)
    return m.group(1) if m else None


def _text(fragment: Optional[str]) -> Optional[str]:
    if fragment is None:
        return None
    s = re.sub(r"<[^>]+>", " ", fragment)
    s = _html.unescape(s).replace("\xa0", " ").replace("\u202f", " ").replace("\u2009", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _find(pattern: str, html: str, flags: int = re.S | re.I) -> Optional[str]:
    m = re.search(pattern, html, flags)
    return m.group(1) if m else None


def _class_text(cls: str, seg: str, *, exclude: str = "") -> Optional[str]:
    """Texte du premier élément dont la classe contient ``cls`` (mot entier).
    ``exclude`` : sous-chaîne de classe à ignorer (ex. ``--regularPrice``)."""
    for m in re.finditer(
        r"<(span|div|sup|p)\b([^>]*\bclass=\"[^\"]*\b" + re.escape(cls) + r"(?![\w-])[^\"]*\"[^>]*)>(.*?)</\1>",
        seg,
        re.S | re.I,
    ):
        if exclude and exclude in m.group(2):
            continue
        t = _text(m.group(3))
        if t:
            return t
    return None


def _ddo(html: str) -> dict[str, Any]:
    raw = _find(r"<script[^>]+id=\"js-product-ddo\"[^>]*>(.*?)</script>", html)
    if not raw:
        return {}
    try:
        data = json.loads(_html.unescape(raw.strip()))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _price_snippet(html: str) -> str:
    i = html.find(_SNIPPET_BEGIN)
    if i >= 0:
        j = html.find(_SNIPPET_END, i)
        # On garde le marqueur de fin : sa présence prouve que le bloc
        # prix est complet (page non tronquée).
        return html[i: j + len(_SNIPPET_END) if j > i else i + 20000]
    m = re.search(r"<div[^>]+class=\"[^\"]*price-box--product-page[^\"]*\"", html)
    if m:
        return html[m.start(): m.start() + 20000]
    m = re.search(r"class=\"[^\"]*price-box\b", html)
    return html[m.start(): m.start() + 20000] if m else ""


def _display_price(seg: str) -> Optional[float]:
    """Prix composé des spans integer / decimal du premier ``price-box__price__amount``."""
    m = re.search(
        r"price-box__price__amount__integer\"[^>]*>\s*([\d\s\xa0,.]*?)\s*<"
        r"(?:(?!price-box__price__amount__integer).)*?"
        r"price-box__price__amount__decimal\"[^>]*>\s*(\d{1,2})\s*<",
        seg,
        re.S,
    )
    if m:
        whole = re.sub(r"[^\d]", "", m.group(1))
        if whole:
            return round(float(f"{whole}.{m.group(2)}"), 2)
    if _SNIPPET_BEGIN in seg and _SNIPPET_END not in seg:
        return None  # bloc tronqué (rendu interrompu) : mieux vaut une erreur qu'un prix faux
    whole = _find(r"price-box__price__amount__integer\"[^>]*>\s*([\d\s\xa0,.]+?)\s*<", seg)
    if whole:
        digits = re.sub(r"[^\d]", "", whole)
        if digits:
            return round(float(digits), 2)
    return None


def _bool(s: Optional[str]) -> Optional[bool]:
    if s is None:
        return None
    return {"true": True, "false": False}.get(s.lower())


# ───────────────────────── parse ─────────────────────────


def parse(html: str, url: str) -> PrixReleve:
    """Lit une page produit rona.ca / renodepot.com (HTML rendu ou brut).
    Jamais d'exception : page inattendue → ``PrixReleve(error=…)``."""
    try:
        return _parse(html or "", url or "")
    except Exception as exc:  # noqa: BLE001 — contrat : jamais d'exception
        return PrixReleve(error=f"Lecture de la page Rona échouée : {exc}")


def _parse(html: str, url: str) -> PrixReleve:
    stripped = html.strip()
    if not stripped:
        return PrixReleve(error="Page vide.")
    if stripped.startswith("{"):
        return _parse_json(stripped, url)
    # Cloudflare injecte son script sur TOUTES les pages : on ne conclut au
    # blocage que si la page n'a aucun contenu produit.
    if is_blocked_page(html) and "js-product-ddo" not in html and "productDetails" not in html:
        return PrixReleve(
            error="Page bloquée par Cloudflare (challenge anti-robot « Un instant… ») : "
                  "relevé à faire par le navigateur du VPS.",
            extra={"blocked": True},
        )

    ddo = _ddo(html)
    seg = _price_snippet(html)
    extra: dict[str, Any] = {}

    # ── prix affiché dans le bloc prix ──
    shown_price = _display_price(seg)
    shown_unit = _class_text("price-box__price__spec", seg)
    shown_regular = parse_money(_class_text("price-box__regularPrice", seg))
    # unité de vente secondaire (planchers : pi² affiché, boîte vendue)
    sec_price = parse_money(
        _class_text("price-box__secondaryUomPrimaryPrice--rebate", seg)
        or _class_text("price-box__secondaryUomPrimaryPrice--no-rebate", seg)
    )
    sec_regular = parse_money(_class_text("price-box__secondaryUomPrimaryPrice--regularPrice", seg))
    sec_unit = _class_text("price-box__secondaryUomPrimaryPrice--spec", seg)

    rebate_amount = _class_text("price-box__rebate__amount", seg)
    rebate_end = _class_text("price-box__rebate__enddate", seg)
    rebate_label = _class_text("price-box__rebate", seg, exclude="price-box__rebate__")
    has_rebate_class = bool(re.search(r"class=\"[^\"]*price-box--rebate\b", seg))

    # ── scripts de données ──
    selling = parse_money(_find(r"productSellingPrice\"\]\s*=\s*'([^']*)'", html))
    was = parse_money(_find(r"productWasPrice\"\]\s*=\s*'([^']*)'", html))
    data_price = data_regular = data_type = None
    for m in re.finditer(r"<div\b[^>]*\bdata-price-regular=\"[^\"]*\"[^>]*>", html):
        tag = m.group(0)
        if "product-tile" in tag:
            continue
        data_price = parse_money(_find(r"\bdata-price=\"([^\"]*)\"", tag))
        data_regular = parse_money(_find(r"\bdata-price-regular=\"([^\"]*)\"", tag))
        data_type = _find(r"\bdata-price-type=\"([^\"]*)\"", tag)
        break

    # ── choix du prix payé et du prix régulier ──
    ddo_price = parse_money(ddo.get("effectivePrice"))
    ddo_regular = parse_money(ddo.get("regularPrice"))
    price: Optional[float] = None
    source = ""
    for cand, label in (
        (ddo_price, "js-product-ddo.effectivePrice"),
        (selling, "ddo_price_obj.productSellingPrice"),
        (data_price, "data-price"),
        (sec_price, "price-box secondaryUom"),
        (shown_price, "price-box"),
    ):
        if cand is not None and cand > 0:
            price, source = cand, label
            break
    if price is None:
        return _no_price(html, ddo, url, seg)

    regular: Optional[float] = None
    for cand in (ddo_regular, was, data_regular, sec_regular,
                 shown_regular if sec_price is None else None):
        if cand is not None and cand > price:
            regular = cand
            break

    on_sale = regular is not None or has_rebate_class or bool(rebate_amount)

    # ── date de fin du rabais ──
    sale_end: Optional[date] = parse_date_any(rebate_end) if rebate_end else None
    if sale_end is None and on_sale:
        m = _DATE_HINT_RE.search(_text(seg) or "")
        if m:
            sale_end = parse_date_any(m.group(1))

    # ── unité, badges, type de prix ──
    unit = sec_unit or shown_unit
    if unit:
        extra["unit"] = unit
    if sec_price is not None and shown_price is not None and shown_unit:
        extra["unit_price"] = {"price": shown_price, "regular": shown_regular, "unit": shown_unit}
    if rebate_amount:
        extra["rebate"] = rebate_amount
    if rebate_label:
        extra["rebate_label"] = rebate_label  # ex. « Rabais de 20% jusqu'au 5 nov. 2025 »
    if re.search(r"page-product__image-container__clearance", html):
        extra["clearance"] = True
    if re.search(r"page-product__image-container__special-value[^>]*>\s*<img[^>]*price_drop", html):
        extra["price_drop"] = True
    offer_type = _find(r"Offer\[[^\]]*\bType:([A-Za-z]+)", html)
    if offer_type and offer_type.lower() != "null":
        extra["price_type"] = offer_type  # P = promo, L = liquidation
    elif data_type:
        extra["price_type"] = data_type
    extra["price_source"] = source

    # ── magasin / stock ──
    store_obj = _find(r"_selectedStore\s*=\s*(\{.*?\})\s*;", html) or ""
    store_id = (_find(r"selectedStoreId\s*=\s*\"(\d+)\"", html)
                or _find(r"\bid\s*:\s*\"(\d+)\"", store_obj))
    store_name = _find(r"\bname\s*:\s*\"((?:[^\"\\]|\\.)*)\"", store_obj)
    if store_id:
        extra["store_id"] = store_id
    if store_name:
        extra["store_name"] = _html.unescape(store_name.replace("\\'", "'").replace('\\"', '"'))
    in_stock = _bool(_find(r"\binventoryAvailable=(true|false)", html))
    qty = _find(r"\binventoryQuantity=(\d+)", html)
    if qty is not None:
        extra["store_qty"] = int(qty)
    if in_stock is None:
        avail = (_find(r"itemprop=\"availability\"[^>]*(?:href|content)=\"([^\"]+)\"", html) or "").lower()
        in_stock = True if "instock" in avail else (False if "outofstock" in avail else None)

    brand = ddo.get("brand")
    if brand:
        extra["brand"] = str(brand)
    model = ddo.get("manufacturerPartNumber") or _find(r"itemprop=\"mpn\"\s+content=\"([^\"]+)\"", html)
    if model:
        extra["model"] = _html.unescape(str(model))

    return PrixReleve(
        price=price,
        regular_price=regular,
        on_sale=on_sale,
        sale_end=sale_end,
        currency="CAD",
        title=_title(html, ddo),
        sku=_sku(html, ddo, url),
        in_stock=in_stock,
        method="html",
        extra=extra,
    )


def _no_price(html: str, ddo: dict[str, Any], url: str, seg: str) -> PrixReleve:
    """Page produit reconnue mais sans prix lisible : dire pourquoi."""
    base = dict(title=_title(html, ddo), sku=_sku(html, ddo, url), method="html")
    seg_text = _text(seg) or ""
    if re.search(r"priceDisplayable=false", html) or re.search(
        r"voir prix et d[ée]tails en magasin|see price and details in store", seg_text, re.I
    ):
        return PrixReleve(
            error="Prix non affiché en ligne par Rona (« Voir prix et détails en magasin »).",
            extra={"price_hidden": True}, **base,
        )
    low = parse_money(_find(r"itemprop=\"lowPrice\"\s+content=\"([^\"]+)\"", html))
    high = parse_money(_find(r"itemprop=\"highPrice\"\s+content=\"([^\"]+)\"", html))
    count = _find(r"itemprop=\"offerCount\"\s+content=\"(\d+)\"", html)
    if low is not None:
        rng = f"{low:.2f}" if high in (None, low) else f"{low:.2f} à {high:.2f}"
        return PrixReleve(
            error=f"Famille de produits à variantes ({count or '?'} articles, {rng} $) : "
                  "le prix s'affiche seulement après le choix d'une variante — utiliser "
                  "l'URL de l'article précis.",
            extra={"price_range": [low, high if high is not None else low],
                   "variants": int(count) if count else None},
            **base,
        )
    if "productDetails" not in html and "js-product-ddo" not in html:
        return PrixReleve(error="Page inattendue : pas une fiche produit Rona (bloc prix absent).", **base)
    return PrixReleve(error="Bloc prix Rona introuvable (fiche produit sans prix ou page non rendue).", **base)


def _title(html: str, ddo: dict[str, Any]) -> Optional[str]:
    t = _text(_find(r"<h1[^>]*class=\"[^\"]*page-product__title[^\"]*\"[^>]*>(.*?)</h1>", html))
    if t:
        return t
    if ddo.get("name"):
        return _text(str(ddo["name"]))
    t = _text(_find(r"<title>(.*?)</title>", html))
    if t:
        return re.sub(r"\s*\|\s*(RONA|R[ée]no-D[ée]p[oô]t)\s*$", "", t, flags=re.I) or None
    return None


def _sku(html: str, ddo: dict[str, Any], url: str) -> Optional[str]:
    for cand in (
        ddo.get("partNumber"),
        _find(r"class=\"productDetails[^\"]*\"[^>]*\bdata-sku=\"([^\"]+)\"", html),
        _find(r"itemprop=\"sku\"\s+content=\"([^\"]+)\"", html),
        product_id_from_url(url),
    ):
        if cand:
            return str(cand).strip()
    return None


def _parse_json(raw: str, url: str) -> PrixReleve:
    """Objet ``js-product-ddo`` (ou équivalent) fourni tel quel."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return PrixReleve(error=f"JSON illisible : {exc}")
    if not isinstance(data, dict):
        return PrixReleve(error="JSON inattendu (objet attendu).")
    price = parse_money(data.get("effectivePrice") or data.get("price"))
    if price is None:
        return PrixReleve(error="JSON sans effectivePrice.")
    regular = parse_money(data.get("regularPrice"))
    if regular is not None and regular <= price:
        regular = None
    sale_end = parse_date_any(data.get("saleEnd") or data.get("rebateEndDate"))
    return PrixReleve(
        price=price,
        regular_price=regular,
        on_sale=regular is not None or bool(data.get("rebateAmout") or data.get("rebateAmount")),
        sale_end=sale_end,
        title=(str(data["name"]) if data.get("name") else None),
        sku=(str(data["partNumber"]) if data.get("partNumber") else product_id_from_url(url)),
        method="api",
        extra={k: data[k] for k in ("brand", "manufacturerPartNumber") if data.get(k)},
    )


# ───────────── Recherche (prix de base automatique, 2026-09-26) ─────────────

SEARCH_URL = "https://www.rona.ca/fr/recherche?q={q}"
_TILE_LINK_RE = re.compile(
    r"<a\b[^>]*href=\"(?P<href>(?:https://www\.rona\.ca)?/fr/produit/[^\"#?]+?-(?P<pid>\d{5,}))\"[^>]*>(?P<inner>.*?)</a>",
    re.S | re.I,
)
_MONEY_TXT_RE = re.compile(r"(\d{1,3}(?:[   ]\d{3})*(?:[.,]\d{2})?)\s*\$")


async def search(query: str, *, limit: int = 10) -> list:
    """Page de résultats RENDUE par le navigateur du VPS (Cloudflare bloque
    tout client direct). On lit les tuiles : lien produit ``/fr/produit/
    <slug>-<id>``, titre, premier montant en $ qui suit."""
    from urllib.parse import quote

    from app.integrations.scraping_proxy import fetch_rendered_html

    from .recherche import Candidat

    html = await fetch_rendered_html(SEARCH_URL.format(q=quote(query)), wait_ms=2500)
    if html is None:
        raise RuntimeError("recherche Rona : le VPS de scraping n'est pas configuré")
    if not html or is_blocked_page(html) and "/fr/produit/" not in html:
        raise RuntimeError("recherche Rona : page bloquée (Cloudflare)")
    out: list[Candidat] = []
    vus: set[str] = set()
    for m in _TILE_LINK_RE.finditer(html):
        pid = m.group("pid")
        if pid in vus:
            continue
        href = m.group("href")
        title = _text(m.group("inner")) or ""
        if not title:
            t = re.search(r"title=\"([^\"]+)\"", m.group(0))
            title = _html.unescape(t.group(1)).strip() if t else ""
        if not title:
            continue
        vus.add(pid)
        tail = html[m.end(): m.end() + 2500]
        pm_ = _MONEY_TXT_RE.search(tail)
        out.append(Candidat(
            url=(href if href.startswith("http") else "https://www.rona.ca" + href),
            title=title, sku=pid, price=(parse_money(pm_.group(1)) if pm_ else None),
        ))
        if len(out) >= limit:
            break
    return out
