"""Date de DÉMARRAGE de la gestion locative (réglable dans Paramètres).

Retour Phil 2026-07-27 : « je commence à utiliser le pôle pour vrai —
tout ce qui est AVANT le 1er juillet 2026 ne doit plus être vrai /
d'actualité ». Concrètement, tout l'argent locatif (loyers échus,
paiements, frais ponctuels, revenus, facturation des frais de gestion)
est calculé À PARTIR de cette date : un locataire qui traînait avril +
mai + juin impayés repart à 0 $ en juillet.

Rien n'est supprimé en base — l'historique d'avant reste stocké, il est
simplement IGNORÉ partout dans les calculs et les affichages d'argent.
Changer la date dans Paramètres → Gestion locative rejoue tout : c'est
un curseur, pas une purge.

Clé de config partagée (``automation_settings``) pour que les endpoints
locatifs, la facturation des frais de gestion et le cron des relances
lisent tous LA MÊME date.
"""
from __future__ import annotations

import logging
from datetime import date

log = logging.getLogger("immobilier.demarrage")

#: Clé dans ``automation_settings`` (config JSON ``{"date": "AAAA-MM-JJ"}``).
DEMARRAGE_KEY = "immo.demarrage"

#: Défaut : 1er juillet 2026 (démarrage réel du pôle chez Phil).
DEFAULT_DEMARRAGE = date(2026, 7, 1)


def parse_demarrage(cfg: dict) -> date:
    """Date de la config, ou le défaut si absente/corrompue."""
    raw = (cfg or {}).get("date")
    if not raw:
        return DEFAULT_DEMARRAGE
    try:
        return date.fromisoformat(str(raw)).replace(day=1)
    except (TypeError, ValueError):
        log.warning("Date de démarrage locatif illisible (%r) — défaut", raw)
        return DEFAULT_DEMARRAGE


async def get_demarrage() -> date:
    """1er du mois à partir duquel les soldes locatifs comptent.

    FAIL-SAFE : le défaut si la table/config n'existe pas encore (les
    pages ne doivent jamais tomber pour un réglage manquant)."""
    from app.services.automation_state import get_automation_config

    return parse_demarrage(await get_automation_config(DEMARRAGE_KEY))


async def set_demarrage(db, valeur: date, *, user_id: int | None = None) -> date:
    """Enregistre la date (ramenée au 1er du mois). Ne commit pas."""
    from app.services.automation_state import set_automation_config

    d = valeur.replace(day=1)
    await set_automation_config(
        db, DEMARRAGE_KEY, {"date": d.isoformat()}, user_id=user_id
    )
    return d
