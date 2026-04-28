"""Banque du Canada — taux hypothécaires courants.

Source : Banque du Canada Valet API (gratuite, pas de clé requise).
https://www.bankofcanada.ca/valet/docs

Séries pertinentes pour l'analyse multi-logements :
- V80691311 : Taux affichés - prêt hypothécaire 5 ans (les Big 6)
  Note : c'est le taux « affiché » des grandes banques, qui sert de
  référence. Le taux RÉELLEMENT négocié est ~1.5% en dessous (chartered
  banks accordent typiquement des escomptes).
- V122544 : Obligations Canada 5 ans (proxy bas de gamme du taux fixe)

Fallback : si la BdC est inaccessible, on retourne None et le wizard
laisse le champ vide pour saisie manuelle.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import httpx

log = logging.getLogger(__name__)

VALET_BASE = "https://www.bankofcanada.ca/valet/observations"

# Code de série « V80691311 » = taux affichés 5 ans des banques.
# « V122544 » = rendement obligations Canada 5 ans (proxy bas-bound).
SERIES_5Y_POSTED = "V80691311"
SERIES_5Y_BOND = "V122544"


async def fetch_latest_rate(series_id: str) -> Optional[dict]:
    """Récupère la dernière observation d'une série Valet.

    Retourne { date, value } ou None si erreur réseau.
    """
    url = f"{VALET_BASE}/{series_id}/json?recent=1"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as exc:
        log.warning("Valet API error %s : %s", series_id, exc)
        return None

    obs = data.get("observations") or []
    if not obs:
        return None
    last = obs[-1]
    # Format Valet : { "d": "2026-04-25", "<series>": { "v": "5.49" } }
    obs_date = last.get("d")
    val_obj = last.get(series_id) or {}
    val_str = val_obj.get("v")
    if val_str is None:
        return None
    try:
        # Le taux est en %. On retourne en décimal (5.49 → 0.0549).
        value = float(val_str) / 100.0
    except ValueError:
        return None
    return {"date": obs_date, "value": value, "series": series_id}


async def get_current_rates() -> dict:
    """Retourne les taux courants utiles au calculateur.

    Format :
    {
      "fixed_5y_posted": { date, value, source },
      "fixed_5y_bond_proxy": { date, value, source },
      "fetched_at": iso datetime,
    }
    Les valeurs sont en décimal (4.49% → 0.0449).
    """
    posted = await fetch_latest_rate(SERIES_5Y_POSTED)
    bond = await fetch_latest_rate(SERIES_5Y_BOND)
    return {
        "fixed_5y_posted": (
            {**posted, "source": "Banque du Canada"}
            if posted
            else None
        ),
        "fixed_5y_bond_proxy": (
            {**bond, "source": "Banque du Canada"} if bond else None
        ),
        "fetched_at": datetime.utcnow().isoformat(),
    }
