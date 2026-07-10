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

    out: Dict[str, Any] = {}

    # ── Paiements de factures non enregistrés dans QB → re-push ──
    # Un paiement entré dans Kratos doit TOUJOURS finir dans QB : si le
    # push immédiat (create/update payment) a échoué en silence, on le
    # rattrape ici. push_facture_payments_only retombe sur la synchro
    # complète si la facture n'a pas encore de miroir QB.
    #
    # IMPORTANT : ce filet n'est PAS conditionné à l'interrupteur de
    # migration `qbo_auto_sync` — au même titre que le push immédiat
    # (push_facture_payments_now). Enregistrer un paiement est une action
    # DÉLIBÉRÉE de l'utilisateur sur UNE facture précise (pas une création
    # de masse), et c'est idempotent (Payment.qbo_payment_id). Le gater
    # derrière `qbo_auto_sync` (OFF en régime normal après migration)
    # laissait les paiements dont le push immédiat avait échoué (ex. la
    # facture 117 « En retard » avec des virements enregistrés côté Kratos)
    # bloqués hors de QB pour toujours, faute de rattrapage.
    try:
        from sqlalchemy import select as _select

        from app.models.facture import Facture as _Facture
        from app.models.payment import Payment
        from app.services.facture_qbo import push_facture_payments_only

        async with AsyncSessionLocal() as db:
            fids = [
                int(r[0])
                for r in (
                    await db.execute(
                        _select(Payment.facture_id)
                        .join(_Facture, _Facture.id == Payment.facture_id)
                        .where(
                            Payment.qbo_payment_id.is_(None),
                            _Facture.status.notin_(("draft", "void")),
                        )
                        .distinct()
                    )
                ).all()
            ]
        pushed = failed = 0
        for fid in fids:
            try:
                async with AsyncSessionLocal() as s:
                    await push_facture_payments_only(s, fid)
                    await s.commit()
                pushed += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log.error(
                    "Facture %s : push des paiements QB échoué : %s",
                    fid,
                    exc,
                )
        out["paiements"] = {
            "factures": len(fids),
            "pushed": pushed,
            "failed": failed,
        }
    except Exception:  # noqa: BLE001
        log.warning("Filet paiements échoué", exc_info=True)

    # ── DÉCOCHE « à refacturer » dans QB pour les projets NON à contrat ──
    # Miroir (one-shot) du backfill Kratos `achat_unbill_non_contract_v2` :
    # les dépenses re-décochées côté Kratos (is_billable=False) doivent
    # passer BillableStatus=NotBillable dans QuickBooks. On re-synchronise
    # chaque dépense concernée QUI A un lien QB via sync_achat_to_qbo (qui
    # pose BillableStatus selon is_billable). NON conditionné à
    # `qbo_auto_sync` (correction déterministe, pas une création). One-shot
    # via applied_backfills ; borné (1000) et journalisé. Le marqueur n'est
    # posé QUE si QBO était disponible → sinon on réessaie au prochain tour.
    try:
        from sqlalchemy import select as _sel, text as _text

        from app.integrations.quickbooks import get_qbo
        from app.models.achat import Achat as _Achat
        from app.models.project import Project as _Project
        from app.models.soumission import Soumission as _Soum
        from app.services.achat_qbo import sync_achat_to_qbo

        _KEY = "decoche_non_contract_qb_v1"
        async with AsyncSessionLocal() as db:
            already = (
                await db.execute(
                    _text("SELECT 1 FROM applied_backfills WHERE key = :k"),
                    {"k": _KEY},
                )
            ).first()
        if already is None:
            _q = get_qbo()
            await _q._load_refresh_from_db()
            if _q.ready:
                async with AsyncSessionLocal() as db:
                    aids = [
                        int(r[0])
                        for r in (
                            await db.execute(
                                _sel(_Achat.id)
                                .join(
                                    _Project,
                                    _Project.id == _Achat.project_id,
                                )
                                .outerjoin(
                                    _Soum,
                                    _Soum.id == _Project.soumission_id,
                                )
                                .where(
                                    _Achat.is_billable.is_(False),
                                    _Achat.invoiced_at.is_(None),
                                    (
                                        _Achat.qbo_bill_id.is_not(None)
                                        | _Achat.qbo_purchase_id.is_not(None)
                                    ),
                                    (
                                        _Soum.id.is_(None)
                                        | (_Soum.kind != "contract")
                                    ),
                                )
                                .limit(1000)
                            )
                        ).all()
                    ]
                ok = ko = 0
                for aid in aids:
                    try:
                        async with AsyncSessionLocal() as s:
                            await sync_achat_to_qbo(s, aid)
                            await s.commit()
                        ok += 1
                    except Exception as exc:  # noqa: BLE001
                        ko += 1
                        log.error(
                            "Décoche QB achat %s échouée : %s", aid, exc
                        )
                async with AsyncSessionLocal() as s:
                    await s.execute(
                        _text(
                            "INSERT INTO applied_backfills (key) "
                            "VALUES (:k) ON CONFLICT (key) DO NOTHING"
                        ),
                        {"k": _KEY},
                    )
                    await s.commit()
                out["decoche_non_contract"] = {
                    "candidats": len(aids),
                    "ok": ok,
                    "ko": ko,
                }
    except Exception:  # noqa: BLE001
        log.warning(
            "Décoche QB non-contrat (one-shot) échouée", exc_info=True
        )

    # ── Pull QB → Kratos (coûts, fournisseurs, paiements, reçus) ──
    # TOUJOURS exécuté (non conditionné à l'interrupteur de migration) : ce
    # pull est le FILET DE SECOURS du webhook Intuit — si un webhook se perd
    # (service endormi, signature rejetée, réseau), c'est lui qui fait
    # converger Kratos vers QB dans l'heure. Il est idempotent (clés = Id
    # QBO + dédup après import) : le gater derrière `qbo_auto_sync` (OFF en
    # régime normal) laissait toute modification QB manquée invisible pour
    # toujours — contraire au miroir attendu.
    try:
        from app.services.qbo_cost_pull import pull_project_costs_from_qbo

        async with AsyncSessionLocal() as db:
            out["cost_pull"] = await pull_project_costs_from_qbo(
                db, dry_run=False
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        log.warning("Filet pull coûts échoué", exc_info=True)

    # ── Heures approuvées sans feuille de temps QB → push ──
    # Punches approuvés + terminés + liés à un projet dont la TimeActivity
    # QB n'existe pas encore (push immédiat échoué ou antérieur à la
    # fonctionnalité). Suivi de projet SANS écriture comptable ; idempotent
    # (Punch.qbo_time_activity_id) → non gated.
    try:
        from app.services.labour_time_qbo import push_pending_punch_times

        async with AsyncSessionLocal() as db:
            out["heures"] = await push_pending_punch_times(db)
            await db.commit()
    except Exception:  # noqa: BLE001
        log.warning("Filet feuilles de temps échoué", exc_info=True)

    # ── Factures clients émises sans miroir QB → re-push ──
    # NON gated : envoyer une facture au client est une action DÉLIBÉRÉE —
    # elle DOIT finir dans QuickBooks. Si l'auto-push à l'envoi a échoué
    # (fond, silencieux), c'est ce filet qui rattrape dans l'heure.
    # Idempotent : qbo_invoice_id + rattachement par DocNumber (jamais de
    # doublon : une facture au même numéro est reliée, pas recréée).
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

    # Les filets de CRÉATION en masse restants (dépenses sans miroir QB)
    # restent conditionnés à l'interrupteur de migration : tant qu'il est
    # OFF, on ne (re)crée RIEN automatiquement pour ne pas produire de
    # doublons pendant que tous les ID QBO ne sont pas reliés.
    if not await is_qbo_auto_sync_enabled():
        out["skipped_migration_nets"] = "qbo_auto_sync_off"
        log.info("Filets QBO exécutés : %s", out)
        return out

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
