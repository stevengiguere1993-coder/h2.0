"""Import QB → Kratos des coûts d'un projet (Bills + Purchases).

RÈGLE : on n'importe un coût QuickBooks (facture fournisseur « Bill » à
payer, ou dépense « Purchase » cash/chèque/CC) QUE s'il est rattaché à un
PROJET — c.-à-d. qu'une de ses lignes a un `CustomerRef` pointant vers le
sous-client (Job) d'un projet Kratos (`Project.qbo_job_id`). Sinon il est
ignoré. Idempotent : dédup par `qbo_bill_id` / `qbo_purchase_id`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.achat import Achat
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.models.soumission import Soumission

log = logging.getLogger(__name__)


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _project_for_txn(
    txn: dict, proj_by_job: dict[str, Project]
) -> Optional[Project]:
    for line in txn.get("Line") or []:
        for key in (
            "AccountBasedExpenseLineDetail",
            "ItemBasedExpenseLineDetail",
        ):
            d = line.get(key) or {}
            cref = (d.get("CustomerRef") or {}).get("value")
            if cref and str(cref) in proj_by_job:
                return proj_by_job[str(cref)]
    return None


def _txn_customer_refs(txn: dict) -> set[str]:
    """Tous les CustomerRef présents sur les lignes (pour savoir si une
    dépense touche un client donné)."""
    out: set[str] = set()
    for line in txn.get("Line") or []:
        for key in (
            "AccountBasedExpenseLineDetail",
            "ItemBasedExpenseLineDetail",
        ):
            d = line.get(key) or {}
            cref = (d.get("CustomerRef") or {}).get("value")
            if cref:
                out.add(str(cref))
    return out


async def pull_project_costs_from_qbo(
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
        bills = await qbo.query(
            f"SELECT * FROM Bill WHERE TxnDate >= '{cutoff}' "
            "ORDER BY TxnDate DESC MAXRESULTS 1000"
        )
        purchases = await qbo.query(
            f"SELECT * FROM Purchase WHERE TxnDate >= '{cutoff}' "
            "ORDER BY TxnDate DESC MAXRESULTS 1000"
        )
    except QuickBooksError as exc:
        return {"error": f"Requête QB échouée : {exc}"}

    # Mode de paiement réel des Bills payés (chèque / carte) déduit des
    # BillPayments QB → on ne laisse jamais un Bill payé en « Sur compte ».
    try:
        from app.services.qbo_payment_classify import (
            build_paid_bill_method_index,
        )

        paid_bill_methods = await build_paid_bill_method_index(qbo, db)
    except Exception:  # noqa: BLE001
        paid_bill_methods = {}

    # Achats déjà liés par qbo_bill_id (objet complet → on peut refléter
    # le PAIEMENT QB → Kratos sur un Bill déjà importé).
    existing_bill: dict[str, Achat] = {
        str(a.qbo_bill_id): a
        for a in (
            await db.execute(
                select(Achat).where(Achat.qbo_bill_id.is_not(None))
            )
        ).scalars().all()
    }
    existing_purchase = {
        r[0]
        for r in (
            await db.execute(
                select(Achat.qbo_purchase_id).where(
                    Achat.qbo_purchase_id.is_not(None)
                )
            )
        ).all()
    }
    pstmt = select(Project).where(Project.qbo_job_id.is_not(None))
    if client_id is not None:
        pstmt = pstmt.where(Project.client_id == client_id)
    proj_by_job: dict[str, Project] = {
        str(p.qbo_job_id): p
        for p in (await db.execute(pstmt)).scalars().all()
    }
    # Refs QB du client (parent + sous-clients) : ne garder que ses
    # dépenses dans l'aperçu détaillé scopé.
    client_refs: Optional[set[str]] = None
    if client_id is not None:
        from app.models.client import Client

        client = (
            await db.execute(select(Client).where(Client.id == client_id))
        ).scalar_one_or_none()
        client_refs = set(proj_by_job.keys())
        if client and client.qbo_customer_id:
            client_refs.add(str(client.qbo_customer_id))
    fourn_by_name: dict[str, int] = {
        (n or "").strip().lower(): i
        for i, n in (
            await db.execute(select(Fournisseur.id, Fournisseur.name))
        ).all()
    }
    # Type de facturation par soumission → défaut « refacturable » des coûts
    # importés. Un CONTRAT (kind=contract, prix coûtant majoré) ou un devis
    # ESTIMÉ → refacturable. Forfaitaire ou inconnu → non refacturable.
    # (Vaut seulement à l'import QB → Kratos.)
    soum_ids = {
        p.soumission_id
        for p in proj_by_job.values()
        if p.soumission_id
    }
    billing_by_soum: dict[int, str] = {}
    if soum_ids:
        for sid, kind, pk in (
            await db.execute(
                select(
                    Soumission.id,
                    Soumission.kind,
                    Soumission.pricing_kind,
                ).where(Soumission.id.in_(soum_ids))
            )
        ).all():
            # Aligné sur _billing_kind (endpoints/projects.py) : contrat
            # l'emporte, sinon le pricing_kind.
            billing_by_soum[sid] = (
                "contrat" if kind == "contract" else (pk or "forfaitaire")
            )

    def _is_billable(proj: Project) -> bool:
        bk = (
            billing_by_soum.get(proj.soumission_id)
            if proj.soumission_id
            else None
        )
        # Refacturable pour un CONTRAT (coût majoré) ou un ESTIMÉ. Forfaitaire
        # OU type inconnu (pas de soumission liée) → NON refacturable : sur un
        # prix fixe, les dépenses ne se refacturent pas au client.
        return bk not in (None, "forfaitaire")

    now = datetime.now(timezone.utc)
    stats = {
        "dry_run": dry_run,
        "scope": "client" if client_id is not None else "all",
        "total_qbo": len(bills) + len(purchases),
        "bills_imported": 0,
        "purchases_imported": 0,
        "skipped_existing": 0,
        "skipped_no_project": 0,
        "paid_synced": 0,
    }
    preview: list[dict] = []

    # ── Bills (factures fournisseurs à payer) ──
    for b in bills:
        bid = str(b.get("Id") or "")
        if not bid:
            continue
        # Scope client : ne garder que les dépenses qui touchent une de
        # ses refs QB (parent / sous-clients).
        if client_refs is not None and _txn_customer_refs(b).isdisjoint(
            client_refs
        ):
            continue
        total = _num(b.get("TotalAmt"))
        balance = _num(b.get("Balance"))
        paid = balance == 0
        vendor = (b.get("VendorRef") or {}).get("name")
        doc = str(b.get("DocNumber") or "")
        if bid in existing_purchase and bid not in existing_bill:
            # Garde symétrique : déjà présent via `qbo_purchase_id`.
            stats["skipped_existing"] += 1
            preview.append(
                {"type": "bill", "qbo_id": bid, "amount": total,
                 "vendor": vendor, "status": "deja_importe"}
            )
            continue
        if bid in existing_bill:
            # Déjà importé → on reflète seulement un PAIEMENT QB
            # (Bill soldé, balance 0) sur un achat pas encore payé.
            ach = existing_bill[bid]
            if paid and ach.status != "paid":
                if not dry_run:
                    ach.status = "paid"
                    ach.paid_at = ach.paid_at or now
                    # Classe selon le paiement réel : un Bill payé ne reste
                    # pas « Sur compte ».
                    real_pm = paid_bill_methods.get(bid)
                    if real_pm and (ach.payment_method or "bill_to_pay") in (
                        "",
                        "bill_to_pay",
                    ):
                        ach.payment_method = real_pm
                    await db.flush()
                stats["paid_synced"] += 1
                pv_status = "paiement_synchro"
            else:
                stats["skipped_existing"] += 1
                pv_status = "deja_importe"
            preview.append(
                {"type": "bill", "qbo_id": bid, "amount": total,
                 "vendor": vendor, "status": pv_status}
            )
            continue
        proj = _project_for_txn(b, proj_by_job)
        if proj is None:
            stats["skipped_no_project"] += 1
            preview.append(
                {"type": "bill", "qbo_id": bid, "amount": total,
                 "vendor": vendor, "status": "sans_projet"}
            )
            continue
        preview.append(
            {"type": "bill", "qbo_id": bid, "project_id": proj.id,
             "amount": total, "paid": paid, "vendor": vendor,
             "status": "a_importer"}
        )
        if not dry_run:
            db.add(
                Achat(
                    fournisseur_id=fourn_by_name.get(
                        (vendor or "").strip().lower()
                    ),
                    project_id=proj.id,
                    is_billable=_is_billable(proj),
                    amount=total,
                    status="paid" if paid else "received",
                    # Bill payé → mode réel (chèque/carte) déduit de QB ;
                    # sinon « Sur compte » (à payer).
                    payment_method=(
                        paid_bill_methods.get(bid) or "bill_to_pay"
                        if paid
                        else "bill_to_pay"
                    ),
                    received_at=now,
                    paid_at=now if paid else None,
                    invoice_date=_parse_date(b.get("TxnDate")),
                    supplier_invoice_number=doc or None,
                    qbo_bill_id=bid,
                    qbo_doc_number=doc or None,
                )
            )
            await db.flush()
        stats["bills_imported"] += 1

    # ── Purchases (dépenses payées : cash / chèque / CC) ──
    for p in purchases:
        pid = str(p.get("Id") or "")
        if not pid:
            continue
        if client_refs is not None and _txn_customer_refs(p).isdisjoint(
            client_refs
        ):
            continue
        total = _num(p.get("TotalAmt"))
        vendor = (p.get("EntityRef") or {}).get("name")
        doc = str(p.get("DocNumber") or "")
        # Anti-doublon : un Achat poussé DEPUIS Kratos vers QB stocke
        # l'Id de la Purchase dans `qbo_bill_id` (cf. achat_qbo.py), PAS
        # dans `qbo_purchase_id`. On vérifie donc les DEUX champs, sinon
        # la dépense ré-importée crée un doublon de l'achat d'origine.
        if pid in existing_purchase or pid in existing_bill:
            stats["skipped_existing"] += 1
            preview.append(
                {"type": "purchase", "qbo_id": pid, "amount": total,
                 "vendor": vendor, "status": "deja_importe"}
            )
            continue
        proj = _project_for_txn(p, proj_by_job)
        if proj is None:
            stats["skipped_no_project"] += 1
            preview.append(
                {"type": "purchase", "qbo_id": pid, "amount": total,
                 "vendor": vendor, "status": "sans_projet"}
            )
            continue
        ptype = str(p.get("PaymentType") or "")
        pm = {
            "Cash": "comptant",
            "Check": "cheque",
            "CreditCard": "cc",
        }.get(ptype)
        preview.append(
            {"type": "purchase", "qbo_id": pid, "project_id": proj.id,
             "amount": total, "vendor": vendor, "status": "a_importer"}
        )
        if not dry_run:
            db.add(
                Achat(
                    fournisseur_id=fourn_by_name.get(
                        (vendor or "").strip().lower()
                    ),
                    project_id=proj.id,
                    is_billable=_is_billable(proj),
                    amount=total,
                    status="paid",
                    payment_method=pm,
                    received_at=now,
                    paid_at=now,
                    invoice_date=_parse_date(p.get("TxnDate")),
                    supplier_invoice_number=doc or None,
                    qbo_purchase_id=pid,
                    qbo_doc_number=doc or None,
                )
            )
            await db.flush()
        stats["purchases_imported"] += 1

    if not dry_run:
        # Correction « refacturable » : sur un projet à CONTRAT / ESTIMÉ, les
        # coûts liés à QB et PAS encore refacturés doivent être « à
        # refacturer » (et le rester jusqu'à la refacturation). Rattrape les
        # coûts importés avec l'ancien défaut erroné.
        from sqlalchemy import update as _upd

        billable_proj_ids = [
            p.id for p in proj_by_job.values() if _is_billable(p)
        ]
        if billable_proj_ids:
            await db.execute(
                _upd(Achat)
                .where(
                    Achat.project_id.in_(billable_proj_ids),
                    Achat.invoiced_at.is_(None),
                    Achat.is_billable.is_(False),
                    (
                        Achat.qbo_bill_id.is_not(None)
                        | Achat.qbo_purchase_id.is_not(None)
                    ),
                )
                .values(is_billable=True)
            )
            await db.flush()

        # Filet automatique : supprime tout doublon résiduel après import.
        from app.services.achat_dedupe import dedupe_achats

        stats["deduped"] = await dedupe_achats(db)

    if dry_run:
        # Scopé client : on montre TOUT (à importer / déjà importé / sans
        # projet). Global : seulement les lignes à importer (taille bornée).
        stats["preview"] = (
            preview[:300]
            if client_id is not None
            else [p for p in preview if p.get("status") == "a_importer"][:200]
        )
    return stats
