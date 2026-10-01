"""JOB DE NUIT HEBDOMADAIRE du catalogue de matériaux (retour Phil
2026-10-01) : « sortir les prix automatiquement une fois par semaine,
durant la nuit, afin de sortir les rabais », puis l'analyse IA des
derniers prix.

Enchaînement (chaque étape isolée : une qui échoue n'empêche pas les
suivantes) :

1. relevé COMPLET de toutes les offres avec lien produit (rabais + date
   de fin compris) — pas de filtre « vérifiée depuis 20 h » ;
2. recherche des prix de base manquants sur les sites (quota large,
   matériaux non cherchés depuis 1 jour) ;
3. alertes de rabais sur les listes d'achats des chantiers ;
4. analyse IA de l'historique (verdict bon moment / attendre…).

Déclenché par le mega-cron HORAIRE : la première heure entre 02:00 et
05:59 (heure de Montréal) où le dernier run date de plus de 6 jours. Pas
de réglage à faire côté cron-job.org. Forçable : ``POST
/api/v1/cron/run/materiaux-hebdo``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

TZ = ZoneInfo("America/Montreal")
HEURES_NUIT = range(2, 6)
INTERVALLE_S = 6 * 24 * 3600
LIMITE_RECHERCHE = 300

DERNIER_HEBDO: dict = {"en_cours": False, "lance_a": None, "termine_a": None, "etapes": None}
_TACHES: set = set()


def est_la_nuit(now: Optional[datetime] = None) -> bool:
    local = (now or datetime.now(timezone.utc)).astimezone(TZ)
    return local.hour in HEURES_NUIT


async def job_hebdo(*, relever: bool = True, chercher: bool = True, analyser: bool = True) -> dict:
    """Le job lui-même (séquentiel, un seul à la fois par processus)."""
    from app.db.session import AsyncSessionLocal

    if DERNIER_HEBDO.get("en_cours"):
        return {"skipped": "deja_en_cours"}
    etapes: dict = {}
    DERNIER_HEBDO.update(en_cours=True, lance_a=datetime.now(timezone.utc).isoformat(), termine_a=None, etapes=etapes)
    try:
        if relever:
            try:
                from app.services.materiaux_prix_auto import relever_tout

                async with AsyncSessionLocal() as db:
                    r = await relever_tout(db, max_age_hours=None)
                    await db.commit()
                etapes["releve"] = {k: v for k, v in r.items() if k != "erreurs"} | {"erreurs": len(r.get("erreurs") or [])}
            except Exception as exc:  # noqa: BLE001
                log.exception("Hebdo matériaux : relevé échoué")
                etapes["releve"] = {"error": str(exc)[:200]}
        if chercher:
            try:
                from app.services.materiaux_recherche import chercher_tout_pour_cron

                rc = await chercher_tout_pour_cron(limit=LIMITE_RECHERCHE, max_age_days=1)
                etapes["recherche"] = {k: v for k, v in rc.items() if k not in ("details", "dernier")}
            except Exception as exc:  # noqa: BLE001
                log.exception("Hebdo matériaux : recherche échouée")
                etapes["recherche"] = {"error": str(exc)[:200]}
        try:
            from app.services.materiaux_prix_auto import alerter_rabais_sans_casser

            async with AsyncSessionLocal() as db:
                etapes["alertes"] = await alerter_rabais_sans_casser(db)
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            etapes["alertes"] = {"error": str(exc)[:200]}
        if analyser:
            try:
                from app.services.materiaux_analyse_ia import analyser_tout

                async with AsyncSessionLocal() as db:
                    etapes["analyse_ia"] = await analyser_tout(db, limit=400, max_age_days=6)
            except Exception as exc:  # noqa: BLE001
                log.exception("Hebdo matériaux : analyse IA échouée")
                etapes["analyse_ia"] = {"error": str(exc)[:200]}
    finally:
        DERNIER_HEBDO.update(en_cours=False, termine_a=datetime.now(timezone.utc).isoformat())
    log.info("Hebdo matériaux terminé : %s", etapes)
    return etapes


def lancer_en_fond(**kwargs) -> bool:
    """Démarre le job en tâche de fond (le cron répond tout de suite)."""
    if DERNIER_HEBDO.get("en_cours"):
        return False
    task = asyncio.create_task(job_hebdo(**kwargs))
    _TACHES.add(task)
    task.add_done_callback(_TACHES.discard)
    return True


async def lancer_si_nuit_hebdo(now: Optional[datetime] = None) -> dict:
    """Appelé chaque heure par le mega-cron : lance le job la nuit, au
    plus une fois par 6 jours (verrou ``cron_runs`` partagé entre
    instances)."""
    if not est_la_nuit(now):
        return {"skipped": "pas la nuit (02:00–05:59 Montréal)"}
    if DERNIER_HEBDO.get("en_cours"):
        return {"skipped": "deja_en_cours"}
    from app.db.session import AsyncSessionLocal
    from app.services.cron_guard import claim_cron_run

    async with AsyncSessionLocal() as db:
        ok = await claim_cron_run(db, "materiaux-prix-hebdo", INTERVALLE_S)
        await db.commit()
    if not ok:
        return {"skipped": "run de moins de 6 jours"}
    return {"lance": lancer_en_fond()}
