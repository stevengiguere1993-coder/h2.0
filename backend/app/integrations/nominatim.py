"""Reverse-geocoding via Nominatim (OpenStreetMap, gratuit).

Usage policy de Nominatim :
- Max 1 requête par seconde (on ne fait que des requêtes ponctuelles
  côté serveur — pas de batch)
- User-Agent identifiable obligatoire
- Cache des résultats côté nous (on stocke directement dans le lead)

Doc : https://operations.osmfoundation.org/policies/nominatim/
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger(__name__)

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "h2.0-Horizon/1.0 (contact@immohorizon.com)"


async def geocode_address(query: str) -> Optional[Dict[str, float]]:
    """Forward-geocoding : transforme une adresse texte en coordonnées.

    Renvoie ``{"lat": ..., "lng": ...}`` ou ``None`` si Nominatim ne
    trouve rien. Restreint au Canada. Sert à géolocaliser les leads
    saisis par adresse (sans GPS drive-by) pour qu'ils apparaissent
    sur la carte et soient sélectionnables dans « Planifier ma route ».
    """
    q = (query or "").strip()
    if not q:
        return None
    params = {
        "format": "jsonv2",
        "q": q,
        "limit": "1",
        "countrycodes": "ca",
        "accept-language": "fr-CA,fr;q=0.9,en;q=0.7",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.get(
                NOMINATIM_SEARCH_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
            )
            if r.status_code != 200:
                log.warning(
                    "Nominatim search '%s' -> %s", q, r.status_code
                )
                return None
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Nominatim search exception '%s': %s", q, exc)
        return None
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    try:
        return {
            "lat": float(first["lat"]),
            "lng": float(first["lon"]),
        }
    except (KeyError, ValueError, TypeError):
        return None


async def reverse_geocode(
    lat: float, lng: float
) -> Optional[Dict[str, Any]]:
    """Renvoie un dict avec address/city/postal_code/display_name à
    partir d'un couple lat/lng. None si Nominatim ne trouve rien.

    Format de retour :
        {
            "address": "529 Rue Castonguay",
            "city": "Saint-Jérôme",
            "postal_code": "J7Y 3N2",
            "display_name": "529 Rue Castonguay, Saint-Jérôme, ..."
        }
    """
    params = {
        "format": "jsonv2",
        "lat": str(lat),
        "lon": str(lng),
        "zoom": "18",
        "addressdetails": "1",
        "accept-language": "fr-CA,fr;q=0.9,en;q=0.7",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.get(
                NOMINATIM_REVERSE_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
            )
            if r.status_code != 200:
                log.warning(
                    "Nominatim %s -> %s: %s",
                    lat, lng, r.status_code, r.text[:200],
                )
                return None
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Nominatim exception for %s,%s: %s", lat, lng, exc)
        return None

    addr = data.get("address") or {}
    if not addr:
        return None

    # Construction de l'adresse civique : numéro + voie
    house_number = (addr.get("house_number") or "").strip()
    road = (
        addr.get("road")
        or addr.get("pedestrian")
        or addr.get("footway")
        or ""
    ).strip()
    address_line = (
        f"{house_number} {road}".strip() if house_number else road or None
    )

    # Ville : ordre de fallback selon ce que Nominatim retourne au QC
    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
        or addr.get("hamlet")
        or addr.get("suburb")
        or None
    )

    postal = (addr.get("postcode") or "").strip() or None

    return {
        "address": address_line,
        "city": city,
        "postal_code": postal,
        "display_name": data.get("display_name"),
    }
