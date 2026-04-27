"""Recherche de téléphones sur LesPAC et Kangalou par adresse / nom.

Approche :
1. On lance une requête de recherche sur chaque site (HTML).
2. On parse les liens des annonces les plus récentes.
3. On fetch chaque annonce et on extrait les numéros de téléphone via
   regex.
4. On dédoublonne et on retourne (numéro, source, snippet).

Robustesse :
- Timeout court par site (10 s) pour ne pas bloquer le caller.
- Try/except large : si un site change son HTML, on log et on continue
  sur le suivant — pas d'exception remontée à l'API.
- User-Agent navigateur pour passer les filtres anti-bot basiques.
- Concurrent par défaut (asyncio.gather) — délai user-perçu réduit.

Limites connues :
- Les annonces expirent après 30-90 jours selon le site. Si le proprio
  a publié il y a 6 mois, on ne trouvera rien.
- Numéros internationaux non gérés (focus Amérique du Nord).
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import List, Optional

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Numéros nord-américains : (xxx) xxx-xxxx, xxx-xxx-xxxx, xxx.xxx.xxxx,
# xxx xxx xxxx, +1 xxx xxx xxxx. On accepte les variations courantes.
PHONE_RE = re.compile(
    r"(?:\+?1[\s\-.]?)?"
    r"\(?([2-9]\d{2})\)?[\s\-.]?"
    r"(\d{3})[\s\-.]?"
    r"(\d{4})\b"
)

# Blocs HTML à exclure (footer / numéros corporatifs des plateformes).
EXCLUDED_NUMBERS = {
    "8005551212",  # placeholder fréquent
    "5555555555",
    # Numéros de service client connus :
    "5142523999",  # LesPAC support
    "8004631222",
}


def _normalize_phone(p: tuple[str, str, str]) -> str:
    """3 groupes regex → '514-555-1234'."""
    return f"{p[0]}-{p[1]}-{p[2]}"


def _phone_digits(p: tuple[str, str, str]) -> str:
    return f"{p[0]}{p[1]}{p[2]}"


def _strip_accents(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def extract_phones_from_html(html: str) -> List[str]:
    """Extrait tous les numéros NA-style d'un blob HTML/texte.
    Dédupliqué et filtré contre EXCLUDED_NUMBERS."""
    if not html:
        return []
    seen: set[str] = set()
    out: List[str] = []
    for m in PHONE_RE.finditer(html):
        groups = (m.group(1), m.group(2), m.group(3))
        digits = _phone_digits(groups)
        if digits in EXCLUDED_NUMBERS:
            continue
        if digits in seen:
            continue
        seen.add(digits)
        out.append(_normalize_phone(groups))
    return out


# --------------------------- LesPAC ---------------------------


async def search_lespac(
    http: httpx.AsyncClient, query: str, *, max_listings: int = 5
) -> List[dict]:
    """Cherche `query` sur lespac.com (toutes catégories) et extrait
    les numéros des N premières annonces.

    Returns : liste de {phone, source, snippet} dédupliqués par numéro.
    """
    if not query or len(query.strip()) < 3:
        return []
    try:
        # LesPAC utilise une URL de recherche simple :
        # https://www.lespac.com/recherche?q=<terme>
        r = await http.get(
            "https://www.lespac.com/recherche",
            params={"q": query},
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        if r.status_code != 200:
            log.info("LesPAC search %s -> %s", query, r.status_code)
            return []
        html = r.text
    except httpx.HTTPError as exc:
        log.info("LesPAC search erreur %s : %s", query, exc)
        return []

    # Récupère les liens vers les annonces individuelles.
    # Pattern observé : /annonce/12345-titre-de-l-annonce
    links = re.findall(
        r'href="(https?://[^"]*lespac\.com/annonce/[^"]+|/annonce/[^"]+)"',
        html,
    )
    # Dédup, normalise en URL absolue, garde max_listings premières.
    seen_links: set[str] = set()
    norm_links: List[str] = []
    for link in links:
        if link.startswith("/"):
            link = "https://www.lespac.com" + link
        if link in seen_links:
            continue
        seen_links.add(link)
        norm_links.append(link)
        if len(norm_links) >= max_listings:
            break

    out: List[dict] = []
    seen_phones: set[str] = set()
    for url in norm_links:
        try:
            r = await http.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            )
            if r.status_code != 200:
                continue
            phones = extract_phones_from_html(r.text)
            for p in phones:
                if p in seen_phones:
                    continue
                seen_phones.add(p)
                # Petit snippet : prend les 80 chars autour du numéro
                idx = r.text.find(p.replace("-", "")[:3])
                snippet = ""
                if idx > 0:
                    text_only = re.sub(r"<[^>]+>", " ", r.text)
                    text_only = re.sub(r"\s+", " ", text_only)
                    j = text_only.find(p[:7].replace("-", " "))
                    if j == -1:
                        j = text_only.find(p[:3])
                    if j > 0:
                        snippet = text_only[
                            max(0, j - 60) : min(len(text_only), j + 60)
                        ].strip()
                out.append(
                    {
                        "phone": p,
                        "source": "lespac",
                        "url": url,
                        "snippet": snippet[:200] if snippet else None,
                    }
                )
        except httpx.HTTPError:
            continue
    return out


# --------------------------- Kangalou ---------------------------


async def search_kangalou(
    http: httpx.AsyncClient, query: str, *, max_listings: int = 5
) -> List[dict]:
    """Cherche `query` sur kangalou.com (locations résidentielles QC).

    Kangalou liste les locations actives et recently expired. URL :
    https://www.kangalou.com/fr/recherche/?keywords=<terme>
    """
    if not query or len(query.strip()) < 3:
        return []
    try:
        r = await http.get(
            "https://www.kangalou.com/fr/recherche/",
            params={"keywords": query},
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        if r.status_code != 200:
            log.info(
                "Kangalou search %s -> %s", query, r.status_code
            )
            return []
        html = r.text
    except httpx.HTTPError as exc:
        log.info("Kangalou search erreur %s : %s", query, exc)
        return []

    # Récupère les liens vers les annonces individuelles.
    # Pattern observé : /fr/appartement/<slug>/<id>/
    links = re.findall(
        r'href="(/fr/appartement/[^"]+|https?://[^"]*kangalou\.com/fr/appartement/[^"]+)"',
        html,
    )
    seen_links: set[str] = set()
    norm_links: List[str] = []
    for link in links:
        if link.startswith("/"):
            link = "https://www.kangalou.com" + link
        if link in seen_links:
            continue
        seen_links.add(link)
        norm_links.append(link)
        if len(norm_links) >= max_listings:
            break

    out: List[dict] = []
    seen_phones: set[str] = set()
    for url in norm_links:
        try:
            r = await http.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            )
            if r.status_code != 200:
                continue
            phones = extract_phones_from_html(r.text)
            for p in phones:
                if p in seen_phones:
                    continue
                seen_phones.add(p)
                text_only = re.sub(r"<[^>]+>", " ", r.text)
                text_only = re.sub(r"\s+", " ", text_only)
                j = text_only.find(p[:7].replace("-", " "))
                if j == -1:
                    j = text_only.find(p[:3])
                snippet = ""
                if j > 0:
                    snippet = text_only[
                        max(0, j - 60) : min(len(text_only), j + 60)
                    ].strip()
                out.append(
                    {
                        "phone": p,
                        "source": "kangalou",
                        "url": url,
                        "snippet": snippet[:200] if snippet else None,
                    }
                )
        except httpx.HTTPError:
            continue
    return out


# --------------------------- Public API ---------------------------


async def find_phones(
    *,
    address: Optional[str] = None,
    owner_name: Optional[str] = None,
    city: Optional[str] = None,
    timeout: float = 12.0,
) -> List[dict]:
    """Cherche le téléphone d'un propriétaire en interrogeant en
    parallèle LesPAC et Kangalou.

    On essaie 2-3 stratégies de requête et on fusionne les résultats :
    - Adresse (« 4520 Saint-Laurent ») — plus précis
    - Nom du propriétaire — si disponible

    Returns : liste {phone, source, url, snippet} dédupliquée par
    numéro (cumul tous sites).
    """
    queries: List[str] = []
    if address:
        addr_clean = address.strip()
        if city:
            queries.append(f"{addr_clean} {city.strip()}")
        else:
            queries.append(addr_clean)
    if owner_name and len(owner_name.strip()) > 4:
        queries.append(owner_name.strip())
    if not queries:
        return []

    timeout_obj = httpx.Timeout(timeout, connect=5.0)
    all_results: List[dict] = []
    async with httpx.AsyncClient(
        timeout=timeout_obj, follow_redirects=True
    ) as http:
        tasks = []
        for q in queries:
            tasks.append(search_lespac(http, q))
            tasks.append(search_kangalou(http, q))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                all_results.extend(r)

    # Dédup par numéro (garde la première occurrence et son snippet).
    seen: set[str] = set()
    deduped: List[dict] = []
    for r in all_results:
        digits = re.sub(r"\D", "", r.get("phone", ""))
        if not digits or digits in seen:
            continue
        seen.add(digits)
        deduped.append(r)
    return deduped
