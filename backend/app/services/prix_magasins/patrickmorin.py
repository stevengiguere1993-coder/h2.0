"""Patrick Morin (patrickmorin.com) — relevé de prix sur les pages produit.

Résumé de l'enquête (2026-09-25, depuis le serveur, ``curl`` + en-têtes
navigateur) :

* Le site est un **Magento 2** (thème O2web/patmorin). Les pages produit
  répondent **200** à un simple client HTTP avec ``BROWSER_HEADERS`` ; aucun
  blocage anti-robot observé → ``NEEDS_BROWSER = False``, pas de ``fetch()``
  spécial (httpx sur l'URL produit suffit).
* URLs produit : ``https://patrickmorin.com/fr/<slug>-<sku>`` (sans ``.html``).
  Exemples réels utilisés :
    - https://patrickmorin.com/fr/panneau-de-gypse-regulier-ultra-leger-gypr1208
      (gypse 1/2 po 4x8, prix régulier 17,92 $)
    - https://patrickmorin.com/fr/vis-a-gypse-tete-plate-6-1-1-4-po-500-pqt-260150013
      (vis à gypse, 6,49 $)
    - https://patrickmorin.com/fr/compose-a-joints-pour-cloison-seche-pret-a-l-emploi-cgc-12-l-0528004
      (composé à joints CGC 12 L, 28,89 $)
    - https://patrickmorin.com/fr/peinture-et-appret-d-interieur-evolution-sico-latex-fini-veloute-blanc-pur-3-78-l-18635504
      (peinture SICO, EN RABAIS : 44,99 $ au lieu de 74,99 $, badge « Circulaire »)
    - https://patrickmorin.com/fr/mousse-isolante-portes-et-fenetres-great-stuff-567-g-2578225
      (mousse isolante, EN RABAIS : 14,99 $ au lieu de 21,99 $, badge « Économisez »)
    - https://patrickmorin.com/fr/plancher-vinyle-spc-neo-3-3-mm-1-mm-classique-0928023
      (plancher vinyle SPC, 62,72 $ la boîte)
  Les listes de catégorie et la recherche du site sont rendues côté client
  par **Bloomreach** ; pour trouver des URLs produit sans navigateur, l'API
  publique de recherche fonctionne avec httpx :
  ``https://core.dxpapi.com/api/v1/core/?account_id=7570&domain_key=patrickmorin_fr_new
  &request_type=search&search_type=keyword&q=gypse&fl=pid,title,price,sale_price,url
  &rows=20&start=0&url=https://patrickmorin.com/fr/&ref_url=https://patrickmorin.com/fr/
  &request_id=<13 chiffres>&_br_uid_2=uid%3D<13 chiffres>%3Av%3D11.5%3Ats%3D<ms>%3Ahc%3D1``
  (aucune clé secrète : identifiants publics présents dans la page). Cette
  API ne renvoie PAS le prix spécial (``price`` == ``sale_price`` même en
  rabais), seulement un champ ``banner`` (« Économisez » / « Circulaire » /
  « No Banner ») ; elle sert donc à la découverte d'URLs, pas au relevé.

Méthode retenue : **HTML** (boîte de prix Magento), avec le **JSON-LD** en
complément (titre, SKU, disponibilité) et en repli pour le prix.

Où sont les données dans la page :

* Prix payé : ``<span data-price-type="finalPrice" data-price-amount="14.99">``
  dans ``<div class="product-info-price"> … <div class="price-box …">``.
* Rabais : la boîte de prix contient alors ``<span class="special-price">``
  avec l'étiquette « Prix Spécial », puis dans ``<span class="save-price">`` :
  ``data-price-type="oldPrice" data-price-amount="21.99"`` (prix régulier) et
  ``data-price-type="savedAmount" data-price-amount="7"`` étiqueté
  « Économisez ». Un badge image ``<div class="image-label …"><span>Économisez</span>``
  (ou « Circulaire », « Liquidation »…) est aussi présent.
  Exemple réel (mousse GREAT STUFF 2578225, 2026-09-25) :
  « Prix Spécial 14,99 $ — 21,99 $ — Économisez 7,00 $ ».
* Prix MAP (« prix_map », prix minimum annoncé imposé par le fabricant,
  ex. outils MAKITA) : la boîte affiche seulement le PDSF dans
  ``<span class="map-fallback-price">`` + « Qu'est-ce que c'est ? » ; le prix
  réel n'apparaît que dans le JSON-LD (``offers.price``). On renvoie alors
  ce prix JSON-LD comme ``price`` et le PDSF comme ``regular_price``, avec
  ``extra["prix_map"] = True``.
* JSON-LD ``Product`` : ``name``, ``sku`` (= code Patrick Morin, aussi
  suffixe de l'URL), ``brand``, ``gtin12``, ``offers.price`` (déjà le prix
  spécial quand il y en a un), ``offers.availability`` (InStock /
  OutOfStock). **Attention** : ``offers.priceValidUntil`` vaut toujours
  ``"2030-01-01"`` (valeur bouche-trou) → ignoré, ne sert pas de
  ``sale_end``.
* OpenGraph : ``product:price:amount`` (= prix final), ``product:availability``.

Date de fin de rabais : **non affichée** sur la page produit, ni dans le
HTML initial, ni après rendu JavaScript (vérifié avec Playwright : aucun
XHR ne rapporte de date ; ``ogasyssalesrule/banner/get`` renvoie
``{"banner":{"message":null}}``). Le seul indice est le badge
« Circulaire » (rabais lié à la circulaire hebdomadaire, dates non
exposées sur la page). ``parse()`` cherche tout de même, par prudence, une
mention « jusqu'au <date> » / « valide jusqu'au … » / « du … au … » dans la
zone du prix, et la renvoie si elle apparaît un jour.

Limites connues :

* Les prix sont ceux du magasin par défaut (Laval, ``current-store``
  entity_id 15) — Patrick Morin a des prix par succursale
  (``price_<retailer>`` / ``specialprice_<retailer>`` dans Bloomreach) ; sans
  cookie de magasin, on relève Laval.
* Le stock affiché (« 115 Disponible à Laval ») vient d'un POST
  ``patmorin_inventory/inventory/updatestock`` après rendu ; on se contente
  de ``InStock`` / ``OutOfStock`` du JSON-LD.
* Montants HT (taxes ajoutées au panier), en CAD.
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import date, timedelta
from typing import Any, Optional

from . import PrixReleve, iter_jsonld, parse_date_any, parse_generic, parse_money

DOMAINS: tuple[str, ...] = ("patrickmorin.com",)
NEEDS_BROWSER: bool = False

# priceValidUntil « bouche-trou » de Magento chez Patrick Morin.
_PLACEHOLDER_VALID_UNTIL = date(2030, 1, 1)

_PRICE_INFO_RE = re.compile(
    r'<div[^>]+class="[^"]*product-info-price[^"]*"[^>]*>(.*?)'
    r'(?:<div[^>]+class="[^"]*product-add-form|<form[^>]+id="product_addtocart_form)',
    re.S | re.I,
)
_PRICE_BOX_RE = re.compile(
    r'<div[^>]+class="[^"]*price-box[^"]*price-final_price[^"]*"[^>]*>(.*?)</div>\s*</div>',
    re.S | re.I,
)
_AMOUNT_RE = re.compile(
    r'<span[^>]+data-price-amount="([^"]*)"[^>]+data-price-type="([^"]*)"', re.I
)
_AMOUNT_RE_REV = re.compile(
    r'<span[^>]+data-price-type="([^"]*)"[^>]+data-price-amount="([^"]*)"', re.I
)
_BADGE_RE = re.compile(
    r'<div[^>]+class="image-label[^"]*"[^>]*>\s*<span>([^<]+)</span>', re.I
)
_SKU_FORM_RE = re.compile(r'data-product-sku="([^"]+)"', re.I)
_TAG_RE = re.compile(r"<[^>]+>")

# Mentions de fin de promo (jamais vues chez Patrick Morin à ce jour, gardées
# par prudence) : « jusqu'au 2 octobre », « valide jusqu'au 2 octobre 2026 »,
# « du 25 septembre au 1er octobre », « until Oct 2 ».
_SALE_END_RE = re.compile(
    r"(?:jusqu['’]\s*au|jusqu['’]\s*à|valide\s+jusqu['’]\s*au|until|through|"
    r"du\s+\d{1,2}(?:er)?\s+[a-zéû]+\s+au)\s+"
    r"(\d{1,2}(?:er)?\s+[a-zéû]+\.?(?:\s+20\d{2})?|[a-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?,?(?:\s+20\d{2})?|20\d{2}-\d{2}-\d{2})",
    re.I,
)


def _amounts(fragment: str) -> dict[str, float]:
    """{price-type: montant} pour tous les ``data-price-amount`` du fragment."""
    out: dict[str, float] = {}
    for amt, typ in _AMOUNT_RE.findall(fragment):
        v = parse_money(amt)
        if v is not None and typ and typ not in out:
            out[typ] = v
    for typ, amt in _AMOUNT_RE_REV.findall(fragment):
        v = parse_money(amt)
        if v is not None and typ and typ not in out:
            out[typ] = v
    return out


def _price_fragment(html: str) -> str:
    m = _PRICE_INFO_RE.search(html)
    if m:
        return m.group(1)
    m = _PRICE_BOX_RE.search(html)
    return m.group(1) if m else ""


def _jsonld_product(html: str) -> Optional[dict]:
    for node in iter_jsonld(html):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(str(x).lower() == "product" for x in types):
            return node
    return None


def _sale_end_from_text(fragment: str, *, today: Optional[date] = None) -> Optional[date]:
    text = _html.unescape(_TAG_RE.sub(" ", fragment))
    text = re.sub(r"\s+", " ", text)
    m = _SALE_END_RE.search(text)
    if not m:
        return None
    return parse_date_any(m.group(1), today=today)


def _parse_bloomreach_doc(data: dict, url: str) -> PrixReleve:
    """Un document de l'API Bloomreach (``{"pid":…, "price":…, "sale_price":…}``)
    ou une réponse complète (``{"response": {"docs": [...]}}``)."""
    doc: Any = data
    if isinstance(data.get("response"), dict):
        docs = data["response"].get("docs") or []
        doc = next((d for d in docs if isinstance(d, dict) and (not url or d.get("url") == url)), None) \
            or (docs[0] if docs and isinstance(docs[0], dict) else None)
    if not isinstance(doc, dict):
        return PrixReleve(error="Réponse Bloomreach sans document produit.")
    price = parse_money(doc.get("sale_price"))
    regular = parse_money(doc.get("price"))
    if price is None:
        price = regular
        regular = None
    if price is None:
        return PrixReleve(error="Document Bloomreach sans prix.")
    on_sale = bool(regular is not None and price < regular)
    return PrixReleve(
        price=price,
        regular_price=regular if on_sale else None,
        on_sale=on_sale or doc.get("banner") == "Économisez",
        title=str(doc.get("title")) if doc.get("title") else None,
        sku=str(doc.get("pid")) if doc.get("pid") else None,
        method="api",
        extra={"banner": doc.get("banner"), "prix_map": doc.get("prix_map") == "true"},
    )


def parse(html: str, url: str = "") -> PrixReleve:  # noqa: C901 - linéaire mais long
    """Lit prix / prix régulier / rabais / titre / SKU / stock d'une page
    produit Patrick Morin. Ne lève jamais : page inattendue → ``error``."""
    try:
        return _parse(html or "", url or "")
    except Exception as exc:  # noqa: BLE001
        return PrixReleve(error=f"Lecture de la page Patrick Morin échouée : {exc}")


def _parse(html: str, url: str) -> PrixReleve:
    stripped = html.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return PrixReleve(error="JSON illisible.")
        return _parse_bloomreach_doc(data, url) if isinstance(data, dict) else PrixReleve(error="JSON inattendu.")

    if not html.strip():
        return PrixReleve(error="Page vide.")

    product = _jsonld_product(html) or {}
    offer = product.get("offers") if isinstance(product.get("offers"), dict) else (
        next((o for o in product.get("offers", []) if isinstance(o, dict)), {})
        if isinstance(product.get("offers"), list) else {}
    )
    jsonld_price = parse_money(offer.get("price")) if offer else None

    fragment = _price_fragment(html)
    amounts = _amounts(fragment)
    extra: dict[str, Any] = {}

    # Le badge est cherché AVANT le bloc principal seulement : plus loin,
    # le carrousel de produits liés a ses propres badges (« Liquidation »
    # d'un autre article).
    m_main = re.search(r'<div[^>]+class="[^"]*product-info-main', html, re.I)
    badge_m = _BADGE_RE.search(html[:m_main.start()] if m_main else html)
    badge = _html.unescape(badge_m.group(1)).strip() if badge_m else None
    if badge:
        extra["banner"] = badge

    price: Optional[float] = None
    regular: Optional[float] = None
    on_sale = False
    method = "html"

    is_map = "map-fallback-price" in fragment or "map-old-price" in fragment
    if is_map:
        # Prix MAP : la page n'affiche que le PDSF ; le vrai prix est dans le JSON-LD.
        extra["prix_map"] = True
        msrp = parse_money(next(iter(re.findall(r'data-price-amount="([^"]*)"', fragment)), None))
        if jsonld_price is not None:
            price = jsonld_price
            method = "jsonld"
            if msrp is not None and msrp > price:
                # Prix MAP : l'écart avec le PDSF est permanent, pas un
                # rabais temporaire → pas de « rabais » au catalogue.
                extra["pdsf"] = msrp
        elif msrp is not None:
            price = msrp
    else:
        price = amounts.get("finalPrice")
        old = amounts.get("oldPrice")
        saved = amounts.get("savedAmount")
        if saved is not None:
            extra["saved_amount"] = saved
        special_box = bool(re.search(r'class="special-price"', fragment, re.I))
        if price is not None and old is not None and old > price:
            regular = old
            on_sale = True
        elif price is not None and special_box:
            on_sale = True
        if price is None and jsonld_price is not None:
            price = jsonld_price
            method = "jsonld"
        elif price is None:
            gen = parse_generic(html, url)
            if gen.ok:
                price, method = gen.price, gen.method

    if price is None:
        if re.search(r"<body[^>]+catalog-product-view", html, re.I) or product:
            return PrixReleve(
                title=str(product.get("name")) if product.get("name") else None,
                sku=str(product.get("sku")) if product.get("sku") else None,
                error="Aucun prix affiché sur la page produit (prix masqué ou produit indisponible).",
                extra=extra,
            )
        return PrixReleve(error="Page inattendue : pas une fiche produit Patrick Morin.", extra=extra)

    # Date de fin de rabais : jamais affichée à ce jour ; priceValidUntil
    # JSON-LD est un bouche-trou (2030-01-01) qu'on ignore.
    sale_end: Optional[date] = None
    if on_sale:
        sale_end = _sale_end_from_text(fragment)
        if sale_end is None and offer.get("priceValidUntil"):
            cand = parse_date_any(offer.get("priceValidUntil"))
            if cand and cand != _PLACEHOLDER_VALID_UNTIL and cand <= date.today() + timedelta(days=400):
                sale_end = cand

    # Titre / SKU / disponibilité.
    title = str(product.get("name")) if product.get("name") else None
    if not title:
        m = re.search(r'<span[^>]+itemprop="name"[^>]*>(.*?)</span>', html, re.S | re.I) or re.search(
            r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', html, re.I
        )
        if m:
            title = _html.unescape(_TAG_RE.sub("", m.group(1))).strip() or None
    sku = str(product.get("sku")) if product.get("sku") else None
    if not sku:
        m = _SKU_FORM_RE.search(html)
        sku = m.group(1) if m else None

    in_stock: Optional[bool] = None
    avail = str(offer.get("availability") or "").lower() if offer else ""
    if "instock" in avail:
        in_stock = True
    elif "outofstock" in avail:
        in_stock = False
    else:
        m = re.search(r'<meta[^>]+property="product:availability"[^>]+content="([^"]*)"', html, re.I)
        if m:
            v = m.group(1).lower()
            in_stock = True if "in stock" in v or "instock" in v else (False if "out" in v else None)

    if isinstance(product.get("brand"), dict) and product["brand"].get("name"):
        extra["brand"] = product["brand"]["name"]
    if product.get("gtin12"):
        extra["gtin"] = str(product["gtin12"])

    return PrixReleve(
        price=price,
        regular_price=regular,
        on_sale=on_sale,
        sale_end=sale_end,
        currency=str(offer.get("priceCurrency") or "CAD") if offer else "CAD",
        title=title,
        sku=sku,
        in_stock=in_stock,
        method=method,
        extra=extra,
    )


# ───────────── Recherche (prix de base automatique, 2026-09-26) ─────────────

BLOOMREACH_URL = "https://core.dxpapi.com/api/v1/core/"
BLOOMREACH_ACCOUNT = "7570"
BLOOMREACH_DOMAIN_KEY = "patrickmorin_fr_new"


async def search(query: str, *, limit: int = 10) -> list:
    """API publique Bloomreach du site (identifiants publics de la page) :
    ``pid``, ``title``, ``url``, ``price`` (le prix courant n'y est PAS
    ramené au rabais : on relève ensuite la page produit)."""
    import time

    import httpx

    from . import BROWSER_HEADERS
    from .recherche import Candidat

    ts = str(int(time.time() * 1000))
    params = {
        "account_id": BLOOMREACH_ACCOUNT, "domain_key": BLOOMREACH_DOMAIN_KEY,
        "request_type": "search", "search_type": "keyword", "q": query,
        "fl": "pid,title,price,sale_price,url,brand", "rows": str(int(limit)),
        "start": "0", "url": "https://patrickmorin.com/fr/",
        "ref_url": "https://patrickmorin.com/fr/", "request_id": ts,
        "_br_uid_2": f"uid={ts}:v=11.5:ts={ts}:hc=1",
    }
    async with httpx.AsyncClient(timeout=25.0, headers=BROWSER_HEADERS) as client:
        r = await client.get(BLOOMREACH_URL, params=params)
    if r.status_code != 200:
        raise RuntimeError(f"recherche Patrick Morin : HTTP {r.status_code}")
    try:
        docs = (r.json().get("response") or {}).get("docs") or []
    except ValueError as exc:
        raise RuntimeError("recherche Patrick Morin : réponse non JSON") from exc
    out = []
    for d in docs[:limit]:
        url = str(d.get("url") or "").strip()
        if not url:
            continue
        title = " ".join(str(x) for x in (d.get("brand"), d.get("title")) if x).strip()
        out.append(Candidat(
            url=url, title=title or url, sku=(str(d.get("pid")) if d.get("pid") else None),
            price=parse_money(d.get("sale_price") if d.get("sale_price") is not None else d.get("price")),
            extra={"brand": d.get("brand")},
        ))
    return out
