"""Position approximative à partir de l'adresse IP (Steven, 2026-10-29).

Quand l'employé refuse la localisation du téléphone au punch, « on va y
aller approximatif » : l'API déduit une position de son adresse
internet. C'est la ville (ou le relais de l'opérateur mobile), jamais
le chantier — la position est marquée approximative partout où elle
s'affiche.

Fournisseur : ipwho.is (gratuit, sans clé, usage commercial permis).
Une seule requête courte par punch, résultat gardé en mémoire 24 h par
adresse pour ne pas rappeler le service à chaque punch du même
téléphone. Tout échec (délai, adresse privée, réponse inattendue) donne
``None`` : le punch part sans position.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from typing import Dict, Optional, Tuple

import httpx

log = logging.getLogger(__name__)

IP_GEO_URL = "https://ipwho.is/{ip}"
#: Délai court : la requête est faite pendant le punch de l'employé.
DELAI_S = 2.5
CACHE_TTL_S = 24 * 3600
CACHE_MAX = 5000

_cache: Dict[str, Tuple[float, Optional[Tuple[float, float]]]] = {}


def ip_publique(ip: Optional[str]) -> Optional[str]:
    """L'adresse telle quelle si elle est publique, sinon None (réseau
    local, boucle locale, tests)."""
    if not ip:
        return None
    brut = ip.strip()
    try:
        adresse = ipaddress.ip_address(brut)
    except ValueError:
        return None
    if not adresse.is_global:
        return None
    return brut


async def _interroger(ip: str) -> Optional[Tuple[float, float]]:
    """Appel réseau brut (doublé dans les tests)."""
    async with httpx.AsyncClient(timeout=DELAI_S) as http:
        r = await http.get(
            IP_GEO_URL.format(ip=ip),
            params={"fields": "success,latitude,longitude"},
            headers={"User-Agent": "h2.0-Horizon/1.0 (contact@immohorizon.com)"},
        )
    if r.status_code != 200:
        log.info("ip_geo %s -> HTTP %s", ip, r.status_code)
        return None
    data = r.json()
    if not isinstance(data, dict) or data.get("success") is False:
        return None
    try:
        return float(data["latitude"]), float(data["longitude"])
    except (KeyError, TypeError, ValueError):
        return None


async def position_par_ip(ip: Optional[str]) -> Optional[Tuple[float, float]]:
    """``(lat, lng)`` approximatifs de l'adresse, ou None."""
    publique = ip_publique(ip)
    if publique is None:
        return None
    maintenant = time.monotonic()
    en_cache = _cache.get(publique)
    if en_cache is not None and en_cache[0] > maintenant:
        return en_cache[1]
    try:
        resultat = await _interroger(publique)
    except Exception as exc:  # noqa: BLE001 — jamais bloquer un punch
        log.info("ip_geo %s indisponible : %s", publique, exc)
        resultat = None
    if len(_cache) >= CACHE_MAX:
        _cache.clear()
    _cache[publique] = (maintenant + CACHE_TTL_S, resultat)
    return resultat


def vider_cache() -> None:
    _cache.clear()
