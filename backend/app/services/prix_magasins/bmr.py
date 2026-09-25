"""BMR (bmr.ca) — relevé de prix sur les pages produit.

Résumé de l'enquête (2026-09-25, depuis le serveur : ``curl`` + en-têtes
navigateur, Playwright/Chromium headless puis Chromium « headful » sous Xvfb,
et Wayback Machine pour l'historique des pages) :

* Le site est un **Magento 2** (thème ``groupe-bmr/bmr``, modules maison
  ``GroupBmr_Prices``, ``GroupBmr_StoreLocator``) derrière **Cloudflare** en
  mode « défi géré » (page « Un instant… / Just a moment… », widget
  Turnstile). Un client HTTP nu ou avec ``BROWSER_HEADERS`` reçoit **403**
  sur TOUT (accueil, pages produit, sitemaps ``/sitemaps/bmr_fr_product.xml``) ;
  seul ``/robots.txt`` répond 200. Le cookie ``cf_clearance`` obtenu par un
  navigateur ne sert à rien avec httpx (lié à l'empreinte TLS du client).
  Depuis ce serveur, Chromium (headless, ou headful sous Xvfb) ne passe le
  défi que de façon aléatoire (1 fois sur ~15 essais, sans intervention ; on
  n'a pas cherché à le forcer). → ``NEEDS_BROWSER = True`` : le relevé
  quotidien passe par le VPS Playwright (IP résidentielle/propre), et
  ``parse()`` lit le **HTML rendu**. Pas de ``fetch()`` : aucune API JSON
  publique utilisable sans navigateur (voir plus bas).
* Les fixtures ``tests/fixtures/prix_magasins/bmr_<n>.html`` sont le HTML
  **serveur réel** de bmr.ca (élagué), récupéré par les instantanés de la
  Wayback Machine faute d'accès direct : ``bmr_1`` gypse 048-8077
  (2025-07-16, 28,98 $), ``bmr_2`` trousse Azur 064-8031 (2025-09-10, EN
  RABAIS 12,97 $ au lieu de 16,98 $), ``bmr_3`` isolant Armacell 078-2317-m
  (2026-08-04, configurable). Le gabarit de prix est identique dans la page
  d'accueil LIVE du 2026-09-25 (tuiles ``special-price`` / ``old-price`` /
  ``dollars`` / ``sep-dec``, bloc ``GroupBmr_Prices/js/store-prices`` avec
  ``"display":{"class":"percent","amount":"20%"},"circulaire":true``),
  seule la recherche a changé (Algolia → Coveo).
* URLs produit : ``https://www.bmr.ca/fr/<slug>-<code BMR NNN-NNNN>.html``
  (le code BMR est le suffixe de l'URL ; suffixe ``-m.html`` = fiche
  « maître » configurable avec plusieurs variantes). Exemples réels utilisés
  (prix = prix affiché pour le magasin par défaut, voir « Limites ») :
    - https://www.bmr.ca/fr/cgc-panneau-de-gypse-sheetrock-mold-tough-ultra-leger-1-2-x-4-x-8-048-8077.html
      (gypse 1/2 po 4x8, 28,98 $, prix régulier)
    - https://www.bmr.ca/fr/cgc-compose-a-joints-cgc-durabond-90-15-kg-036-0559.html
      (composé à joints Durabond 90, 35,98 $)
    - https://www.bmr.ca/fr/cgc-compose-a-joints-cgc-sheetrock-20-11-kg-036-0568.html
      (composé à joints Sheetrock 20, 32,98 $)
    - https://www.bmr.ca/fr/bmr-15-32-x-4-x-8-panneau-osb-scelle-001-0487.html
      (panneau OSB 15/32 4x8, 15,98 $)
    - https://www.bmr.ca/fr/bmr-1-2-x-4-x-8-contreplaque-csp-standard-061-6740.html
      (contreplaqué CSP 1/2 4x8, 40,38 $)
    - https://www.bmr.ca/fr/atika-bois-traite-brun-2-x-4-x-16-074-8942.html
      (2x4x16 traité brun, 16,58 $)
    - https://www.bmr.ca/fr/rust-oleum-peinture-antirouille-a-base-d-huile-tremclad-fini-lustre-blanc-3-78-l-029-0542.html
      (peinture Tremclad 3,78 L, 84,98 $)
    - https://www.bmr.ca/fr/armacell-canada-isolant-de-tuyau-078-2317-m.html
      (isolant de tuyau, fiche CONFIGURABLE : plusieurs variantes → pas de
      prix unique, voir ``extra["variants"]``)
    - https://www.bmr.ca/fr/architek-plancher-de-vinyle-spc-5-mm-bora-ginseng-7-x-48-001-5355.html
      (plancher vinyle SPC)
  Découverte d'URLs : les sitemaps sont derrière Cloudflare ; la recherche et
  les listes de catégorie sont rendues côté client (Algolia jusqu'au début
  2026, **Coveo** ``atomic-commerce-search-box`` depuis) — rien n'est
  interrogeable sans navigateur. Depuis le serveur, l'index CDX de la Wayback
  Machine (``web.archive.org/cdx/search/cdx?url=bmr.ca/fr/&matchType=prefix
  &filter=original:.*gypse.*\\.html``) a servi à trouver de vraies URLs, et
  ses instantanés (``/web/<ts>id_/<url>``, corps gzip) à étudier le HTML.

Méthode retenue : **HTML** (boîte de prix Magento du bloc
``product-info-main``), complétée par le **JSON-LD** ``Product`` (titre,
code BMR, marque, disponibilité) et les blocs JSON de configuration
(``priceConfig`` / ``GroupBmr_Prices/js/store-prices``) pour les drapeaux de
promotion.

Où sont les données dans la page :

* Boîte de prix : ``<div class="product-info-price"><div class="price-box …"
  data-product-id="62350">`` puis
  ``<span class="regular-price">`` (prix courant, pas de rabais) **ou**
  ``<span class="special-price">`` (prix de rabais) + ``<span class="old-price">``
  (prix régulier barré). Chaque prix est un
  ``<span data-price-type="finalPrice|oldPrice" data-price-amount="…">`` (l'attribut
  ``data-price-amount`` est VIDE dans le HTML de BMR : le montant est dans le
  texte ``<span class="price"><span class="dollars">15</span><span class="sep-dec">,</span><span>98 $</span></span>``
  → « 15,98 $ »). Un ``<span class="unit-label">`` (ex. « / pi² ») peut suivre.
  Le même gabarit sert aux tuiles de produits liés (``product-item-price``),
  d'où l'importance de rester dans ``product-info-main``.
  Exemple réel (tuile « Ensemble de peinture BMR 051-5061 », 2026-02) :
  ``special-price`` 9,97 $ + ``old-price`` 13,98 $.
* Rabais : ``<span class="special-price">`` + ``old-price`` dans la boîte, et
  drapeaux JSON ``"promotion":{"display":…,"circulaire":…,"flash_sale":…,
  "merchant_promotion":…,"merchant_clearance":…,"promotion_number":"…",
  "picto_promo":{"class":…,"front":"Bas prix"|"Pas de Promotion"}}``
  (``priceConfig`` de ``Magento_Catalog/js/price-box`` et
  ``GroupBmr_Prices/js/store-prices``). Étiquettes affichées (dictionnaire de
  traduction de la page) : « Rabais » (display / merchant_promotion),
  « Soldes » (circulaire), « Liquidation » (flash_sale / merchant_clearance),
  « Bas prix » (picto saisonnier). Le gabarit ``promo-tag`` peut afficher
  « Économisez <montant> ».
  ``on_sale`` = ``special-price`` présent, ou ``oldPrice > finalPrice``, ou
  un drapeau de promotion vrai.
* Date de fin de rabais : **non affichée** sur les pages produit examinées
  (ni « jusqu'au », ni ``priceValidUntil`` : le JSON-LD n'en a pas). Le
  dictionnaire Algolia de la page connaît ``special_to_date`` /
  ``special_from_date`` mais aucun gabarit ne l'affiche. Par prudence,
  ``parse()`` cherche quand même « jusqu'au <date> », « valide jusqu'au … »,
  « du … au … », « until <date> », « se termine le … » dans le bloc produit,
  ainsi qu'un ``special_to_date`` / ``priceValidUntil`` dans les JSON de la
  page, et renseigne ``sale_end`` si l'un d'eux apparaît.
* JSON-LD ``Product`` : ``name``, ``sku`` (code BMR), ``brand.name``,
  ``category``, ``offers`` = ``AggregateOffer`` avec ``lowPrice`` /
  ``highPrice`` = fourchette de prix **entre les magasins BMR** (pas un
  rabais !) et ``availability`` (InStock / OutOfStock). Fiche configurable :
  liste d'``AggregateOffer`` (une par variante, ``sku`` null).
* Titre : ``<h1 class="page-title"><span … itemprop="name">`` ; code BMR :
  ``<div class="value" itemprop="sku">`` (libellé « Code BMR »), repli
  ``data-product-sku`` du formulaire panier, puis suffixe de l'URL ;
  numéro d'article fabricant ``itemprop="manufacturer-part-number"`` et UPC
  ``itemprop="main-upc"`` dans ``extra``.
* Disponibilité : ``<meta property="product:availability" content="in stock">``
  et JSON-LD ; la disponibilité par magasin (``current-store-availability``)
  est remplie par XHR après le rendu (« En stock » / « Rupture de stock »…).
* Magasin : ``<span class="store-name">Matco St-Léonard</span>`` et
  ``"currentStoreId":103`` → ``extra["store"]`` / ``extra["store_id"]``.
* Fiche configurable (``-m.html``, ``"productType":"configurable"``) : la
  boîte principale est masquée (``price-unit-container``) ; les prix par
  variante sont dans ``optionPrices`` du ``Magento_Swatches/js/swatch-renderer``
  (``finalPrice.amount`` / ``oldPrice.amount``). ``parse()`` renvoie alors
  ``error`` + ``extra["variants"]`` : utiliser l'URL de la variante simple.
* « Voir le prix en magasin » (``showPrice: false`` / ``noPriceLabel``) :
  prix masqué en ligne → ``error``.

Ce qui ne marche pas / limites :

* Aucune API publique : l'ancien index Algolia (``DE7LVWVQ9D`` /
  ``bmr_magento2_fr``, avec prix par magasin ``price.CAD.default``,
  ``special_to_date``…) n'était accessible qu'avec une clé *sécurisée*
  générée par la page et valable ~24 h ; le XHR maison
  ``/fr/groupbmr_prices/ajax/index/`` (prix par magasin) est derrière
  Cloudflare comme le reste. Donc pas de ``fetch()``.
* **Prix par magasin** : BMR est une coopérative de marchands indépendants ;
  le prix affiché dépend du magasin choisi (cookie), et le magasin par défaut
  dépend du visiteur (« Matco St-Léonard » id 103 depuis ce serveur, « BMR
  Avantis Sainte-Claire » id 1320 ou « BMR Express Arthur Eidt » id 1307
  dans les instantanés Wayback). ``extra["store"]`` / ``extra["store_id"]``
  disent pour quel magasin le prix a été lu ; le JSON-LD donne la fourchette
  ``lowPrice``–``highPrice`` de tous les magasins (``extra["price_low"]`` /
  ``extra["price_high"]``). Si la boîte de prix est absente mais que la
  fourchette est un prix unique, on le renvoie (``method="jsonld"``).
* Fiche configurable : ``parse()`` renvoie ``error`` ; attention, le
  dispatch ``prix_magasins.parse()`` retombe alors sur ``parse_generic`` qui
  lit le ``lowPrice`` de la 1re ``AggregateOffer`` (prix plancher d'une
  variante, tous magasins confondus) — mieux vaut enregistrer l'URL de la
  variante simple dans le catalogue.
* Montants HT (taxes ajoutées au panier), en CAD.
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import date
from typing import Any, Optional

from . import PrixReleve, iter_jsonld, parse_date_any, parse_money

DOMAINS: tuple[str, ...] = ("bmr.ca",)
#: Le lowPrice d'une AggregateOffer (variante / tous magasins) n'est pas un prix payé : pas de repli générique.
GENERIC_FALLBACK: bool = False
NEEDS_BROWSER: bool = True

DEFAULT_STORE_ID = "103"  # Matco St-Léonard (magasin par défaut du site)

_SKU_URL_RE = re.compile(r"-(\d{3}-\d{4})(?:-m)?\.html?(?:[?#].*)?$", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_DATE_PHRASES = [
    re.compile(r"jusqu['’]\s*au\s+(\d{1,2}(?:er)?\s+[a-zéû]+\.?(?:\s+20\d{2})?)", re.I),
    re.compile(r"jusqu['’]\s*au\s+(20\d{2}-\d{2}-\d{2})", re.I),
    re.compile(r"se\s+termine\s+le\s+(\d{1,2}(?:er)?\s+[a-zéû]+\.?(?:\s+20\d{2})?)", re.I),
    re.compile(r"\bdu\s+\d{1,2}(?:er)?\s+(?:[a-zéû]+\.?\s+)?au\s+(\d{1,2}(?:er)?\s+[a-zéû]+\.?(?:\s+20\d{2})?)", re.I),
    re.compile(r"\b(?:until|through|ends?)\s+([a-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?,?(?:\s+20\d{2})?)", re.I),
    re.compile(r"\b(?:until|through)\s+(20\d{2}-\d{2}-\d{2})", re.I),
]
_JSON_DATE_RES = [
    re.compile(r"special_to_date[\"']?\s*[:=]\s*[\"']?(20\d{2}-\d{2}-\d{2})"),
    re.compile(r"priceValidUntil[\"']?\s*:\s*[\"'](20\d{2}-\d{2}-\d{2})"),
]


def sku_from_url(url: str) -> Optional[str]:
    """``…-panneau-osb-scelle-001-0487.html`` → ``001-0487``."""
    m = _SKU_URL_RE.search(url or "")
    return m.group(1) if m else None


def _text(fragment: str) -> str:
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub(" ", fragment or ""))).strip()


def _money_from_fragment(fragment: str) -> Optional[float]:
    """Texte « 15,98 $ » (ou « 1 234,56 $ ») d'un ``<span class="price">``."""
    t = _text(fragment)
    t = re.sub(r"\s*([,.])\s*", r"\1", t)
    m = re.search(r"\d[\d  ]*(?:[.,]\d{1,2})?", t)
    return parse_money(m.group(0)) if m else None


def _json_after(s: str, key: str, start: int = 0) -> tuple[Optional[Any], int]:
    """Objet JSON (accolades équilibrées) qui suit ``"key":`` dans ``s``."""
    i = s.find(key, start)
    if i < 0:
        return None, -1
    j = s.find("{", i + len(key))
    if j < 0:
        return None, -1
    depth, k, in_str, esc = 0, j, False, False
    while k < len(s):
        c = s[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[j : k + 1]), k + 1
                except json.JSONDecodeError:
                    return None, k + 1
        k += 1
    return None, -1


def _price_element(box: str, price_type: str) -> tuple[Optional[float], Optional[str]]:
    """Montant d'un ``<span data-price-type="…">`` de la boîte : attribut
    ``data-price-amount`` s'il est rempli, sinon le texte du ``<span class="price">``."""
    m = re.search(
        r"<span[^>]*data-price-type=[\"']" + re.escape(price_type) + r"[\"'][^>]*>",
        box, re.I,
    )
    if not m:
        return None, None
    tag = m.group(0)
    am = re.search(r"data-price-amount=[\"']([^\"']*)[\"']", tag)
    amount = parse_money(am.group(1)) if am and am.group(1).strip() else None
    rest = box[m.end() : m.end() + 1500]
    unit = None
    um = re.search(r"class=[\"'][^\"']*unit-label[^\"']*[\"'][^>]*>(.*?)</span>", rest, re.S | re.I)
    if um:
        unit = _text(um.group(1)) or None
    if amount is None:
        pm = re.search(r"<span[^>]*class=[\"']price[\"'][^>]*>(.*?)</span>\s*</span>", rest, re.S | re.I)
        frag = pm.group(1) if pm else rest.split("</span></span>")[0]
        amount = _money_from_fragment(frag)
    return amount, unit


def _main_block(html: str) -> str:
    """Bloc ``product-info-main`` (fiche principale, sans les produits liés)."""
    i = html.find("product-info-main")
    if i < 0:
        return html
    end = len(html)
    for marker in ("product-info-detailed", "related_products_list", "upsell_products_list",
                   "class=\"product info detailed\"", "block upsell", "block related"):
        j = html.find(marker, i)
        if 0 < j < end:
            end = j
    return html[i:end]


def _price_box(block: str) -> Optional[str]:
    """Première boîte de prix visible du bloc principal (hors ``price-unit-container``
    masqué des fiches configurables et hors tuiles de produits liés)."""
    for m in re.finditer(r"<div[^>]*class=[\"'][^\"']*\bprice-box\b[^\"']*[\"'][^>]*>", block, re.I):
        before = block[max(0, m.start() - 200) : m.start()]
        if "price-unit-container" in before or "product-item-price" in before:
            continue
        return block[m.start() : m.start() + 4000]
    return None


def _find_dates(text: str) -> Optional[date]:
    for rx in _DATE_PHRASES:
        m = rx.search(text)
        if m:
            d = parse_date_any(m.group(1))
            if d:
                return d
    return None


def parse(html: str, url: str) -> PrixReleve:
    """Lit une page produit BMR (HTML rendu par navigateur, ou HTML serveur).
    Jamais d'exception."""
    try:
        return _parse(html or "", url or "")
    except Exception as exc:  # noqa: BLE001
        return PrixReleve(error=f"Lecture de la page BMR échouée : {exc}", extra={"url": url})


def _parse(html: str, url: str) -> PrixReleve:
    extra: dict[str, Any] = {"url": url}
    sku_url = sku_from_url(url)
    if sku_url:
        extra["sku_url"] = sku_url

    if not html.strip() or "<" not in html:
        return PrixReleve(error="Page vide.", extra=extra)
    low = html[:20000].lower()
    if ("challenge-platform" in low or "cf-chl" in low or "just a moment" in low
            or "un instant…" in low or "checking your browser" in low) and "product-info-main" not in html:
        return PrixReleve(
            error="Page bloquée par Cloudflare (défi « Un instant… ») : relevé impossible sans navigateur.",
            extra=extra,
        )

    # ── JSON-LD Product ─────────────────────────────────────────────────
    title = sku = brand = None
    in_stock: Optional[bool] = None
    low_price = high_price = None
    ld_price = None
    for node in iter_jsonld(html):
        t = node.get("@type")
        types = [str(x).lower() for x in (t if isinstance(t, list) else [t])]
        if "product" not in types:
            continue
        title = str(node.get("name")) if node.get("name") else None
        sku = str(node.get("sku")) if node.get("sku") else None
        b = node.get("brand")
        brand = (b.get("name") if isinstance(b, dict) else b) or None
        if node.get("category"):
            extra["category"] = node["category"]
        offers = node.get("offers")
        offer_list = offers if isinstance(offers, list) else [offers]
        offer_list = [o for o in offer_list if isinstance(o, dict)]
        if offer_list:
            o = offer_list[0]
            avail = str(o.get("availability") or "").lower()
            in_stock = True if "instock" in avail else (False if "outofstock" in avail else None)
            if len(offer_list) == 1:
                low_price = parse_money(o.get("lowPrice"))
                high_price = parse_money(o.get("highPrice"))
                ld_price = parse_money(o.get("price"))
                if o.get("priceValidUntil"):
                    extra["priceValidUntil"] = o["priceValidUntil"]
            else:
                extra["variants"] = [
                    {"name": v.get("name"), "low": parse_money(v.get("lowPrice")),
                     "high": parse_money(v.get("highPrice")), "price": parse_money(v.get("price"))}
                    for v in offer_list
                ]
        break
    if low_price is not None:
        extra["price_low"] = low_price
    if high_price is not None:
        extra["price_high"] = high_price
    if brand:
        extra["brand"] = brand

    if title is None and sku is None and "product-info-main" not in html:
        return PrixReleve(error="Pas une page produit BMR (aucune fiche produit dans la page).", extra=extra)

    # ── bloc principal : titre, code BMR, magasin ───────────────────────
    block = _main_block(html)
    m = re.search(r"<h1[^>]*class=[\"'][^\"']*page-title[^\"']*[\"'][^>]*>(.*?)</h1>", block, re.S | re.I)
    if m and _text(m.group(1)):
        title = _text(m.group(1))
    if not title:
        m = re.search(r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']+)", html, re.I)
        if m:
            title = _text(m.group(1))
    m = re.search(r"itemprop=[\"']sku[\"'][^>]*>(.*?)</", block, re.S | re.I)
    if m and _text(m.group(1)):
        sku = _text(m.group(1))
    if not sku:
        m = re.search(r"data-product-sku=[\"']([^\"']+)", block, re.I)
        sku = m.group(1) if m else sku_url
    m = re.search(r"itemprop=[\"']manufacturer-part-number[\"'][^>]*>(.*?)</", block, re.S | re.I)
    if m and _text(m.group(1)):
        extra["manufacturer_part_number"] = _text(m.group(1))
    m = re.search(r"itemprop=[\"']main-upc[\"'][^>]*>(.*?)</", block, re.S | re.I)
    if m and _text(m.group(1)):
        extra["upc"] = _text(m.group(1))
    m = re.search(r"class=[\"']store-name[\"'][^>]*>(.*?)</span>", html, re.S | re.I)
    if m and _text(m.group(1)):
        extra["store"] = _text(m.group(1))
    m = re.search(r"[\"']currentStoreId[\"']\s*:\s*[\"']?(\d+)", html)
    extra["store_id"] = m.group(1) if m else DEFAULT_STORE_ID

    # disponibilité (meta OG, puis texte par magasin du HTML rendu)
    m = re.search(r"<meta[^>]+property=[\"']product:availability[\"'][^>]+content=[\"']([^\"']+)", html, re.I)
    if m:
        v = m.group(1).strip().lower()
        if "in stock" in v or v == "instock":
            in_stock = True
        elif "out" in v:
            in_stock = False
    m = re.search(r"class=[\"'][^\"']*current-store-availability[^\"']*[\"'][^>]*>(.*?)</div>", block, re.S | re.I)
    if m:
        av = _text(m.group(1))
        if av:
            extra["availability_text"] = av
            lo = av.lower()
            if "rupture" in lo or "non disponible" in lo or "épuisé" in lo or "out of stock" in lo:
                in_stock = False
            elif "en stock" in lo or "in stock" in lo or "disponible" in lo:
                in_stock = True

    # ── drapeaux de promotion (priceConfig / store-prices) ──────────────
    promo: dict[str, Any] = {}
    pos = 0
    while not promo:
        obj, pos = _json_after(html, '"promotion":', pos)
        if pos < 0:
            break
        if isinstance(obj, dict) and "display" in obj:
            promo = obj
    pos = 0
    while not promo:
        # bloc store-prices : {"<productId>": {"promotions": {...}}}
        obj, pos = _json_after(html, '"promotions":', pos)
        if pos < 0:
            break
        if isinstance(obj, dict):
            for v in obj.values():
                if isinstance(v, dict) and isinstance(v.get("promotions"), dict) and "display" in v["promotions"]:
                    promo = v["promotions"]
                    break
    promo_flags = {k: bool(promo.get(k)) for k in
                   ("display", "circulaire", "flash_sale", "merchant_promotion", "merchant_clearance", "low_price")}
    if promo:
        extra["promotion"] = promo_flags
        disp = promo.get("display")
        if isinstance(disp, dict) and disp.get("amount"):
            extra["discount_label"] = str(disp["amount"])
        if promo.get("gtm_type"):
            extra["promo_type"] = promo["gtm_type"]
        pict = promo.get("picto_promo")
        if isinstance(pict, dict) and pict.get("front"):
            extra["promo_picto"] = pict["front"]
        if promo.get("promotion_number"):
            extra["promotion_number"] = promo["promotion_number"]
    m = re.search(r"[\"']productType[\"']\s*:\s*[\"'](\w+)[\"']", html)
    product_type = m.group(1).lower() if m else None
    if product_type:
        extra["product_type"] = product_type
    show_price = not re.search(r"[\"']showPrice[\"']\s*:\s*false", html)
    if show_price and "Voir le prix en magasin" in _text(re.sub(r"<script\b[^>]*>.*?</script>", " ", block, flags=re.S | re.I)):
        show_price = False  # libellé affiché à la place du prix (HTML rendu)

    # ── boîte de prix ───────────────────────────────────────────────────
    box = _price_box(block) if (show_price and product_type not in ("configurable", "grouped", "bundle")) else None
    price = regular = None
    unit = None
    on_sale = False
    if box:
        price, unit = _price_element(box, "finalPrice")
        regular, _ = _price_element(box, "oldPrice")
        if price is None:
            # fiche « À partir de » / gabarits sans data-price-type
            m = re.search(r"<span[^>]*class=[\"']price[\"'][^>]*>(.*?)</span>\s*</span>", box, re.S | re.I)
            if m:
                price = _money_from_fragment(m.group(1))
        on_sale = bool(re.search(r"class=[\"'][^\"']*\bspecial-price\b", box, re.I))
        if "from-price" in box and "display: none" not in box.split("from-price")[0][-200:]:
            extra["starting_at"] = True
    if unit:
        extra["unit"] = unit

    # étiquette de promo rendue (« Rabais », « Soldes », « Liquidation », « Économisez 10 % »)
    if box:
        bi = block.find(box[:200])
        zone = block[max(0, bi - 1500) : bi + len(box)] if bi >= 0 else box
        for m in re.finditer(r"<div[^>]*class=[\"'][^\"']*\bpromo-tag\b[^\"']*[\"'][^>]*>(.*?)</div>\s*</div>", zone, re.S | re.I):
            label = _text(m.group(1))
            if label and len(label) <= 80 and "{" not in label:
                extra["promo_label"] = label
                break

    # ── date de fin de promotion (si jamais affichée) ───────────────────
    sale_end: Optional[date] = None
    for rx in _JSON_DATE_RES:
        m = rx.search(html)
        if m:
            sale_end = parse_date_any(m.group(1))
            if sale_end:
                break
    if sale_end is None:
        sale_end = _find_dates(_text(block))

    # ── fiche configurable / prix masqué ────────────────────────────────
    if product_type in ("configurable", "grouped", "bundle") and price is None:
        opt, _ = _json_after(html, '"optionPrices":')
        if isinstance(opt, dict):
            variants = []
            for pid, v in opt.items():
                if isinstance(v, dict):
                    fp = (v.get("finalPrice") or {}).get("amount")
                    op = (v.get("oldPrice") or {}).get("amount")
                    variants.append({"product_id": pid, "price": parse_money(fp), "regular_price": parse_money(op)})
            if variants:
                extra["variants"] = variants
        return PrixReleve(
            title=title, sku=sku, in_stock=in_stock, sale_end=sale_end, method="html",
            error=f"Fiche {product_type} (plusieurs variantes) : utiliser l'URL du produit simple.",
            extra=extra,
        )
    if price is None and not show_price:
        return PrixReleve(
            title=title, sku=sku, in_stock=in_stock, method="html",
            error="Prix non affiché en ligne (« Voir le prix en magasin »).", extra=extra,
        )

    method = "html"
    if price is None:
        # repli : JSON-LD (prix unique dans tous les magasins seulement)
        if ld_price is not None:
            price, method = ld_price, "jsonld"
        elif low_price is not None and (high_price is None or high_price == low_price):
            price, method = low_price, "jsonld"
        else:
            msg = "Aucune boîte de prix reconnue dans la page BMR."
            if low_price is not None and high_price is not None:
                msg += f" (fourchette selon le magasin : {low_price:.2f}–{high_price:.2f} $)"
            return PrixReleve(title=title, sku=sku, in_stock=in_stock, method=method, error=msg, extra=extra)

    if regular is not None and regular <= price:
        if regular < price:
            extra["old_price_ignored"] = regular
        regular = None
    if regular is not None:
        on_sale = True
    if any(promo_flags.values()):
        on_sale = True
    return PrixReleve(
        price=price,
        regular_price=regular,
        on_sale=on_sale,
        sale_end=sale_end if on_sale or sale_end else None,
        currency="CAD",
        title=title,
        sku=sku,
        in_stock=in_stock,
        method=method,
        extra=extra,
    )


# ───────────── Recherche (prix de base automatique, 2026-09-26) ─────────────

SEARCH_URL = "https://www.bmr.ca/fr/catalogsearch/result/?q={q}"
_BMR_LINK_RE = re.compile(
    r"<a\b[^>]*href=\"(?P<href>https://www\.bmr\.ca/fr/[^\"#?]+?-(?P<sku>\d{3}-\d{4})(?:-m)?\.html)\"[^>]*>(?P<inner>.*?)</a>",
    re.S | re.I,
)
_MONEY_TXT_RE = re.compile(r"(\d{1,3}(?:[   ]\d{3})*(?:[.,]\d{2})?)\s*\$")
#: Identifiants Algolia lus dans ``window.algoliaConfig`` de la première
#: page rendue : ensuite la recherche interroge Algolia directement
#: (JSON, sans navigateur).
_ALGOLIA: dict[str, Any] = {"app": None, "key": None, "index": None}


def _capture_algolia(html: str) -> None:
    m = re.search(r"window\.algoliaConfig\s*=\s*(\{.*?\});\s*</script>", html, re.S)
    if not m:
        return
    raw = m.group(1)
    app = re.search(r"\"applicationId\"\s*:\s*\"([^\"]+)\"", raw)
    key = re.search(r"\"apiKey\"\s*:\s*\"([^\"]+)\"", raw)
    idx = re.search(r"\"indexName\"\s*:\s*\"([^\"]+)\"", raw)
    if app and key and idx:
        _ALGOLIA.update(app=app.group(1), key=key.group(1), index=idx.group(1))


async def _search_algolia(query: str, limit: int) -> list:
    import httpx

    from .recherche import Candidat

    app, key, index = _ALGOLIA["app"], _ALGOLIA["key"], _ALGOLIA["index"]
    from urllib.parse import urlencode

    idx = index if index.endswith("_products") else f"{index}_products"
    url = f"https://{app}-dsn.algolia.net/1/indexes/{idx}/query"
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            url, json={"params": urlencode({"query": query, "hitsPerPage": int(limit)})},
            headers={"X-Algolia-Application-Id": app, "X-Algolia-API-Key": key},
        )
    if r.status_code != 200:
        raise RuntimeError(f"Algolia BMR : HTTP {r.status_code}")
    out = []
    for h in (r.json().get("hits") or [])[:limit]:
        url = str(h.get("url") or "")
        if not url:
            continue
        price = None
        p = h.get("price")
        if isinstance(p, dict):
            cad = p.get("CAD") or next(iter(p.values()), None)
            if isinstance(cad, dict):
                price = parse_money(cad.get("default"))
        out.append(Candidat(url=url, title=str(h.get("name") or url), sku=(str(h.get("sku")) if h.get("sku") else None), price=price))
    return out


async def search(query: str, *, limit: int = 10) -> list:
    """Page de résultats RENDUE par le VPS (Cloudflare) ; les tuiles sont
    des liens ``…-NNN-NNNN.html``. Si la page livre les identifiants
    Algolia, les recherches suivantes passent par Algolia (JSON)."""
    from urllib.parse import quote

    from app.integrations.scraping_proxy import fetch_rendered_html

    from .recherche import Candidat

    if _ALGOLIA["app"]:
        try:
            res = await _search_algolia(query, limit)
            if res:
                return res
        except Exception:  # noqa: BLE001 — on retombe sur la page rendue
            pass
    html = await fetch_rendered_html(SEARCH_URL.format(q=quote(query)), wait_ms=3000)
    if html is None:
        raise RuntimeError("recherche BMR : le VPS de scraping n'est pas configuré")
    if not html or ("Un instant" in html[:3000] and "-dsn.algolia" not in html and ".html\"" not in html):
        raise RuntimeError("recherche BMR : page bloquée (Cloudflare)")
    _capture_algolia(html)
    out: list[Candidat] = []
    vus: set[str] = set()
    for m in _BMR_LINK_RE.finditer(html):
        sku = m.group("sku")
        if sku in vus:
            continue
        title = _text(m.group("inner")) or ""
        if not title:
            t = re.search(r"title=\"([^\"]+)\"", m.group(0))
            title = _html.unescape(t.group(1)).strip() if t else ""
        if not title:
            continue
        vus.add(sku)
        # Le prix des tuiles est découpé en balises (« 47 », « , », « 98 $ ») :
        # on ne le lit pas ici, le relevé de la page produit s'en charge.
        out.append(Candidat(url=m.group("href"), title=title, sku=sku, price=None))
        if len(out) >= limit:
            break
    return out
