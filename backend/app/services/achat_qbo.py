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

from app.core.config import settings
from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.achat import Achat
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.models.qbo_account_map import QboAccountMap


# Modes considérés comme paiement immédiat → Purchase QB.
# (Tout sauf bill_to_pay, qui devient un Bill A/P.)
PAID_METHODS = {
    "cheque_horizon",
    "cc_steven",
    "cc_michael",
    "cc_olivier",
    "cc_christian",
}


log = logging.getLogger(__name__)


class AchatSyncError(Exception):
    pass


def _is_stale_ref(exc: Exception) -> bool:
    """Vrai si l'erreur QBO indique que l'objet référencé (par son Id)
    a été supprimé/inactivé côté QuickBooks — auquel cas on doit recréer
    plutôt que mettre à jour. Couvre « Object Not Found » et « made
    inactive » (errorCode 610 / 3200)."""
    msg = str(exc).lower()
    return (
        "made inactive" in msg
        or "object not found" in msg
        or "introuvable" in msg
        or "inactive" in msg
        or "errorcode=610" in msg
        or "code': '610'" in msg
    )


async def _load_achat(db: AsyncSession, achat_id: int) -> Optional[Achat]:
    return (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()


def _build_line(
    achat: Achat,
    expense_account_id: str,
    project_name: Optional[str],
    customer_id: Optional[str] = None,
) -> Dict[str, Any]:
    # Montant HT de la ligne. Avec un TaxCodeRef + TaxExcluded, QBO
    # calcule la taxe par-dessus, donc on doit envoyer le HT.
    #   - Achat « normal » : amount = HT déjà (amount_taxes porte la taxe).
    #   - Achat « legacy » : amount = TTC et amount_taxes = 0/None →
    #     on décompose le TTC pour retrouver le HT (TPS 5 % + TVQ 9,975 %
    #     = facteur 1,14975), sinon QBO ajouterait la taxe sur un TTC
    #     (double taxation → total gonflé).
    raw_amount = float(achat.amount or 0)
    taxes = float(achat.amount_taxes or 0)
    if settings.qbo_purchase_tax_code and taxes <= 0 and raw_amount > 0:
        amount = round(raw_amount / 1.14975, 2)
    else:
        amount = raw_amount
    description = (
        achat.description
        or f"Achat #{achat.id}"
    )
    if project_name:
        description = f"{description} — {project_name}"
    detail: Dict[str, Any] = {
        "AccountRef": {"value": str(expense_account_id)},
    }
    # Si le projet est rattaché à un Client QB, l'achat devient
    # « Billable » (refacturable au client) avec CustomerRef pointant
    # sur ce client. C'est le mécanisme QB pour repasser une dépense
    # dans la prochaine facture.
    # CustomerRef = le PROJET QBO (sous-client). On rattache la dépense
    # au projet pour le suivi des coûts. BillableStatus dépend de
    # `is_billable` : « Billable » seulement si on veut la repasser au
    # client dans une facture, sinon « NotBillable » (coût de projet
    # simple, non refacturé).
    if customer_id:
        detail["CustomerRef"] = {"value": str(customer_id)}
        detail["BillableStatus"] = (
            "Billable" if achat.is_billable else "NotBillable"
        )
    # Code de taxe sur la ligne — exigé par la taxe de vente automatisée
    # QBO (« Tous les articles ont besoin d'un taux de taxe »). On
    # applique le code configuré (TPS/TVQ QC) à chaque ligne d'achat.
    if settings.qbo_purchase_tax_code:
        detail["TaxCodeRef"] = {"value": str(settings.qbo_purchase_tax_code)}
    return {
        "DetailType": "AccountBasedExpenseLineDetail",
        "Amount": round(amount, 2),
        "Description": description[:4000],
        "AccountBasedExpenseLineDetail": detail,
    }


def _doc_number(achat: Achat, po_reference: Optional[str]) -> str:
    """DocNumber = numéro de PO si l'achat est lié à un PO, sinon
    # facture fournisseur, sinon « A-{id} » en dernier recours.

    Quand un PO existe, on l'utilise comme identifiant canonique côté
    QB pour que le comptable retrouve facilement le lien interne.
    Le # de facture fournisseur reste dans PrivateNote pour le
    rapprochement avec la facture papier."""
    if po_reference:
        return po_reference[:21]
    if achat.supplier_invoice_number:
        return achat.supplier_invoice_number[:21]
    return f"A-{achat.id}"[:21]


def _txn_date(achat: Achat) -> str:
    if achat.invoice_date:
        return achat.invoice_date.isoformat()
    if achat.received_at:
        return achat.received_at.date().isoformat()
    return date.today().isoformat()


def _private_note(
    achat: Achat, po_reference: Optional[str], project_name: Optional[str]
) -> str:
    parts = [f"Source: Horizon h2.0 Achat #{achat.id}"]
    if po_reference:
        parts.append(f"PO source: {po_reference}")
    if achat.supplier_invoice_number:
        parts.append(f"Facture fournisseur: {achat.supplier_invoice_number}")
    if project_name:
        parts.append(f"Projet: {project_name}")
    return " | ".join(parts)


def _add_quebec_taxes(payload: Dict[str, Any], lines: list) -> None:
    """Quand l'achat est rattaché à un projet (donc refacturable),
    on ajoute TPS 5 % + TVQ 9.975 % calculés sur la somme des lignes,
    avec GlobalTaxCalculation=TaxExcluded (les Amount des lignes ne
    contiennent pas la taxe). Permet à QB d'avoir le montant total
    avec taxes pour le rapprochement comptable."""
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


def _build_bill_payload(
    *,
    achat: Achat,
    vendor_id: str,
    expense_account_id: str,
    po_reference: Optional[str],
    project_name: Optional[str],
    customer_id: Optional[str] = None,
    existing_bill_id: Optional[str] = None,
    existing_sync_token: Optional[str] = None,
) -> Dict[str, Any]:
    lines = [
        _build_line(
            achat, expense_account_id, project_name, customer_id=customer_id
        )
    ]
    payload: Dict[str, Any] = {
        "VendorRef": {"value": str(vendor_id)},
        "TxnDate": _txn_date(achat),
        "DocNumber": _doc_number(achat, po_reference),
        "PrivateNote": _private_note(achat, po_reference, project_name),
        "Line": lines,
    }
    if customer_id:
        _add_quebec_taxes(payload, lines)
    elif settings.qbo_purchase_tax_code:
        # Sans client (achat non refacturable) : le montant de ligne est
        # le HT, et QBO calcule la taxe par-dessus via le TaxCodeRef.
        # TaxExcluded évite que QBO traite le HT comme un TTC (sinon la
        # taxe est ajoutée en double → total gonflé).
        payload["GlobalTaxCalculation"] = "TaxExcluded"
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
    po_reference: Optional[str],
    project_name: Optional[str],
    customer_id: Optional[str] = None,
    existing_purchase_id: Optional[str] = None,
    existing_sync_token: Optional[str] = None,
) -> Dict[str, Any]:
    lines = [
        _build_line(
            achat, expense_account_id, project_name, customer_id=customer_id
        )
    ]
    payload: Dict[str, Any] = {
        "AccountRef": {"value": str(payment_account_id)},
        "PaymentType": payment_type,
        "EntityRef": {"value": str(vendor_id), "type": "Vendor"},
        "TxnDate": _txn_date(achat),
        "DocNumber": _doc_number(achat, po_reference),
        "PrivateNote": _private_note(achat, po_reference, project_name),
        "Line": lines,
    }
    if customer_id:
        _add_quebec_taxes(payload, lines)
    elif settings.qbo_purchase_tax_code:
        # Sans client (achat non refacturable) : montant de ligne = HT,
        # QBO calcule la taxe via le TaxCodeRef. TaxExcluded évite la
        # double taxation (sinon le HT serait traité comme un TTC).
        payload["GlobalTaxCalculation"] = "TaxExcluded"
    if existing_purchase_id and existing_sync_token is not None:
        payload["Id"] = existing_purchase_id
        payload["SyncToken"] = existing_sync_token
        payload["sparse"] = True
    return payload


def _payment_type_for(method: Optional[str]) -> str:
    """QBO Purchase.PaymentType : Cash / Check / CreditCard."""
    if method and method.startswith("cc_"):
        return "CreditCard"
    if method == "cheque_horizon":
        return "Check"
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
    elif method == "cc_olivier":
        name = map_row.cc_olivier_account
    elif method == "cc_christian":
        name = map_row.cc_christian_account
    elif method == "cheque_horizon":
        name = map_row.cheque_horizon_account
    if not name:
        return None
    acc = await qbo.find_account_by_name(name)
    return str(acc.get("Id")) if acc else None


async def _resolve_expense_account(
    db, qbo, fournisseur: Optional[Fournisseur] = None
) -> Optional[str]:
    """Compte de dépense à utiliser pour la ligne d'achat.

    Priorité :
    1. fournisseur.qbo_expense_account (auto-classification par
       fournisseur — ex. Rona → Matériaux)
    2. QboAccountMap.default_expense_account (fallback global)
    3. Premier compte d'expense disponible côté QB (dernier recours)
    """
    if fournisseur and fournisseur.qbo_expense_account:
        acc = await qbo.find_account_by_name(fournisseur.qbo_expense_account)
        if acc:
            return str(acc.get("Id"))
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
    customer_id: Optional[str] = None
    if achat.project_id:
        project = (
            await db.execute(
                select(Project).where(Project.id == achat.project_id)
            )
        ).scalar_one_or_none()
        # On rattache la dépense au PROJET QBO (sous-client/Job du client),
        # pour le suivi des coûts par chantier — même si elle n'est PAS
        # refacturable. Le projet QBO est créé s'il n'existe pas.
        if project and project.client_id:
            from app.models.client import Client

            client = (
                await db.execute(
                    select(Client).where(Client.id == project.client_id)
                )
            ).scalar_one_or_none()
            if client:
                try:
                    # 1) Client parent QBO (créé/réutilisé).
                    parent = await qbo.ensure_customer(
                        display_name=client.name,
                        email=client.email,
                        phone=client.phone,
                        billing_address=client.address,
                    )
                    parent_id = str(parent.get("Id") or "")
                    # 2) Projet QBO = sous-client (Job) sous ce parent.
                    if parent_id and project.name:
                        proj = await qbo.ensure_project(
                            parent_customer_id=parent_id,
                            project_name=project.name,
                        )
                        customer_id = str(proj.get("Id") or "") or None
                except QuickBooksError as exc:
                    # Le rattachement projet ne doit pas bloquer la
                    # création de la dépense : on logge et on continue
                    # sans CustomerRef.
                    log.warning(
                        "QBO: rattachement projet échoué (achat %s): %s",
                        achat.id,
                        exc,
                    )
                    customer_id = None
    # PO source (optionnel) — sa référence sert de DocNumber fallback
    # quand le # de facture fournisseur n'est pas fourni.
    po_reference: Optional[str] = None
    if achat.purchase_order_id:
        from app.models.purchase_order import PurchaseOrder

        po = (
            await db.execute(
                select(PurchaseOrder).where(
                    PurchaseOrder.id == achat.purchase_order_id
                )
            )
        ).scalar_one_or_none()
        if po:
            po_reference = po.reference

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

        expense_account_id = await _resolve_expense_account(
            db, qbo, fournisseur=fournisseur
        )
        if not expense_account_id:
            raise AchatSyncError(
                "Aucun compte de dépense disponible côté QBO. "
                "Configure un compte par défaut dans /app/parametres "
                "→ Comptes QuickBooks ou crée au moins un compte "
                "type 'Cost of Goods Sold' / 'Expense' dans QB."
            )

        method = (achat.payment_method or "bill_to_pay").lower()
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
                po_reference=po_reference,
                project_name=project.name if project else None,
                customer_id=customer_id,
                existing_purchase_id=achat.qbo_bill_id,
                existing_sync_token=achat.qbo_sync_token,
            )
            if payload.get("Id"):
                try:
                    qbo_obj = await qbo.update_purchase(payload)
                except QuickBooksError as exc:
                    if not _is_stale_ref(exc):
                        raise
                    # L'objet QBO référencé a été supprimé/inactivé côté
                    # QuickBooks : on recrée un nouveau Purchase.
                    log.warning(
                        "QBO purchase %s introuvable → recréation (achat %s)",
                        payload.get("Id"),
                        achat.id,
                    )
                    payload.pop("Id", None)
                    payload.pop("SyncToken", None)
                    payload.pop("sparse", None)
                    qbo_obj = await qbo.create_purchase(payload)
            else:
                qbo_obj = await qbo.create_purchase(payload)
        else:
            # Sur compte fournisseur (chèque / net-30) → Bill
            payload = _build_bill_payload(
                achat=achat,
                vendor_id=vendor_id,
                expense_account_id=expense_account_id,
                po_reference=po_reference,
                project_name=project.name if project else None,
                customer_id=customer_id,
                existing_bill_id=achat.qbo_bill_id,
                existing_sync_token=achat.qbo_sync_token,
            )
            if payload.get("Id"):
                try:
                    qbo_obj = await qbo.update_bill(payload)
                except QuickBooksError as exc:
                    if not _is_stale_ref(exc):
                        raise
                    log.warning(
                        "QBO bill %s introuvable → recréation (achat %s)",
                        payload.get("Id"),
                        achat.id,
                    )
                    payload.pop("Id", None)
                    payload.pop("SyncToken", None)
                    payload.pop("sparse", None)
                    qbo_obj = await qbo.create_bill(payload)
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

    # Joindre la facture fournisseur (image / PDF) si l'employé en a
    # uploadé une. On le fait après création du Bill/Purchase ; en cas
    # d'échec on log mais on ne bloque pas le push principal.
    # NB: receipt_image est une colonne `deferred` — non chargée par
    # défaut. Il faut explicitement rafraîchir pour la lire.
    receipt_attached = False
    receipt_error: Optional[str] = None
    if qbo_id and achat.receipt_image_content_type:
        try:
            await db.refresh(achat, attribute_names=["receipt_image"])
        except Exception as exc:  # noqa: BLE001
            receipt_error = f"refresh: {exc}"
            log.warning("Refresh receipt_image failed: %s", exc)
    if qbo_id and achat.receipt_image:
        try:
            ctype = (
                achat.receipt_image_content_type
                or "application/octet-stream"
            )
            ext = "pdf" if "pdf" in ctype else "jpg"
            if "png" in ctype:
                ext = "png"
            file_name = f"facture-A{achat.id}.{ext}"
            await qbo.upload_attachment(
                entity_type=kind,
                entity_id=qbo_id,
                file_name=file_name,
                content_type=ctype,
                content=bytes(achat.receipt_image),
            )
            receipt_attached = True
            log.info(
                "Attached receipt to QBO %s %s (file=%s)",
                kind, qbo_id, file_name,
            )
        except Exception as exc:  # noqa: BLE001
            receipt_error = str(exc)[:200]
            log.warning(
                "Receipt upload failed for Achat %s -> QBO %s %s: %s",
                achat.id, kind, qbo_id, exc,
            )

    return {
        "ok": True,
        "qbo_bill_id": qbo_id,
        "qbo_doc_number": doc_number,
        "qbo_vendor_id": vendor_id,
        "receipt_attached": receipt_attached,
        "receipt_error": receipt_error,
    }
