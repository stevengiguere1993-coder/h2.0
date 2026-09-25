"""Relevé automatique des PRIX chez les détaillants (étape 2 du catalogue
de matériaux, 2026-09-25).

Un module par magasin (``homedepot.py``, ``patrickmorin.py``, ``canac.py``,
``rona.py``, ``bmr.py``…) expose :

    parse(html: str, url: str) -> PrixReleve      # obligatoire
    fetch(url: str) -> str                        # optionnel : quand le
                                                  # magasin se lit mieux
                                                  # par une API JSON que
                                                  # par sa page HTML
    DOMAINS: tuple[str, ...]                      # domaines gérés

``REGISTRY`` associe un domaine à son module. ``parse_generic`` couvre
tout site inconnu via les données structurées (JSON-LD ``Product`` /
``Offer``, balises OpenGraph ``product:price:amount``, microdonnées
``itemprop=price``).

Contrat d'un parseur : JAMAIS d'exception pour une page inattendue —
retourner un ``PrixReleve`` avec ``price=None`` et ``error`` renseigné.
Les montants sont en dollars canadiens, taxes NON comprises.
"""

from __future__ import annotations

import html as _html
import importlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

#: En-têtes « navigateur » pour les sites qui refusent un client nu.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-CA,fr;q=0.9,en-CA;q=0.8,en;q=0.7",
}


@dataclass
class PrixReleve:
    """Résultat d'un relevé sur une page produit."""

    #: Prix affiché aujourd'hui (celui qu'on paierait), HT.
    price: Optional[float] = None
    #: Prix régulier si le prix affiché est un prix de rabais.
    regular_price: Optional[float] = None
    on_sale: bool = False
    #: Dernier jour du rabais (inclus) quand la page l'indique.
    sale_end: Optional[date] = None
    currency: str = "CAD"
    title: Optional[str] = None
    sku: Optional[str] = None
    in_stock: Optional[bool] = None
    #: D'où vient la donnée : jsonld | html | api | og | microdata.
    method: str = ""
    #: Message lisible si rien n'a pu être lu (page inattendue, bloquée…).
    error: Optional[str] = None
    #: Détails libres pour le débogage (jamais affichés tels quels).
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.price is not None and self.error is None


class FetchBlocked(Exception):
    """Le site refuse notre serveur (403 / captcha) : il faut passer par
    un navigateur (VPS de scraping)."""


# ───────────────────────── utilitaires communs ─────────────────────────

_MONEY_RE = re.compile(r"(\d{1,3}(?:[  ,]\d{3})*|\d+)(?:[.,](\d{1,2}))?")


def parse_money(text: Any) -> Optional[float]:
    """« 1 234,56 $ », « $1,234.56 », « 12,99 » → 1234.56 / 12.99."""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return round(float(text), 2)
    s = str(text).strip().replace(" ", " ")
    if not s:
        return None
    m = _MONEY_RE.search(s)
    if not m:
        return None
    whole = re.sub(r"[ ,]", "", m.group(1))
    frac = m.group(2) or "0"
    try:
        return round(float(f"{whole}.{frac}"), 2)
    except ValueError:
        return None


_FR_MONTHS = {
    "janv": 1, "janvier": 1, "fév": 2, "fev": 2, "février": 2, "fevrier": 2,
    "mars": 3, "avr": 4, "avril": 4, "mai": 5, "juin": 6, "juil": 7,
    "juillet": 7, "août": 8, "aout": 8, "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10, "nov": 11, "novembre": 11, "déc": 12,
    "dec": 12, "décembre": 12, "decembre": 12,
}
_EN_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_DATE_ISO_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_DATE_FR_RE = re.compile(
    r"(\d{1,2})(?:er)?\s+([a-zéû]+)\.?(?:\s+(20\d{2}))?", re.IGNORECASE
)
_DATE_EN_RE = re.compile(
    r"([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?(?:\s+(20\d{2}))?", re.IGNORECASE
)


def parse_date_any(text: Any, *, today: Optional[date] = None) -> Optional[date]:
    """« 2026-10-02 », « jusqu'au 2 octobre », « until Oct 2, 2026 »…
    Sans année : l'année courante, ou la suivante si la date est déjà
    passée de plus de 30 jours (une promo annoncée « jusqu'au 5 janvier »
    en décembre vise l'an prochain)."""
    if text is None:
        return None
    if isinstance(text, date) and not isinstance(text, datetime):
        return text
    if isinstance(text, datetime):
        return text.date()
    s = str(text).strip().lower()
    today = today or date.today()
    m = _DATE_ISO_RE.search(s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _DATE_FR_RE.search(s)
    if m and m.group(2).rstrip(".") in _FR_MONTHS:
        d, mo, y = int(m.group(1)), _FR_MONTHS[m.group(2).rstrip(".")], m.group(3)
        return _resolve_year(d, mo, int(y) if y else None, today)
    m = _DATE_EN_RE.search(s)
    if m and m.group(1).rstrip(".") in _EN_MONTHS:
        mo, d, y = _EN_MONTHS[m.group(1).rstrip(".")], int(m.group(2)), m.group(3)
        return _resolve_year(d, mo, int(y) if y else None, today)
    return None


def _resolve_year(d: int, mo: int, y: Optional[int], today: date) -> Optional[date]:
    try:
        if y:
            return date(y, mo, d)
        cand = date(today.year, mo, d)
        if (today - cand).days > 30:
            cand = date(today.year + 1, mo, d)
        return cand
    except ValueError:
        return None


def iter_jsonld(html: str) -> list[Any]:
    """Tous les blocs <script type="application/ld+json"> décodés
    (listes et @graph aplatis)."""
    out: list[Any] = []
    for m in re.finditer(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html, re.S | re.I,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:
                data = json.loads(_html.unescape(raw))
            except json.JSONDecodeError:
                continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("@graph"), list):
                out.extend(x for x in it["@graph"] if isinstance(x, dict))
            elif isinstance(it, dict):
                out.append(it)
    return out


def _first_offer(product: dict) -> Optional[dict]:
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = next((o for o in offers if isinstance(o, dict)), None)
    return offers if isinstance(offers, dict) else None


def parse_generic(html: str, url: str = "") -> PrixReleve:
    """Données structurées standard : JSON-LD Product/Offer, puis
    OpenGraph, puis microdonnées. Sert de repli à tout parseur."""
    for node in iter_jsonld(html):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if not any(str(x).lower() in ("product", "productmodel", "individualproduct") for x in types):
            continue
        offer = _first_offer(node) or {}
        price = parse_money(offer.get("price") or offer.get("lowPrice"))
        if price is None and isinstance(offer.get("priceSpecification"), dict):
            price = parse_money(offer["priceSpecification"].get("price"))
        if price is None:
            continue
        valid = parse_date_any(offer.get("priceValidUntil"))
        avail = str(offer.get("availability") or "").lower()
        return PrixReleve(
            price=price,
            currency=str(offer.get("priceCurrency") or "CAD"),
            title=(str(node.get("name")) if node.get("name") else None),
            sku=(str(node.get("sku")) if node.get("sku") else None),
            in_stock=(True if "instock" in avail else (False if "outofstock" in avail else None)),
            sale_end=valid,
            method="jsonld",
        )
    m = re.search(
        r"<meta[^>]+property=[\"']product:price:amount[\"'][^>]+content=[\"']([^\"']+)", html, re.I
    ) or re.search(
        r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+property=[\"']product:price:amount[\"']", html, re.I
    )
    if m:
        price = parse_money(m.group(1))
        if price is not None:
            return PrixReleve(price=price, method="og")
    m = re.search(r"itemprop=[\"']price[\"'][^>]*content=[\"']([^\"']+)", html, re.I)
    if m:
        price = parse_money(m.group(1))
        if price is not None:
            return PrixReleve(price=price, method="microdata")
    return PrixReleve(error="Aucun prix reconnu dans la page (pas de données structurées).")


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


#: Domaine → nom de module dans ce paquet.
REGISTRY: dict[str, str] = {
    "homedepot.ca": "homedepot",
    "patrickmorin.com": "patrickmorin",
    "canac.ca": "canac",
    "rona.ca": "rona",
    "renodepot.com": "rona",
    "bmr.ca": "bmr",
}


def parser_for(url: str):
    """Module de parseur pour cette URL, ou None (→ parse_generic)."""
    dom = domain_of(url)
    name = REGISTRY.get(dom)
    if not name:
        # sous-domaine (ex. fr.canac.ca)
        for d, n in REGISTRY.items():
            if dom.endswith("." + d):
                name = n
                break
    if not name:
        return None
    try:
        return importlib.import_module(f"{__name__}.{name}")
    except Exception as exc:  # noqa: BLE001
        log.warning("Parseur %s indisponible : %s", name, exc)
        return None


def parse(html: str, url: str) -> PrixReleve:
    """Parseur du magasin si connu, sinon générique ; jamais d'exception."""
    mod = parser_for(url)
    try:
        if mod is not None and hasattr(mod, "parse"):
            res = mod.parse(html, url)
            if res.ok:
                return res
            fallback = parse_generic(html, url)
            return fallback if fallback.ok else res
        return parse_generic(html, url)
    except Exception as exc:  # noqa: BLE001
        log.warning("Parseur %s a levé %s pour %s", getattr(mod, "__name__", "generic"), exc, url)
        return PrixReleve(error=f"Lecture de la page échouée : {exc}")
