"""Sync an Achat (PO) to QuickBooks Online as a Bill OR a Purchase.

Le PO interne (PO-0027) reste maître côté h2.0. Le routage côté QBO
dépend du mode de paiement :

- operations / interac / cheque  → Bill (facture fournisseur)
  (apparaît dans Comptes Fournisseurs jusqu'au paiement)
- cc_steven / cc_michael / cash  → Purchase (achat déjà payé)
  (charge la dépense + crédite le compte de paiement directement)

Le mapping nom_de_compte ← mode_de_paiement vient de la table
qbo_account_maps configurée dans /app/parametres. Le service
résout le nom → Account.Id via une query QBO au moment du push.

Le numéro PO interne est mis dans DocNumber + PrivateNote du
Bill/Purchase pour la traçabilité comptable.
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
from app.models.qbo_account_map import QboAccountMap


# Modes considérés comme « payés cash » → Purchase QB
PAID_METHODS = {"cc_steven", "cc_michael", "cash", "interac"}


log = logging.getLogger(__name__)


class AchatSyncError(Exception):
    pass


async def _load_achat(db: AsyncSession, achat_id: int) -> Optional[Achat]:
    return (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()


def _build_line(
    achat: Achat, expense_account_id: str, project_name: Optional[str]
) -> Dict[str, Any]:
    amount = float(achat.amount or 0)
    description = achat.description or f"Achat {achat.reference}"
    if project_name:
        description = f"{description} — {project_name}"
    return {
        "DetailType": "AccountBasedExpenseLineDetail",
        "Amount": round(amount, 2),
        "Description": description[:4000],
        "AccountBasedExpenseLineDetail": {
            "AccountRef": {"value": str(expense_account_id)},
        },
    }


def _build_bill_payload(
    *,
    achat: Achat,
    vendor_id: str,
    expense_account_id: str,
    project_name: Optional[str],
    existing_bill_id: Optional[str] = None,
    existing_sync_token: Optional[str] = None,
) -> Dict[str, Any]:
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
        "Line": [_build_line(achat, expense_account_id, project_name)],
    }
    if existing_bill_id and existing_sync_token is not None:
        payload["Id"] = existing_bill_id
        payload["SyncToken"] = existing_sync_token
        payload["sparse"] = True
    return payload


def _build_purchase_payload(
    *,
    achat: Achat,
    vendor_id: str,
    expense_account_id: str,
    payment_account_id: str,
    payment_type: str,  # "Cash" | "Check" | "CreditCard"
    project_name: Optional[str],
    existing_purchase_id: Optional[str] = None,
    existing_sync_token: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "AccountRef": {"value": str(payment_account_id)},
        "PaymentType": payment_type,
        "EntityRef": {"value": str(vendor_id), "type": "Vendor"},
        "TxnDate": (
            achat.ordered_at.date().isoformat()
            if achat.ordered_at
            else date.today().isoformat()
        ),
        "DocNumber": achat.reference[:21],
        "PrivateNote": (
            f"Source: Horizon h2.0 PO {achat.reference}"
            + (f" — projet {project_name}" if project_name else "")
        ),
        "Line": [_build_line(achat, expense_account_id, project_name)],
    }
    if existing_purchase_id and existing_sync_token is not None:
        payload["Id"] = existing_purchase_id
        payload["SyncToken"] = existing_sync_token
        payload["sparse"] = True
    return payload


def _payment_type_for(method: Optional[str]) -> str:
    """QBO Purchase.PaymentType : Cash / Check / CreditCard."""
    if method in ("cc_steven", "cc_michael"):
        return "CreditCard"
    if method in ("interac",):
        # Interac est techniquement un débit immédiat, on le marque
        # « Cash » qui regroupe debit/cash dans QB.
        return "Cash"
    return "Cash"


async def _resolve_payment_account(
    db, qbo, method: Optional[str]
) -> Optional[str]:
    """Retourne l'Account.Id QBO correspondant au mode de paiement,
    via le mapping configuré dans qbo_account_maps. Renvoie None si
    pas de mapping (l'appelant lèvera une erreur user-friendly)."""
    if not method:
        return None
    map_row = (
        await db.execute(
            select(QboAccountMap).where(QboAccountMap.id == 1)
        )
    ).scalar_one_or_none()
    if map_row is None:
        return None
    name = None
    if method == "cc_steven":
        name = map_row.cc_steven_account
    elif method == "cc_michael":
        name = map_row.cc_michael_account
    elif method == "cash":
        name = map_row.cash_account
    elif method == "interac":
        name = map_row.interac_account
    elif method == "operations":
        name = map_row.operations_account
    if not name:
        return None
    acc = await qbo.find_account_by_name(name)
    return str(acc.get("Id")) if acc else None


async def _resolve_expense_account(db, qbo) -> Optional[str]:
    """Compte de dépense par défaut (configuré dans /app/parametres,
    ou premier compte d'expense disponible)."""
    map_row = (
        await db.execute(
            select(QboAccountMap).where(QboAccountMap.id == 1)
        )
    ).scalar_one_or_none()
    if map_row and map_row.default_expense_account:
        acc = await qbo.find_account_by_name(map_row.default_expense_account)
        if acc:
            return str(acc.get("Id"))
    fallback = await qbo.first_expense_account()
    return str(fallback.get("Id")) if fallback else None


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

        expense_account_id = await _resolve_expense_account(db, qbo)
        if not expense_account_id:
            raise AchatSyncError(
                "Aucun compte de dépense disponible côté QBO. "
                "Configure un compte par défaut dans /app/parametres "
                "→ Comptes QuickBooks ou crée au moins un compte "
                "type 'Cost of Goods Sold' / 'Expense' dans QB."
            )

        method = (achat.payment_method or "operations").lower()
        as_purchase = method in PAID_METHODS

        if as_purchase:
            # Achat déjà payé (carte de crédit, comptant, interac) →
            # Purchase QB qui crédite le compte de paiement
            # directement.
            payment_account_id = await _resolve_payment_account(
                db, qbo, method
            )
            if not payment_account_id:
                raise AchatSyncError(
                    f"Le mode de paiement « {method} » n'a pas de "
                    f"compte QBO configuré. Va dans /app/parametres "
                    f"→ Comptes QuickBooks et entre le nom exact du "
                    f"compte (ex. « Carte Visa Steven »)."
                )
            payload = _build_purchase_payload(
                achat=achat,
                vendor_id=vendor_id,
                expense_account_id=expense_account_id,
                payment_account_id=payment_account_id,
                payment_type=_payment_type_for(method),
                project_name=project.name if project else None,
                existing_purchase_id=achat.qbo_bill_id,
                existing_sync_token=achat.qbo_sync_token,
            )
            if payload.get("Id"):
                qbo_obj = await qbo.update_purchase(payload)
            else:
                qbo_obj = await qbo.create_purchase(payload)
        else:
            # Sur compte fournisseur (chèque / net-30) → Bill
            payload = _build_bill_payload(
                achat=achat,
                vendor_id=vendor_id,
                expense_account_id=expense_account_id,
                project_name=project.name if project else None,
                existing_bill_id=achat.qbo_bill_id,
                existing_sync_token=achat.qbo_sync_token,
            )
            if payload.get("Id"):
                qbo_obj = await qbo.update_bill(payload)
            else:
                qbo_obj = await qbo.create_bill(payload)
    except QuickBooksError as exc:
        raise AchatSyncError(str(exc)) from exc

    qbo_id = str(qbo_obj.get("Id") or "")
    sync_token = str(qbo_obj.get("SyncToken") or "")
    doc_number = str(qbo_obj.get("DocNumber") or "")
    # On stocke dans qbo_bill_id, qu'il s'agisse d'un Bill ou d'un
    # Purchase — c'est le « id externe QB » de ce mouvement.
    achat.qbo_bill_id = qbo_id or None
    achat.qbo_sync_token = sync_token or None
    achat.qbo_doc_number = doc_number or None
    await db.flush()

    kind = "Purchase" if as_purchase else "Bill"
    log.info(
        "Pushed Achat %s to QBO %s %s (DocNumber=%s)",
        achat.id, kind, qbo_id, doc_number,
    )
    return {
        "ok": True,
        "qbo_bill_id": qbo_id,
        "qbo_doc_number": doc_number,
        "qbo_vendor_id": vendor_id,
    }
