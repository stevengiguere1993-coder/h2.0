"""Cron : rappel quotidien des loyers en retard.

Crée une notification (cloche) pour les managers+ avec le nombre de loyers
en retard du mois courant. N'envoie RIEN aux locataires — les relances
individuelles (courriel) se font à la main depuis la page Loyers, pour
garder le contrôle sur ce qui part.

Usage (Render cron, en semaine après le 5 du mois) :
    python -m app.jobs.loyer_relances
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Logement,
    PaiementLoyer,
)
from app.services.notifications import notify_role


log = logging.getLogger(__name__)


async def _run() -> None:
    async with AsyncSessionLocal() as db:
        today = datetime.now(timezone.utc).date()
        # Même seuil que la page Loyers : on ne signale qu'après le 5.
        if today.day <= 5:
            return
        month_start = today.replace(day=1)

        # Immeubles en GESTION EXTERNE exclus : la perception des loyers
        # (et les relances) relève du gestionnaire tiers. isnot(True)
        # couvre aussi les NULL (lignes d'avant le backfill du default).
        baux = (
            await db.execute(
                select(Bail)
                .join(Logement, Logement.id == Bail.logement_id)
                .join(Immeuble, Immeuble.id == Logement.immeuble_id)
                .where(
                    Bail.status == BailStatus.ACTIF.value,
                    Immeuble.gestion_externe.isnot(True),
                )
            )
        ).scalars().all()
        if not baux:
            return

        bail_ids = [b.id for b in baux]
        paid = {
            row[0]
            for row in (
                await db.execute(
                    select(PaiementLoyer.bail_id).where(
                        PaiementLoyer.bail_id.in_(bail_ids),
                        PaiementLoyer.mois_couvert == month_start,
                    )
                )
            ).all()
        }
        retards = [b for b in baux if b.id not in paid]
        if not retards:
            return

        n = len(retards)
        montant = sum(float(b.loyer_mensuel or 0) for b in retards)
        await notify_role(
            db,
            min_role="manager",
            kind="loyer_retard",
            title=f"{n} loyer{'s' if n > 1 else ''} en retard ce mois",
            body=(
                f"Total dû : {montant:,.0f} $. "
                f"Relance-les depuis la page Loyers."
            ),
            href="/immobilier/baux",
        )
        await db.commit()
        log.info("loyer_relances: %d retard(s), %.0f$", n, montant)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())
