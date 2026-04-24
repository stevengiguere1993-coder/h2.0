"""
Sync a Soumission to QuickBooks Online as an Estimate.

Flow:
1. Resolve contact info from the linked ContactRequest (name / email /
   phone / address).
2. Ensure a QBO Customer exists (find-by-email -> find-by-name -> create).
3. Collect all SoumissionItem rows.
4. Create (or update, if already synced) an Estimate referencing that
   customer with one QBO Line per item.
5. Persist the QBO identifiers (`qbo_estimate_id`, `qbo_doc_number`,
   `qbo_sync_token`) on the Soumission via the Facture-style columns we
   add on the model in this commit.

This module is a pure service; the HTTP endpoint just calls
`sync_soumission_to_qbo`.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.contact_request import ContactRequest
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem

log = logging.getLogger(__name__)


class SoumissionSyncError(Exception):
    pass


async def _load_soumission(
    db: AsyncSession, soumission_id: int
) -> Optional[Soumission]:
    return (
        await db.execute(select(Soumission).where(Soumission.id == soumission_id))
    ).scalar_one_or_none()


async def _load_items(
    db: AsyncSession, soumission_id: int
) -> list[SoumissionItem]:
    rows = await db.execute(
        select(SoumissionItem)
        .where(SoumissionItem.soumission_id == soumission_id)
        .order_by(SoumissionItem.position.asc(), SoumissionItem.id.asc())
    )
    return list(rows.scalars().all())


async def _load_contact(
    db: AsyncSession, contact_request_id: Optional[int]
) -> Optional[ContactRequest]:
    if not contact_request_id:
        return None
    return (
        await db.execute(
            select(ContactRequest).where(ContactRequest.id == contact_request_id)
        )
    ).scalar_one_or_none()


async def _build_lines(qbo, items: list[SoumissionItem], fallback_name: str) -> list[Dict[str, Any]]:
    """Build QBO Estimate lines, ensuring each one references a real QBO Item.

    Each Soumission line item description is used as the QBO Item name
    (find-or-create, Service type). This way every line in the Estimate
    is tied to a proper entry in the Products & Services catalog.
    """
    lines: list[Dict[str, Any]] = []
    for it in items:
        amount = round(float(it.quantity) * float(it.unit_price), 2)
        qty = float(it.quantity)
        unit_price = float(it.unit_price)
        # QBO Item.Name is limited to 100 chars and must be unique per realm.
        name = (it.description or "").strip()[:100] or fallback_name
        qbo_item = await qbo.ensure_item(name, description=it.description)
        item_id = str(qbo_item.get("Id") or "")
        sales_detail: Dict[str, Any] = {
            "Qty": qty,
            "UnitPrice": unit_price,
        }
        if item_id:
            sales_detail["ItemRef"] = {"value": item_id}
        lines.append(
            {
                "DetailType": "SalesItemLineDetail",
                "Amount": amount,
                "Description": it.description,
                "SalesItemLineDetail": sales_detail,
            }
        )
    return lines


def _build_estimate_payload(
    *,
    soumission: Soumission,
    customer_id: str,
    lines: list[Dict[str, Any]],
    existing_sync_token: Optional[str] = None,
    existing_estimate_id: Optional[str] = None,
) -> Dict[str, Any]:
    # If we have no items, QBO requires at least one line -- send a
    # placeholder so the estimate can still be created as a draft.
    if not lines:
        lines = [
            {
                "DetailType": "SalesItemLineDetail",
                "Amount": 0,
                "Description": soumission.title or soumission.reference,
                "SalesItemLineDetail": {"Qty": 1, "UnitPrice": 0},
            }
        ]

    payload: Dict[str, Any] = {
        "CustomerRef": {"value": str(customer_id)},
        "DocNumber": soumission.reference[:21],  # QBO caps at 21 chars
        "TxnDate": date.today().isoformat(),
        "PrivateNote": soumission.notes or None,
        "CustomerMemo": {"value": soumission.title or ""},
        "Line": lines,
    }
    if soumission.valid_until:
        payload["ExpirationDate"] = soumission.valid_until.date().isoformat()

    if existing_estimate_id and existing_sync_token is not None:
        payload["Id"] = existing_estimate_id
        payload["SyncToken"] = existing_sync_token
        payload["sparse"] = True

    return payload


async def sync_soumission_to_qbo(
    db: AsyncSession, soumission_id: int
) -> Dict[str, Any]:
    """Push a soumission to QBO as an Estimate. Returns a small summary dict.

    Raises SoumissionSyncError if QBO is not configured or the push fails.
    """
    qbo = get_qbo()
    # Charge d'abord les tokens persistés (OAuth callback /qbo/callback).
    # Sinon qbo.ready retourne False juste après un redeploy même si la
    # compagnie est connectée en DB — l'env peut être vide.
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        raise SoumissionSyncError(
            "QuickBooks not configured (missing client id / secret / refresh token / realm)."
        )

    s = await _load_soumission(db, soumission_id)
    if s is None:
        raise SoumissionSyncError(f"Soumission {soumission_id} not found")

    items = await _load_items(db, soumission_id)
    contact = await _load_contact(db, s.contact_request_id)

    display_name = (contact.name if contact else None) or s.title or s.reference
    email = contact.email if contact else None
    phone = contact.phone if contact else None
    address = contact.address if contact else None

    try:
        customer = await qbo.ensure_customer(
            display_name=display_name,
            email=email,
            phone=phone,
            billing_address=address,
        )
        customer_id = str(customer.get("Id") or "")
        if not customer_id:
            raise SoumissionSyncError("QBO customer creation did not return an Id.")

        lines = await _build_lines(
            qbo, items, fallback_name=(s.title or s.reference)
        )
        payload = _build_estimate_payload(
            soumission=s,
            customer_id=customer_id,
            lines=lines,
            existing_estimate_id=s.qbo_estimate_id if hasattr(s, "qbo_estimate_id") else None,
            existing_sync_token=s.qbo_sync_token if hasattr(s, "qbo_sync_token") else None,
        )

        if payload.get("Id"):
            estimate = await qbo.update_estimate(payload)
        else:
            estimate = await qbo.create_estimate(payload)

    except QuickBooksError as exc:
        raise SoumissionSyncError(str(exc)) from exc

    # Persist the returned QBO identifiers so subsequent syncs update in place
    estimate_id = str(estimate.get("Id") or "")
    sync_token = str(estimate.get("SyncToken") or "")
    doc_number = str(estimate.get("DocNumber") or "")

    if hasattr(s, "qbo_estimate_id"):
        s.qbo_estimate_id = estimate_id or None
    if hasattr(s, "qbo_sync_token"):
        s.qbo_sync_token = sync_token or None
    if hasattr(s, "qbo_doc_number"):
        s.qbo_doc_number = doc_number or None
    await db.flush()

    log.info(
        "Pushed Soumission %s to QBO as Estimate %s (DocNumber=%s)",
        s.id, estimate_id, doc_number,
    )
    return {
        "ok": True,
        "qbo_estimate_id": estimate_id,
        "qbo_doc_number": doc_number,
        "qbo_customer_id": customer_id,
    }
