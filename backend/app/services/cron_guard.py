"""Garde d'idempotence pour les crons.

`claim_cron_run` tente de « réserver » l'exécution d'un job : elle ne
réussit que si le dernier run remonte à plus de `min_interval_seconds`.
L'opération est ATOMIQUE (upsert Postgres avec garde dans le WHERE), donc
deux appels concurrents ne peuvent pas réserver tous les deux — le second
est refusé et le job ne tourne pas en double.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


async def claim_cron_run(
    db: AsyncSession, job_name: str, min_interval_seconds: int
) -> bool:
    """Renvoie True si l'exécution est réservée (le job peut tourner),
    False si un run trop récent existe déjà (on saute pour éviter un
    double-envoi). Tolérant aux erreurs : en cas de souci SQL on autorise
    l'exécution (mieux vaut un run qu'un blocage permanent)."""
    try:
        row = (
            await db.execute(
                text(
                    """
                    INSERT INTO cron_runs (job_name, last_run_at)
                    VALUES (:job, now())
                    ON CONFLICT (job_name) DO UPDATE SET last_run_at = now()
                    WHERE cron_runs.last_run_at
                          < now() - make_interval(secs => :sec)
                    RETURNING job_name
                    """
                ),
                {"job": job_name, "sec": min_interval_seconds},
            )
        ).first()
        await db.commit()
        return row is not None
    except Exception as exc:  # noqa: BLE001
        log.warning("claim_cron_run(%s) a échoué, on autorise: %s", job_name, exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return True
