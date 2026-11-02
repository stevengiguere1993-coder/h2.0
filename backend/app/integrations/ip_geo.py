"""Position approximative à partir de l'adresse IP (Steven, 2026-10-29).

Quand l'employé refuse la localisation du téléphone au punch, « on va y
aller approximatif » : l'API déduit une position de son adresse
internet. C'est la ville (ou le relais de l'opérateur mobile), jamais
le chantier — la position est marquée approximative partout où elle
s'affiche.

Deux fournisseurs gratuits, sans clé, essayés dans l'ordre (ipwho.is,
puis ipapi.co) ; une réponse valable est gardée en mémoire 24 h par
adresse, un échec seulement 5 minutes (retour 2026-11-02 : un échec
passager ne doit pas priver une adresse de position pour la journée).
Tout échec donne ``None`` : le punch part sans position, et le journal
dit pourquoi.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

log = logging.getLogger(__name__)

#: Fournisseurs essayés dans l'ordre : (nom, gabarit d'URL, clé lat, clé lng).
FOURNISSEURS: List[Tuple[str, str, str, str]] = [
    ("ipwho.is", "https://ipwho.is/{ip}", "latitude", "longitude"),
    ("ipapi.co", "https://ipapi.co/{ip}/json/", "latitude", "longitude"),
]
#: Délai par fournisseur : la requête est faite pendant le punch.
DELAI_S = 3.0
CACHE_TTL_OK_S = 24 * 3600
CACHE_TTL_ECHEC_S = 5 * 60
CACHE_MAX = 5000
USER_AGENT = "h2.0-Horizon/1.0 (contact@immohorizon.com)"

_cache: Dict[str, Tuple[float, Optional[Tuple[float, float]]]] = {}


def ip_publique(ip: Optional[str]) -> Optional[str]:
    """L'adresse telle quelle si elle est publique, sinon None (réseau
    local, boucle locale, tests)."""
    if not ip:
        return None
    brut = ip.strip()
    # « [2607:...]:443 » ou « 24.1.2.3:51234 » : on garde l'adresse.
    if brut.startswith("["):
        brut = brut[1:].split("]")[0]
    elif brut.count(":") == 1:
        brut = brut.split(":")[0]
    try:
        adresse = ipaddress.ip_address(brut)
    except ValueError:
        return None
    if not adresse.is_global:
        return None
    return brut


async def _appeler(nom: str, gabarit: str, cle_lat: str, cle_lng: str, ip: str) -> Tuple[Optional[Tuple[float, float]], str]:
    """Un fournisseur : ``(coordonnées, explication)``."""
    async with httpx.AsyncClient(timeout=DELAI_S, follow_redirects=True) as http:
        r = await http.get(gabarit.format(ip=ip), headers={"User-Agent": USER_AGENT})
    if r.status_code != 200:
        return None, f"{nom}: HTTP {r.status_code} {r.text[:120]!r}"
    try:
        data: Any = r.json()
    except ValueError:
        return None, f"{nom}: réponse non JSON {r.text[:120]!r}"
    if not isinstance(data, dict):
        return None, f"{nom}: réponse inattendue"
    if data.get("success") is False or data.get("error") is True:
        return None, f"{nom}: refus {str(data.get('message') or data.get('reason') or '')[:120]!r}"
    try:
        lat, lng = float(data[cle_lat]), float(data[cle_lng])
    except (KeyError, TypeError, ValueError):
        return None, f"{nom}: pas de coordonnées dans la réponse"
    if lat == 0.0 and lng == 0.0:
        return None, f"{nom}: coordonnées nulles"
    return (lat, lng), f"{nom}: ok"


async def diagnostiquer(ip: str) -> Tuple[Optional[Tuple[float, float]], List[str]]:
    """Essaie chaque fournisseur ; renvoie les coordonnées du premier qui
    répond et le compte rendu de tous (pour le journal et le débogage)."""
    comptes: List[str] = []
    for nom, gabarit, cle_lat, cle_lng in FOURNISSEURS:
        try:
            coords, explication = await _appeler(nom, gabarit, cle_lat, cle_lng, ip)
        except Exception as exc:  # noqa: BLE001 — jamais bloquer un punch
            coords, explication = None, f"{nom}: {type(exc).__name__} {exc}"
        comptes.append(explication)
        if coords is not None:
            return coords, comptes
    return None, comptes


async def _interroger(ip: str) -> Optional[Tuple[float, float]]:
    """Appel réseau (doublé dans les tests)."""
    coords, comptes = await diagnostiquer(ip)
    if coords is None:
        log.warning("ip_geo : aucune position pour %s — %s", ip, " ; ".join(comptes))
    return coords


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
        log.warning("ip_geo %s indisponible : %s", publique, exc)
        resultat = None
    if len(_cache) >= CACHE_MAX:
        _cache.clear()
    ttl = CACHE_TTL_OK_S if resultat is not None else CACHE_TTL_ECHEC_S
    _cache[publique] = (maintenant + ttl, resultat)
    return resultat


def vider_cache() -> None:
    _cache.clear()
