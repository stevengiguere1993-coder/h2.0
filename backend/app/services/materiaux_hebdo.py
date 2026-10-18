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
_TACHE_EN_COURS: Optional[asyncio.Task] = None


def est_la_nuit(now: Optional[datetime] = None) -> bool:
    local = (now or datetime.now(timezone.utc)).astimezone(TZ)
    return local.hour in HEURES_NUIT


async def job_hebdo(*, relever: bool = True, chercher: bool = True, analyser: bool = True) -> dict:
    """Le job lui-même (séquentiel, un seul à la fois par processus)."""
    global _TACHE_EN_COURS
    from app.db.session import AsyncSessionLocal

    if DERNIER_HEBDO.get("en_cours"):
        return {"skipped": "deja_en_cours"}
    etapes: dict = {}
    _TACHE_EN_COURS = asyncio.current_task()
    DERNIER_HEBDO.update(en_cours=True, lance_a=datetime.now(timezone.utc).isoformat(), termine_a=None, etapes=etapes)
    try:
        if relever:
            try:
                # Même course que le bouton « Actualiser les prix » : état
                # visible à l'écran, session par domaine, durée maximale,
                # arrêtable (alertes de rabais comprises).
                from app.services.materiaux_prix_auto import lancer_releve_en_fond

                tache = lancer_releve_en_fond(max_age_hours=None)
                r = (await tache) if tache is not None else {"skipped": "releve_deja_en_cours"}
                etapes["releve"] = {k: v for k, v in r.items() if k not in ("erreurs", "dernier")} | {"erreurs": len(r.get("erreurs") or [])}
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
                from app.services.materiaux_analyse_ia import lancer_analyse_en_fond

                tache = lancer_analyse_en_fond(limit=400, max_age_days=6)
                etapes["analyse_ia"] = (await tache) if tache is not None else {"skipped": "analyse_deja_en_cours"}
            except Exception as exc:  # noqa: BLE001
                log.exception("Hebdo matériaux : analyse IA échouée")
                etapes["analyse_ia"] = {"error": str(exc)[:200]}
    except asyncio.CancelledError:
        # Bouton « Arrêter » sur le job de nuit : l'étape en cours s'arrête
        # (son propre état est libéré par sa course), les suivantes ne
        # tournent pas ; le prochain passage nocturne reprendra.
        log.info("Hebdo matériaux : arrêté à la demande")
        etapes["annule"] = True
    finally:
        _TACHE_EN_COURS = None
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


def annuler_hebdo() -> bool:
    """Arrête le job de nuit en cours (et l'étape qu'il attend) ; True si
    un job tournait."""
    t = _TACHE_EN_COURS
    if t is not None and not t.done():
        t.cancel()
        return True
    if DERNIER_HEBDO.get("en_cours"):
        DERNIER_HEBDO.update(en_cours=False, termine_a=datetime.now(timezone.utc).isoformat())
        return True
    return False


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
