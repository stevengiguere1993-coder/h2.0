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


async def pull_invoices_from_qbo(
    db: AsyncSession, *, since_days: int = 180, dry_run: bool = False
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

    # Factures déjà reliées (dédoublonnage par ID QBO).
    existing_ids = {
        r[0]
        for r in (
            await db.execute(
                select(Facture.qbo_invoice_id).where(
                    Facture.qbo_invoice_id.is_not(None)
                )
            )
        ).all()
    }
    # Projet par Job QBO (clé de rattachement).
    proj_by_job: dict[str, Project] = {
        str(p.qbo_job_id): p
        for p in (
            await db.execute(
                select(Project).where(Project.qbo_job_id.is_not(None))
            )
        ).scalars().all()
    }

    stats = {
        "dry_run": dry_run,
        "total_qbo": len(invoices),
        "imported": 0,
        "skipped_existing": 0,
        "skipped_no_project": 0,
    }
    to_import: list[dict] = []

    for inv in invoices:
        iid = str(inv.get("Id") or "")
        if not iid:
            continue
        if iid in existing_ids:
            stats["skipped_existing"] += 1
            continue
        cref = (inv.get("CustomerRef") or {}).get("value")
        proj = proj_by_job.get(str(cref)) if cref else None
        if proj is None:
            # RÈGLE : pas de projet rattaché → on n'importe pas.
            stats["skipped_no_project"] += 1
            continue

        total = _num(inv.get("TotalAmt"))
        balance = _num(inv.get("Balance"))
        doc = str(inv.get("DocNumber") or "")
        status = "paid" if balance == 0 else "sent"
        to_import.append(
            {
                "qbo_invoice_id": iid,
                "doc_number": doc,
                "project_id": proj.id,
                "client_id": proj.client_id,
                "total": total,
                "balance": balance,
                "status": status,
            }
        )
        if not dry_run:
            db.add(
                Facture(
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
            )
            await db.flush()
            existing_ids.add(iid)
        stats["imported"] += 1

    if dry_run:
        stats["preview"] = to_import[:200]
    return stats
