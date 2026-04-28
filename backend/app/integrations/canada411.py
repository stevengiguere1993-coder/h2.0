"""Scraper Canada411 — recherche personne par nom + ville.

Quand on identifie un propriétaire (depuis EvalWeb/REQ) sans
téléphone, on tente un lookup Canada411 pour trouver le numéro
et compléter la fiche.

URL pattern :
  https://www.canada411.ca/search/?stype=si&what=<nom>&where=<ville>

Les résultats sont en HTML server-side. On extrait nom + adresse +
téléphone via BeautifulSoup. Anti-bot modéré (UA réaliste suffit).

⚠ Best-effort : si la structure HTML change ou si Canada411 met du
captcha, le lookup retourne juste « rien trouvé » — pas d'erreur
fatale. L'utilisateur peut toujours saisir le téléphone manuellement.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import List, Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.5",
}

_TIMEOUT = httpx.Timeout(15.0, connect=8.0)


_PHONE_RE = re.compile(
    r"(?<!\d)\(?(\d{3})\)?[\s\-.]?(\d{3})[\s\-.]?(\d{4})(?!\d)"
)


def _strip_accents(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", s or "")
        if not unicodedata.combining(c)
    )


def _format_phone(raw: str) -> Optional[str]:
    m = _PHONE_RE.search(raw)
    if not m:
        return None
    return f"({m.group(1)}) {m.group(2)}-{m.group(3)}"


async def lookup_by_name(
    name: str, *, city: Optional[str] = None
) -> List[dict]:
    """Recherche Canada411 pour `name` (et optionnellement `city`).

    Retourne une liste de dicts { name, address, city, phone, source_url }.
    Vide si rien trouvé ou si la requête échoue.
    """
    name_clean = (name or "").strip()
    if not name_clean:
        return []
    # Format Canada411 attend "Nom, Prénom" ou "Prénom Nom" — les
    # 2 marchent. On envoie tel quel.
    what = quote_plus(name_clean)
    where = quote_plus(city or "Quebec")
    url = (
        f"https://www.canada411.ca/search/?stype=si"
        f"&what={what}&where={where}"
    )

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=_TIMEOUT,
            follow_redirects=True,
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Canada411 error (%s): %s", url, exc)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results: List[dict] = []

    # Pattern actuel (avril 2026) : chaque résultat dans un
    # `<div class="listing">` ou `<article>`. On tombe en
    # fallback sur le texte plat si la structure n'est pas reconnue.
    items = soup.select("article, .listing, .listing__content")
    for item in items[:10]:
        text = item.get_text(" ", strip=True)
        if not text:
            continue

        # Nom : élément avec class « listing__name » ou h3/h2
        name_el = item.select_one(
            ".listing__name, h3, h2, .merchant__name"
        )
        found_name = (
            name_el.get_text(" ", strip=True) if name_el else None
        )

        # Adresse : class « listing__address » ou élément avec
        # « address »
        addr_el = item.select_one(".listing__address, address")
        found_addr = (
            addr_el.get_text(" ", strip=True) if addr_el else None
        )

        # Téléphone
        phone_el = item.select_one(
            ".listing__phone, [data-phone], .merchant__phone"
        )
        phone_raw = (
            phone_el.get_text(" ", strip=True)
            if phone_el
            else _format_phone(text)
        )
        phone = (
            _format_phone(phone_raw) if phone_raw else None
        )

        if not phone:
            continue

        results.append(
            {
                "name": found_name or name_clean,
                "address": found_addr,
                "phone": phone,
                "source_url": url,
                "source": "canada411",
            }
        )

    return results
