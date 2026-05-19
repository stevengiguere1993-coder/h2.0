"""OpenRouteService — calcul de temps de trajet entre coordonnées.

Free tier : 2000 requêtes / jour, 40 req/min. Largement assez pour
les besoins agenda d'Horizon.

Doc : https://openrouteservice.org/dev/#/api-docs/v2/matrix/profile/post
API key gratuite : https://openrouteservice.org/dev/#/signup

Configuration :
  - OPENROUTESERVICE_API_KEY (env var)

Si la clé n'est pas configurée, `travel_time_seconds()` renvoie None
et l'appelant doit fallback sur une heuristique (distance euclidienne
× vitesse moyenne 35 km/h en ville).
"""

from __future__ import annotations

import logging
import math
import os
from typing import Optional, Tuple

import httpx

log = logging.getLogger(__name__)

_MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/driving-car"


def is_configured() -> bool:
    return bool(os.getenv("OPENROUTESERVICE_API_KEY"))


async def travel_time_seconds(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
) -> Optional[int]:
    """Retourne le temps de trajet en voiture (secondes) entre deux
    coordonnées (lat, lng). None si l'API n'est pas configurée ou
    en erreur."""
    api_key = os.getenv("OPENROUTESERVICE_API_KEY", "").strip()
    if not api_key:
        return None
    payload = {
        # OpenRouteService veut [lng, lat] (pas l'inverse).
        "locations": [
            [float(origin[1]), float(origin[0])],
            [float(destination[1]), float(destination[0])],
        ],
        "metrics": ["duration"],
        "sources": [0],
        "destinations": [1],
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                _MATRIX_URL,
                headers={
                    "Authorization": api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
            )
            if r.status_code >= 400:
                log.warning(
                    "OpenRouteService matrix failed: %s %s",
                    r.status_code, r.text[:200],
                )
                return None
            data = r.json()
            durations = data.get("durations") or []
            if not durations or not durations[0]:
                return None
            secs = durations[0][0]
            if secs is None:
                return None
            return int(secs)
    except Exception as exc:  # noqa: BLE001
        log.warning("OpenRouteService matrix error: %s", exc)
        return None


def haversine_fallback_seconds(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    avg_kmh: float = 35.0,
) -> int:
    """Fallback heuristique quand OpenRouteService n'est pas dispo.
    Distance à vol d'oiseau × 1.3 (facteur tortuosité urbaine) /
    vitesse moyenne. Largement approximatif mais évite de bloquer la
    fonctionnalité si l'API key n'est pas configurée."""
    lat1, lng1 = math.radians(origin[0]), math.radians(origin[1])
    lat2, lng2 = math.radians(destination[0]), math.radians(destination[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.asin(min(1, math.sqrt(a)))
    km = 6371 * c * 1.3  # facteur tortuosité urbaine
    return int(km / max(avg_kmh, 1) * 3600)
