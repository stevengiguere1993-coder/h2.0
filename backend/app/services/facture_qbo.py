"""Sync a Facture to QuickBooks Online as an Invoice.

Parallel to soumission_qbo (Estimate) — creates or updates a QBO
Invoice with SalesItemLineDetail lines referencing real Items
(find-or-created per line description).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.client import Client
from app.models.facture import Facture
from app.models.facture_item import FactureItem

log = logging.getLogger(__name__)


class FactureSyncError(Exception):
    pass


async def _load_facture(db: AsyncSession, facture_id: int) -> Optional[Facture]:
    return (
        await db.execute(select(Facture).where(Facture.id == facture_id))
    ).scalar_one_or_none()


async def _load_items(db: AsyncSession, facture_id: int) -> list[FactureItem]:
    rows = await db.execute(
        select(FactureItem)
        .where(FactureItem.facture_id == facture_id)
        .order_by(FactureItem.position.asc(), FactureItem.id.asc())
    )
    return list(rows.scalars().all())


async def _load_client(
    db: AsyncSession, client_id: Optional[int]
) -> Optional[Client]:
    if not client_id:
        return None
    return (
        await db.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()


async def _build_lines(
    qbo, items: list[FactureItem], fallback_name: str
) -> list[Dict[str, Any]]:
    lines: list[Dict[str, Any]] = []
    for it in items:
        amount = round(float(it.quantity) * float(it.unit_price), 2)
        qty = float(it.quantity)
        unit_price = float(it.unit_price)
        name = (it.description or "").strip()[:100] or fallback_name
        qbo_item = await qbo.ensure_item(name, description=it.description)
        item_id = str(qbo_item.get("Id") or "")
        sales_detail: Dict[str, Any] = {
            "Qty": qty,
            "UnitPrice": unit_price,
        }
        if item_id:
            sales_detail["ItemRef"] = {"value": item_id}
        # Taxe de vente automatisée (AST) : chaque ligne porte le code de
        # taxe ; QBO calcule la TPS/TVQ. Sans ça, la compagnie rejette la
        # facture (« toutes vos opérations comprennent un taux de TPS/TVH »).
        # On retombe sur le code d'achat si le code de vente n'est pas
        # défini (souvent le même code TPS/TVQ QC sert aux deux).
        _tax_code = (
            settings.qbo_sales_tax_code or settings.qbo_purchase_tax_code
        )
        if _tax_code:
            sales_detail["TaxCodeRef"] = {"value": str(_tax_code)}
        lines.append(
            {
                "DetailType": "SalesItemLineDetail",
                "Amount": amount,
                "Description": it.description,
                "SalesItemLineDetail": sales_detail,
            }
        )
    return lines


def _build_invoice_payload(
    *,
    facture: Facture,
    customer_id: str,
    lines: list[Dict[str, Any]],
    existing_sync_token: Optional[str] = None,
    existing_invoice_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not lines:
        # Facture sans items : ligne de repli avec le MONTANT réel
        # (sous-total HT) ET le code de taxe — sinon la taxe automatisée
        # (AST) refuse (« toutes vos opérations comprennent un taux de
        # TPS/TVH », erreur 6000) et le total serait à 0.
        try:
            _amt = float(
                facture.subtotal
                if facture.subtotal is not None
                else (facture.total or 0)
            )
        except (TypeError, ValueError):
            _amt = 0.0
        _detail: Dict[str, Any] = {"Qty": 1, "UnitPrice": _amt}
        _tax_code = (
            settings.qbo_sales_tax_code or settings.qbo_purchase_tax_code
        )
        if _tax_code:
            _detail["TaxCodeRef"] = {"value": str(_tax_code)}
        lines = [
            {
                "DetailType": "SalesItemLineDetail",
                "Amount": _amt,
                "Description": facture.reference,
                "SalesItemLineDetail": _detail,
            }
        ]

    payload: Dict[str, Any] = {
        "CustomerRef": {"value": str(customer_id)},
        "DocNumber": facture.reference[:21],
        "TxnDate": date.today().isoformat(),
        "Line": lines,
    }
    if facture.due_at:
        payload["DueDate"] = facture.due_at.date().isoformat()

    # Taxes canadiennes — recalculées à partir des montants de ligne
    # pour rester cohérent avec ce que h2.0 affiche, indépendamment de
    # ce qui est stocké dans facture.tps/tvq (souvent null car calculé
    # au PDF). TPS 5 % + TVQ 9.975 %. GlobalTaxCalculation=TaxExcluded
    # dit à QBO que les lignes n'incluent pas la taxe.
    if settings.qbo_sales_tax_code or settings.qbo_purchase_tax_code:
        # Taxe AUTOMATISÉE (AST) : les lignes portent déjà le TaxCodeRef,
        # QBO calcule la taxe. On NE fournit PAS de TxnTaxDetail manuel
        # (la compagnie AST le refuse).
        payload["GlobalTaxCalculation"] = "TaxExcluded"
    else:
        # Taxe MANUELLE (compagnies sans AST) : on fournit le total.
        subtotal = 0.0
        for line in lines:
            try:
                subtotal += float(line.get("Amount") or 0)
            except (TypeError, ValueError):
                continue
        tps = round(subtotal * 0.05, 2)
        tvq = round(subtotal * 0.09975, 2)
        total_tax = round(tps + tvq, 2)
        if total_tax > 0:
            payload["GlobalTaxCalculation"] = "TaxExcluded"
            payload["TxnTaxDetail"] = {"TotalTax": total_tax}

    if existing_invoice_id and existing_sync_token is not None:
        payload["Id"] = existing_invoice_id
        payload["SyncToken"] = existing_sync_token
        payload["sparse"] = True

    return payload


async def ensure_invoice_payment(
    qbo,
    db: AsyncSession,
    facture: Facture,
    customer_ref: str,
    invoice_obj: Dict[str, Any],
) -> Optional[str]:
    """Crée le Payment QBO qui solde la facture si elle est PAYÉE dans
    Kratos et pas déjà payée côté QBO. Idempotent via qbo_payment_id.
    Best-effort : un échec ne casse pas la synchro de la facture."""
    if facture.status != "paid":
        return None
    if getattr(facture, "qbo_payment_id", None):
        return facture.qbo_payment_id
    inv_id = str(invoice_obj.get("Id") or "")
    if not inv_id:
        return None
    try:
        amount = float(invoice_obj.get("TotalAmt") or facture.total or 0)
    except (TypeError, ValueError):
        amount = float(facture.total or 0)
    if amount <= 0:
        return None
    payload = {
        "TotalAmt": amount,
        "CustomerRef": {"value": str(customer_ref)},
        "Line": [
            {
                "Amount": amount,
                "LinkedTxn": [{"TxnId": inv_id, "TxnType": "Invoice"}],
            }
        ],
    }
    try:
        res = await qbo.create_payment(payload)
        pay = res.get("Payment") or res
        pid = str(pay.get("Id") or "") or None
        facture.qbo_payment_id = pid
        await db.flush()
        return pid
    except Exception as exc:  # noqa: BLE001
        log.warning("create payment facture %s: %s", facture.id, exc)
        return None


async def sync_facture_payments_to_qbo(
    qbo,
    db: AsyncSession,
    facture: Facture,
    customer_ref: str,
    inv_id: str,
) -> list[str]:
    """Pousse CHAQUE virement (ligne de paiement Kratos) de la facture
    comme un Payment QBO DISTINCT — pour qu'il corresponde à une opération
    bancaire appariable dans QB. Idempotent par `Payment.qbo_payment_id`.

    Repli : si la facture est payée mais sans ligne de paiement détaillée
    (ancien flux « marquée payée »), on solde en un seul Payment.
    Retourne la liste des IDs de Payment QBO créés."""
    inv_id = str(inv_id or "")
    if not inv_id:
        return []
    from app.models.payment import Payment

    # CustomerRef du paiement = celui de la FACTURE QB elle-même (pas le
    # qbo_job_id Kratos, qui peut pointer vers un sous-client erroné après
    # un reset/doublon). Un paiement doit être sous le même client que la
    # facture pour pouvoir s'y imputer. Repli sur customer_ref si échec.
    pay_customer_ref = str(customer_ref)
    try:
        inv_fetch = await qbo.get_invoice(inv_id)
        inv_obj = inv_fetch.get("Invoice") or inv_fetch
        cref = (inv_obj.get("CustomerRef") or {}).get("value")
        if cref:
            pay_customer_ref = str(cref)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "get_invoice %s pour CustomerRef paiement: %s", inv_id, exc
        )

    rows = (
        await db.execute(
            select(Payment)
            .where(Payment.facture_id == facture.id)
            .order_by(Payment.paid_at.asc(), Payment.id.asc())
        )
    ).scalars().all()

    if not rows:
        # Pas de virements détaillés → repli legacy (1 paiement global).
        pid = await ensure_invoice_payment(
            qbo, db, facture, pay_customer_ref, {"Id": inv_id}
        )
        return [pid] if pid else []

    pushed: list[str] = []
    for p in rows:
        if p.qbo_payment_id:
            continue
        try:
            amount = float(p.amount or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0:
            continue
        payload: Dict[str, Any] = {
            "TotalAmt": amount,
            "CustomerRef": {"value": pay_customer_ref},
            "Line": [
                {
                    "Amount": amount,
                    "LinkedTxn": [
                        {"TxnId": inv_id, "TxnType": "Invoice"}
                    ],
                }
            ],
        }
        if p.paid_at:
            payload["TxnDate"] = str(p.paid_at)[:10]
        if p.reference:
            payload["PaymentRefNum"] = str(p.reference)[:21]
        try:
            res = await qbo.create_payment(payload)
            pay = res.get("Payment") or res
            qid = str(pay.get("Id") or "") or None
            if qid:
                p.qbo_payment_id = qid
                # Garde le 1er id aussi au niveau facture (rétrocompat).
                if not getattr(facture, "qbo_payment_id", None):
                    facture.qbo_payment_id = qid
                await db.flush()
                pushed.append(qid)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "create payment (virement) facture %s ligne %s: %s",
                facture.id, p.id, exc,
            )
    return pushed


async def sync_facture_to_qbo(
    db: AsyncSession, facture_id: int
) -> Dict[str, Any]:
    qbo = get_qbo()
    # Charge les tokens persistés avant de vérifier ready — sinon après
    # un redeploy l'in-memory client ne sait pas qu'on a OAuth-connecté.
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        raise FactureSyncError(
            "QuickBooks n'est pas configuré (client id / secret / refresh token / realm)."
        )

    fa = await _load_facture(db, facture_id)
    if fa is None:
        raise FactureSyncError(f"Facture {facture_id} introuvable")

    items = await _load_items(db, facture_id)
    client = await _load_client(db, fa.client_id)
    if client is None:
        raise FactureSyncError(
            "La facture doit être liée à un client avant d'être envoyée dans QBO."
        )

    try:
        customer = await qbo.ensure_customer(
            display_name=client.name,
            email=client.email,
            phone=client.phone,
            billing_address=client.address,
        )
        customer_id = str(customer.get("Id") or "")
        if not customer_id:
            raise FactureSyncError("QBO customer creation did not return an Id.")

        lines = await _build_lines(
            qbo, items, fallback_name=fa.reference
        )
        payload = _build_invoice_payload(
            facture=fa,
            customer_id=customer_id,
            lines=lines,
            existing_invoice_id=fa.qbo_invoice_id,
            existing_sync_token=fa.qbo_sync_token,
        )

        if payload.get("Id"):
            invoice = await qbo.create_invoice(payload)  # same endpoint updates w/ Id+SyncToken
        else:
            invoice = await qbo.create_invoice(payload)

    except QuickBooksError as exc:
        raise FactureSyncError(str(exc)) from exc

    inv = invoice.get("Invoice") or invoice
    fa.qbo_invoice_id = str(inv.get("Id") or "") or None
    fa.qbo_sync_token = str(inv.get("SyncToken") or "") or None
    fa.qbo_doc_number = str(inv.get("DocNumber") or "") or None
    await db.flush()
    # Chaque virement Kratos → un Payment QBO distinct (appariable à une
    # opération bancaire). Repli sur 1 paiement global si pas de virement.
    await sync_facture_payments_to_qbo(
        qbo, db, fa, customer_id, str(inv.get("Id") or "")
    )
    await db.refresh(fa)

    return {
        "qbo_invoice_id": fa.qbo_invoice_id or "",
        "qbo_doc_number": fa.qbo_doc_number or "",
    }
