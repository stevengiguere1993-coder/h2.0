"""Sync an Achat (PO) to QuickBooks Online as a Bill.

Le PO interne (PO-0027) reste maître côté h2.0. Côté QBO on crée
une Bill (= facture fournisseur) qui charge le coût matériel sur le
projet et apparaît dans les comptes fournisseurs à payer. Le numéro
PO interne est mis dans le PrivateNote / DocNumber du Bill pour la
traçabilité avec le comptable.

Flow:
1. Charger l'achat + son fournisseur + son projet.
2. Ensure_vendor (crée le fournisseur QBO s'il n'existe pas).
3. Lookup d'un compte de dépense (Expense / Cost of Goods Sold).
4. Create / update Bill avec une seule ligne AccountBasedExpenseLineDetail
   du montant de l'achat.
5. Persister Bill.Id + SyncToken sur l'Achat pour permettre les
   sparse updates ultérieurs.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.achat import Achat
from app.models.fournisseur import Fournisseur
from app.models.project import Project


log = logging.getLogger(__name__)


class AchatSyncError(Exception):
    pass


async def _load_achat(db: AsyncSession, achat_id: int) -> Optional[Achat]:
    return (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()


def _build_bill_payload(
    *,
    achat: Achat,
    vendor_id: str,
    expense_account_id: str,
    project_name: Optional[str],
    existing_bill_id: Optional[str] = None,
    existing_sync_token: Optional[str] = None,
) -> Dict[str, Any]:
    amount = float(achat.amount or 0)
    description = achat.description or f"Achat {achat.reference}"
    if project_name:
        description = f"{description} — {project_name}"

    line: Dict[str, Any] = {
        "DetailType": "AccountBasedExpenseLineDetail",
        "Amount": round(amount, 2),
        "Description": description[:4000],
        "AccountBasedExpenseLineDetail": {
            "AccountRef": {"value": str(expense_account_id)},
        },
    }

    payload: Dict[str, Any] = {
        "VendorRef": {"value": str(vendor_id)},
        "TxnDate": (
            achat.ordered_at.date().isoformat()
            if achat.ordered_at
            else date.today().isoformat()
        ),
        # DocNumber sur le Bill = notre numéro PO. Comme ça le
        # comptable retrouve « PO-0027 » directement dans QB.
        "DocNumber": achat.reference[:21],
        "PrivateNote": (
            f"Source: Horizon h2.0 PO {achat.reference}"
            + (f" — projet {project_name}" if project_name else "")
        ),
        "Line": [line],
    }

    if existing_bill_id and existing_sync_token is not None:
        payload["Id"] = existing_bill_id
        payload["SyncToken"] = existing_sync_token
        payload["sparse"] = True

    return payload


async def sync_achat_to_qbo(
    db: AsyncSession, achat_id: int
) -> Dict[str, Any]:
    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        raise AchatSyncError(
            "QuickBooks n'est pas configuré (client id / secret / "
            "refresh token / realm)."
        )

    achat = await _load_achat(db, achat_id)
    if achat is None:
        raise AchatSyncError(f"Achat {achat_id} introuvable")
    if not achat.amount or float(achat.amount) <= 0:
        raise AchatSyncError(
            "L'achat doit avoir un montant > 0 pour être poussé."
        )

    fournisseur: Optional[Fournisseur] = None
    if achat.fournisseur_id:
        fournisseur = (
            await db.execute(
                select(Fournisseur).where(Fournisseur.id == achat.fournisseur_id)
            )
        ).scalar_one_or_none()
    project: Optional[Project] = None
    if achat.project_id:
        project = (
            await db.execute(
                select(Project).where(Project.id == achat.project_id)
            )
        ).scalar_one_or_none()

    if fournisseur is None or not (fournisseur.name or "").strip():
        raise AchatSyncError(
            "Cet achat n'a pas de fournisseur — impossible de créer "
            "le Bill QuickBooks."
        )

    try:
        vendor = await qbo.ensure_vendor(
            display_name=fournisseur.name,
            email=fournisseur.email,
            phone=fournisseur.phone,
        )
        vendor_id = str(vendor.get("Id") or "")
        if not vendor_id:
            raise AchatSyncError("QBO n'a pas retourné d'id vendor.")

        expense = await qbo.first_expense_account()
        if expense is None:
            raise AchatSyncError(
                "Aucun compte de dépense disponible côté QBO. "
                "Crée au moins un compte type 'Cost of Goods Sold' "
                "ou 'Expense' dans QB."
            )
        expense_account_id = str(expense.get("Id") or "")

        payload = _build_bill_payload(
            achat=achat,
            vendor_id=vendor_id,
            expense_account_id=expense_account_id,
            project_name=project.name if project else None,
            existing_bill_id=achat.qbo_bill_id,
            existing_sync_token=achat.qbo_sync_token,
        )

        if payload.get("Id"):
            bill = await qbo.update_bill(payload)
        else:
            bill = await qbo.create_bill(payload)
    except QuickBooksError as exc:
        raise AchatSyncError(str(exc)) from exc

    bill_id = str(bill.get("Id") or "")
    sync_token = str(bill.get("SyncToken") or "")
    doc_number = str(bill.get("DocNumber") or "")
    achat.qbo_bill_id = bill_id or None
    achat.qbo_sync_token = sync_token or None
    achat.qbo_doc_number = doc_number or None
    await db.flush()

    log.info(
        "Pushed Achat %s to QBO Bill %s (DocNumber=%s)",
        achat.id, bill_id, doc_number,
    )
    return {
        "ok": True,
        "qbo_bill_id": bill_id,
        "qbo_doc_number": doc_number,
        "qbo_vendor_id": vendor_id,
    }
