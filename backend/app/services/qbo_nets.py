"""Filets de synchronisation QBO exécutés PAR L'APPLICATION elle-même.

Les filets « horaires » (re-pousser les factures/dépenses sans miroir QB,
pull QB → Kratos) vivaient uniquement dans le mega-cron
/api/v1/cron/run/all-hourly — qui exige une configuration EXTERNE
(cron-job.org + CRON_SECRET). Si elle n'est pas en place, les filets ne
tournent JAMAIS : une facture dont le push à l'envoi a échoué en silence
(ex. factures 117/118) reste absente de QB pour toujours.

Ce module rend les filets autonomes : une boucle asyncio démarrée avec
l'app fait un premier passage ~90 s après le boot (rattrapage immédiat
post-deploy), puis toutes les heures. Garde anti-double-run via
cron_runs (multi-instances / all-hourly externe en parallèle) ; chaque
document reste idempotent (qbo_invoice_id / qbo_bill_id).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

log = logging.getLogger("qbo.nets")

_FIRST_RUN_DELAY_SECONDS = 90
_LOOP_INTERVAL_SECONDS = 3600
# < intervalle de boucle pour qu'un run planifié ne soit pas bloqué par
# le claim du run précédent.
_CLAIM_INTERVAL_SECONDS = 50 * 60


async def run_qbo_nets() -> Dict[str, Any]:
    """Exécute les filets QBO (best-effort, chaque volet isolé)."""
    from app.db.session import AsyncSessionLocal
    from app.services.cron_guard import claim_cron_run
    from app.services.qbo_auto_sync import is_qbo_auto_sync_enabled

    async with AsyncSessionLocal() as gdb:
        if not await claim_cron_run(gdb, "qbo-nets", _CLAIM_INTERVAL_SECONDS):
            return {"skipped": "run_recent"}

    if not await is_qbo_auto_sync_enabled():
        return {"skipped": "qbo_auto_sync_off"}

    out: Dict[str, Any] = {}

    # ── Factures clients émises sans miroir QB → re-push ──
    try:
        from sqlalchemy import select

        from app.models.facture import Facture
        from app.services.facture_qbo import sync_facture_to_qbo

        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(Facture.id, Facture.reference).where(
                        Facture.status.in_(("sent", "paid", "overdue")),
                        Facture.qbo_invoice_id.is_(None),
                        Facture.client_id.is_not(None),
                    )
                )
            ).all()
        pushed = failed = 0
        errors: Dict[str, str] = {}
        for fid, ref in rows:
            try:
                async with AsyncSessionLocal() as s:
                    await sync_facture_to_qbo(s, int(fid))
                    await s.commit()
                pushed += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                if len(errors) < 5:
                    errors[str(ref or fid)] = str(exc)[:200]
                # log.ERROR (pas warning) : c'est exactement l'échec
                # silencieux qu'on veut rendre visible dans les logs.
                log.error(
                    "Facture %s : push QB échoué : %s", ref or fid, exc
                )
        out["factures"] = {
            "candidates": len(rows),
            "pushed": pushed,
            "failed": failed,
            **({"errors": errors} if errors else {}),
        }
    except Exception:  # noqa: BLE001
        log.warning("Filet factures échoué", exc_info=True)

    # ── Dépenses actives sans lien QB → re-push ──
    try:
        from sqlalchemy import select

        from app.models.achat import Achat
        from app.services.achat_qbo import sync_achat_to_qbo

        recent = datetime.now(timezone.utc) - timedelta(days=14)
        async with AsyncSessionLocal() as db:
            ids = [
                int(r[0])
                for r in (
                    await db.execute(
                        select(Achat.id).where(
                            (
                                Achat.project_id.is_not(None)
                                | (Achat.created_at >= recent)
                            ),
                            Achat.status.in_(("received", "paid")),
                            Achat.qbo_bill_id.is_(None),
                            Achat.qbo_purchase_id.is_(None),
                        )
                    )
                ).all()
            ]
        pushed = failed = 0
        for aid in ids:
            try:
                async with AsyncSessionLocal() as s:
                    await sync_achat_to_qbo(s, aid)
                    await s.commit()
                pushed += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log.error("Achat %s : push QB échoué : %s", aid, exc)
        out["achats"] = {
            "candidates": len(ids),
            "pushed": pushed,
            "failed": failed,
        }
    except Exception:  # noqa: BLE001
        log.warning("Filet achats échoué", exc_info=True)

    # ── Pull QB → Kratos (coûts, fournisseurs, paiements, reçus) ──
    try:
        from app.services.qbo_cost_pull import pull_project_costs_from_qbo

        async with AsyncSessionLocal() as db:
            out["cost_pull"] = await pull_project_costs_from_qbo(
                db, dry_run=False
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        log.warning("Filet pull coûts échoué", exc_info=True)

    log.info("Filets QBO exécutés : %s", out)
    return out


async def qbo_nets_loop() -> None:
    """Boucle de fond démarrée avec l'app : 1ᵉʳ passage ~90 s après le
    boot (rattrapage post-deploy), puis toutes les heures."""
    delay = _FIRST_RUN_DELAY_SECONDS
    while True:
        try:
            await asyncio.sleep(delay)
            delay = _LOOP_INTERVAL_SECONDS
            await run_qbo_nets()
        except asyncio.CancelledError:  # arrêt de l'app
            raise
        except Exception:  # noqa: BLE001
            log.warning("Boucle filets QBO : itération échouée", exc_info=True)
