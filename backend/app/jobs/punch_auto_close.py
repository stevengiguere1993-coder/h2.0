"""Cron : ferme automatiquement les punches restés ouverts (clock-out
oublié) et notifie les managers/propriétaires qu'ils ont des punches
à corriger.

Politique :
  - Chaque jour à 22:00 (heure de Montréal), on cherche les punches
    `ended_at IS NULL` dont `started_at < 22:00 du même jour Montréal`.
  - On les ferme à 22:00 ce jour-là (= durée plafonnée raisonnable).
  - On marque `approved = False` (sera dans la file d'approbation).
  - On ajoute une note `[AUTO-FERMÉ … à corriger]` pour signaler à
    qui regarde le tableau que ce punch est suspect.
  - On envoie une **notification unique** (cloche) aux managers+
    listant le nombre de punches auto-fermés.

Cas particulier : si un employé est encore en chantier après 22:00
(rare mais possible pour un dépannage), il pourra refaire le punch
manuellement ou un manager pourra corriger via la page Paie.

Usage local :
    python -m app.jobs.punch_auto_close
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.employe import Employe
from app.models.punch import Punch
from app.services.audit import log_action
from app.services.notifications import notify_role


log = logging.getLogger(__name__)

MONTREAL = ZoneInfo("America/Montreal")
AUTO_CLOSE_HOUR_LOCAL = 22  # 22:00 heure Montréal


def _previous_22h_montreal(now_utc: datetime) -> datetime:
    """Renvoie le dernier 22:00 Montréal passé, en UTC.

    Si la fonction est appelée à 23:30 EDT (= 03:30 UTC), retourne
    aujourd'hui 22:00 EDT. Si appelée à 21:00 EDT, retourne hier
    22:00 EDT (= la cible précédente).
    """
    now_mtl = now_utc.astimezone(MONTREAL)
    cutoff_mtl = now_mtl.replace(
        hour=AUTO_CLOSE_HOUR_LOCAL, minute=0, second=0, microsecond=0
    )
    if cutoff_mtl > now_mtl:
        cutoff_mtl -= timedelta(days=1)
    return cutoff_mtl.astimezone(timezone.utc)


async def _run() -> None:
    from app.services.automation_state import is_automation_enabled
    if not await is_automation_enabled("punch_auto_close"):
        return
    async with AsyncSessionLocal() as db:
        now_utc = datetime.now(timezone.utc)
        cutoff_utc = _previous_22h_montreal(now_utc)

        rows = (
            await db.execute(
                select(Punch).where(
                    Punch.ended_at.is_(None),
                    Punch.started_at < cutoff_utc,
                )
            )
        ).scalars().all()

        if not rows:
            log.info("punch-auto-close: aucun punch à fermer (cutoff=%s)", cutoff_utc.isoformat())
            await db.commit()
            return

        closed_count = 0
        names: list[str] = []
        for p in rows:
            # Ferme au 22:00 du jour où le punch a démarré (pas la date
            # courante — sinon un punch d'avant-hier oublié écope d'un
            # ended_at d'aujourd'hui).
            started_mtl = p.started_at.astimezone(MONTREAL)
            close_mtl = started_mtl.replace(
                hour=AUTO_CLOSE_HOUR_LOCAL, minute=0, second=0, microsecond=0
            )
            # Si pour une raison X le punch a commencé après 22:00 le
            # même jour (ex. 22:30), on ferme à started_at + 4 h pour
            # éviter ended_at < started_at.
            if close_mtl <= started_mtl:
                close_mtl = started_mtl + timedelta(hours=4)
            close_utc = close_mtl.astimezone(timezone.utc)

            started = p.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed = (close_utc - started).total_seconds() / 3600.0
            p.ended_at = close_utc
            p.hours = round(max(elapsed, 0), 2)
            p.approved = False
            tag = (
                "[AUTO-FERMÉ par le système — clock-out manquant, à corriger]"
            )
            p.notes = f"{p.notes}\n{tag}" if p.notes else tag

            emp = (
                await db.execute(
                    select(Employe).where(Employe.id == p.employe_id)
                )
            ).scalar_one_or_none()
            if emp:
                names.append(emp.full_name or f"#{emp.id}")
            closed_count += 1

            await log_action(
                db,
                user=None,
                action="punch.auto_closed",
                entity_type="punch",
                entity_id=p.id,
                details={
                    "employe_id": p.employe_id,
                    "started_at": p.started_at.isoformat(),
                    "auto_closed_at": close_utc.isoformat(),
                    "hours": float(p.hours),
                },
            )

        await db.flush()

        # Une seule notification cloche groupée pour les managers+.
        if closed_count > 0:
            body = "Employés concernés : " + ", ".join(sorted(set(names)))
            await notify_role(
                db,
                min_role="manager",
                kind="punch.auto_closed",
                title=(
                    f"{closed_count} punch{'s' if closed_count > 1 else ''} "
                    "auto-fermé(s) à 22 h — à corriger"
                ),
                body=body[:500],
                href="/app/punch/approbations",
            )

        await db.commit()
        log.info(
            "punch-auto-close: %d punch(es) fermé(s) (cutoff=%s)",
            closed_count,
            cutoff_utc.isoformat(),
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
