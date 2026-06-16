"""Import QB → Kratos des factures clients (Invoices).

RÈGLE : une facture QuickBooks n'est importée dans Kratos QUE si elle est
rattachée à un PROJET — c.-à-d. que son CustomerRef pointe vers un « Job »
(sous-client) déjà relié à un projet Kratos (`Project.qbo_job_id`). Sinon
elle est ignorée. Idempotent : dédoublonnage par `qbo_invoice_id`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.facture import Facture
from app.models.payment import Payment
from app.models.project import Project

log = logging.getLogger(__name__)


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None


async def _invoice_payments_index(qbo, cutoff: str) -> dict[str, list[dict]]:
    """Index `invoice_id -> [{id, amount, txn_date}]` à partir des Payment
    QB — pour refléter CHAQUE paiement QB en ligne de paiement Kratos. Une
    seule requête (pas de martèlement de l'API)."""
    try:
        rows = await qbo.query(
            f"SELECT * FROM Payment WHERE TxnDate >= '{cutoff}' "
            "MAXRESULTS 1000"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("QBO Payment query failed: %s", exc)
        return {}
    idx: dict[str, list[dict]] = {}
    for p in rows:
        pid = str(p.get("Id") or "")
        if not pid:
            continue
        txn_date = p.get("TxnDate")
        for line in p.get("Line") or []:
            amt = _num(line.get("Amount"))
            for lt in line.get("LinkedTxn") or []:
                if str(lt.get("TxnType")) == "Invoice":
                    inv = str(lt.get("TxnId") or "")
                    if inv:
                        idx.setdefault(inv, []).append(
                            {
                                "id": pid,
                                "amount": amt or _num(p.get("TotalAmt")),
                                "txn_date": txn_date,
                            }
                        )
    return idx


async def pull_invoices_from_qbo(
    db: AsyncSession,
    *,
    since_days: int = 180,
    dry_run: bool = False,
    client_id: Optional[int] = None,
) -> dict:
    from app.integrations.quickbooks import QuickBooksError, get_qbo

    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        return {"error": "QuickBooks non connecté (OAuth)."}

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=since_days)
    ).strftime("%Y-%m-%d")
    try:
        invoices = await qbo.query(
            f"SELECT * FROM Invoice WHERE TxnDate >= '{cutoff}' "
            "ORDER BY TxnDate DESC MAXRESULTS 1000"
        )
    except QuickBooksError as exc:
        return {"error": f"Requête QB Invoices échouée : {exc}"}

    # Factures déjà reliées, par ID QBO — sert au dédoublonnage ET à la
    # mise à jour du statut « payé » (QB → Kratos).
    existing_by_qid: dict[str, Facture] = {
        str(f.qbo_invoice_id): f
        for f in (
            await db.execute(
                select(Facture).where(Facture.qbo_invoice_id.is_not(None))
            )
        ).scalars().all()
    }
    # Projet par Job QBO (clé de rattachement). Scopé à un client si
    # demandé (« importer tout d'un client »).
    pstmt = select(Project).where(Project.qbo_job_id.is_not(None))
    if client_id is not None:
        pstmt = pstmt.where(Project.client_id == client_id)
    proj_by_job: dict[str, Project] = {
        str(p.qbo_job_id): p
        for p in (await db.execute(pstmt)).scalars().all()
    }
    # Refs QB du client (parent + sous-clients) : sert à NE GARDER que
    # les transactions de ce client dans l'aperçu détaillé.
    client_refs: Optional[set[str]] = None
    if client_id is not None:
        from app.models.client import Client

        client = (
            await db.execute(select(Client).where(Client.id == client_id))
        ).scalar_one_or_none()
        client_refs = set(proj_by_job.keys())
        if client and client.qbo_customer_id:
            client_refs.add(str(client.qbo_customer_id))

    # Index des paiements QB par facture (pour le miroir par virement) +
    # garde anti-doublon des virements déjà reflétés dans Kratos.
    pay_idx = await _invoice_payments_index(qbo, cutoff)
    existing_pay_ids: set[str] = {
        str(r[0])
        for r in (
            await db.execute(
                select(Payment.qbo_payment_id).where(
                    Payment.qbo_payment_id.is_not(None)
                )
            )
        ).all()
    }

    now = datetime.now(timezone.utc)
    stats = {
        "dry_run": dry_run,
        "scope": "client" if client_id is not None else "all",
        "total_qbo": len(invoices),
        "imported": 0,
        "skipped_existing": 0,
        "skipped_no_project": 0,
        "paid_synced": 0,
        "payments_mirrored": 0,
    }
    preview: list[dict] = []

    async def _mirror_payments(facture_id: int, inv_id: str) -> int:
        """Crée une ligne de paiement Kratos pour chaque Payment QB lié à
        cette facture, pas encore reflété. Retourne le nombre créé."""
        created = 0
        for qp in pay_idx.get(inv_id, []):
            if qp["id"] in existing_pay_ids or qp["amount"] <= 0:
                continue
            if not dry_run:
                d = _parse_date(qp["txn_date"])
                db.add(
                    Payment(
                        facture_id=facture_id,
                        amount=qp["amount"],
                        method="bank_transfer",
                        paid_at=(d.date() if d else now.date()),
                        qbo_payment_id=qp["id"],
                        reference="QB",
                    )
                )
                await db.flush()
            existing_pay_ids.add(qp["id"])
            created += 1
        return created

    for inv in invoices:
        iid = str(inv.get("Id") or "")
        if not iid:
            continue
        cref = str((inv.get("CustomerRef") or {}).get("value") or "")
        cname = (inv.get("CustomerRef") or {}).get("name") or ""
        # Hors périmètre du client demandé → on ignore silencieusement.
        if client_refs is not None and cref not in client_refs:
            continue
        total = _num(inv.get("TotalAmt"))
        balance = _num(inv.get("Balance"))
        doc = str(inv.get("DocNumber") or "")

        existing = existing_by_qid.get(iid)
        if existing is not None:
            # Déjà dans Kratos : on REFLÈTE chaque paiement QB (virement)
            # en ligne de paiement Kratos, puis on solde si balance 0.
            mirrored = await _mirror_payments(existing.id, iid)
            stats["payments_mirrored"] += mirrored
            newly_paid = balance == 0 and existing.status != "paid"
            if newly_paid and not dry_run:
                existing.status = "paid"
                existing.balance = 0
                existing.paid_at = existing.paid_at or now
                await db.flush()
            if newly_paid:
                stats["paid_synced"] += 1
            if mirrored or newly_paid:
                pv_status = "paiement_synchro"
            else:
                stats["skipped_existing"] += 1
                pv_status = "deja_importee"
            preview.append(
                {"type": "facture", "qbo_id": iid, "doc_number": doc,
                 "customer": cname, "total": total, "balance": balance,
                 "status": pv_status}
            )
            continue

        proj = proj_by_job.get(cref)
        if proj is None:
            # RÈGLE : pas de projet rattaché → on n'importe pas.
            stats["skipped_no_project"] += 1
            preview.append(
                {"type": "facture", "qbo_id": iid, "doc_number": doc,
                 "customer": cname, "total": total, "balance": balance,
                 "status": "sans_projet"}
            )
            continue

        status = "paid" if balance == 0 else "sent"
        preview.append(
            {"type": "facture", "qbo_id": iid, "doc_number": doc,
             "customer": cname, "total": total, "balance": balance,
             "project_id": proj.id, "status": "a_importer"}
        )
        if not dry_run:
            new_fac = Facture(
                reference=f"QB-{iid}"[:32],
                client_id=proj.client_id,
                project_id=proj.id,
                total=total,
                balance=balance,
                status=status,
                issued_at=_parse_date(inv.get("TxnDate")),
                due_at=_parse_date(inv.get("DueDate")),
                qbo_invoice_id=iid,
                qbo_doc_number=doc or None,
                qbo_sync_token=str(inv.get("SyncToken") or "") or None,
            )
            db.add(new_fac)
            await db.flush()
            # Reflète chaque paiement QB de cette nouvelle facture.
            stats["payments_mirrored"] += await _mirror_payments(
                new_fac.id, iid
            )
        stats["imported"] += 1

    if dry_run:
        # Scopé à un client : on montre TOUT (y compris déjà importé /
        # sans projet) pour que l'utilisateur voie l'ensemble. Sinon, on
        # se limite aux lignes à importer pour borner la taille.
        stats["preview"] = (
            preview[:300]
            if client_id is not None
            else [p for p in preview if p["status"] == "a_importer"][:200]
        )
    return stats
