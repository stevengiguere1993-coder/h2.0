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
    class_id: Optional[str] = None,
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

    # Classe = chantier (projet). On la pose sur CHAQUE ligne (comme les
    # coûts) pour que le suivi par classe / l'onglet Projets QB attribue le
    # revenu au bon projet, quel que soit le réglage « une classe par
    # opération / par ligne » de la compagnie.
    if class_id:
        for line in lines:
            detail = line.get("SalesItemLineDetail")
            if isinstance(detail, dict):
                detail["ClassRef"] = {"value": str(class_id)}

    payload: Dict[str, Any] = {
        "CustomerRef": {"value": str(customer_id)},
        "DocNumber": facture.reference[:21],
        "TxnDate": date.today().isoformat(),
        "Line": lines,
    }
    if class_id:
        # Repli : aussi au niveau transaction si la compagnie est en mode
        # « une classe pour toute l'opération ».
        payload["ClassRef"] = {"value": str(class_id)}
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


# Mode de paiement Kratos (côté facture client) → nom du PaymentMethod QB
# (libellés FR de QuickBooks). Le Payment QB portera le MÊME mode que celui
# choisi dans Kratos.
_QBO_PAYMENT_METHOD_NAME = {
    "cash": "Espèces",
    "credit_card": "Carte de crédit",
    "debit_card": "Carte de débit",
    "check": "Chèque",
    "bank_transfer": "Virement",
}


async def _resolve_deposit_account_id(qbo, db: AsyncSession) -> Optional[str]:
    """Compte « Déposer sur » des paiements client = TOUJOURS le compte
    chèque Horizon (configuré dans qbo_account_maps)."""
    from app.models.qbo_account_map import QboAccountMap

    row = (
        await db.execute(select(QboAccountMap).where(QboAccountMap.id == 1))
    ).scalar_one_or_none()
    name = (getattr(row, "cheque_horizon_account", None) or "").strip()
    if not name:
        return None
    try:
        acc = await qbo.find_account_by_name(name)
        return str(acc.get("Id")) if acc and acc.get("Id") else None
    except Exception:  # noqa: BLE001
        return None


async def _resolve_payment_method_id(qbo, method: Optional[str]) -> Optional[str]:
    name = _QBO_PAYMENT_METHOD_NAME.get((method or "").strip().lower())
    if not name:
        return None
    try:
        pm = await qbo.ensure_payment_method(name=name)
        return str(pm.get("Id")) if pm and pm.get("Id") else None
    except Exception:  # noqa: BLE001
        return None


async def _create_payment_resilient(
    qbo, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Crée le Payment QBO en tolérant le rejet d'un champ OPTIONNEL.

    L'application d'un paiement à une facture ne requiert que CustomerRef +
    TotalAmt + Line[].LinkedTxn. Les décorations — compte de dépôt
    (DepositToAccountRef), mode de paiement (PaymentMethodRef), n° de
    référence (PaymentRefNum) — sont des causes FRÉQUENTES de rejet de
    validation QBO (« Invalid Reference Id », compte de dépôt d'un type non
    valide, etc.). Quand le payload complet est rejeté, on réessaie avec le
    payload MINIMAL pour que le paiement solde quand même la facture (elle
    passe de « En retard » à « Payée » côté QB). C'est le même pattern de
    repli que côté achats (_strip_txn_tax_detail). On ne lève que si même le
    payload minimal échoue — l'appelant journalise alors le motif QBO."""
    try:
        return await qbo.create_payment(payload)
    except QuickBooksError as exc:
        minimal: Dict[str, Any] = {
            "TotalAmt": payload.get("TotalAmt"),
            "CustomerRef": payload.get("CustomerRef"),
            "Line": payload.get("Line"),
        }
        if payload.get("TxnDate"):
            minimal["TxnDate"] = payload["TxnDate"]
        # Rien à retirer (déjà minimal) → inutile de refaire le même appel.
        if set(minimal) >= set(payload):
            raise
        log.warning(
            "Payment QBO rejeté avec le payload complet (%s) → nouvel essai "
            "sans compte de dépôt / mode de paiement / n° de référence",
            exc,
        )
        return await qbo.create_payment(minimal)


async def ensure_invoice_payment(
    qbo,
    db: AsyncSession,
    facture: Facture,
    customer_ref: str,
    invoice_obj: Dict[str, Any],
    deposit_account_id: Optional[str] = None,
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
    # Déposer TOUJOURS sur le compte chèque Horizon.
    if deposit_account_id:
        payload["DepositToAccountRef"] = {"value": str(deposit_account_id)}
    try:
        res = await _create_payment_resilient(qbo, payload)
        pay = res.get("Payment") or res
        pid = str(pay.get("Id") or "") or None
        facture.qbo_payment_id = pid
        await db.flush()
        return pid
    except Exception as exc:  # noqa: BLE001
        # ERROR (pas warning) : un paiement Kratos qui n'atteint pas QB est
        # exactement l'échec silencieux à rendre visible (motif QBO inclus).
        log.error(
            "Paiement QB facture %s NON enregistré : %s", facture.id, exc
        )
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

    # « Déposer sur » = toujours le compte chèque Horizon (résolu 1×).
    deposit_account_id = await _resolve_deposit_account_id(qbo, db)

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
            qbo, db, facture, pay_customer_ref, {"Id": inv_id},
            deposit_account_id=deposit_account_id,
        )
        return [pid] if pid else []

    # Cache des PaymentMethod QB par mode Kratos (évite les requêtes répétées).
    pm_cache: dict[str, Optional[str]] = {}

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
        # Mode de paiement QB = celui choisi dans Kratos.
        mkey = (p.method or "").strip().lower()
        if mkey not in pm_cache:
            pm_cache[mkey] = await _resolve_payment_method_id(qbo, mkey)
        if pm_cache[mkey]:
            payload["PaymentMethodRef"] = {"value": pm_cache[mkey]}
        # Déposer toujours sur le compte chèque Horizon.
        if deposit_account_id:
            payload["DepositToAccountRef"] = {"value": str(deposit_account_id)}
        try:
            res = await _create_payment_resilient(qbo, payload)
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
            # ERROR : virement Kratos non répliqué dans QB → à voir dans les
            # logs (le motif QBO exact est inclus via QuickBooksError).
            log.error(
                "Paiement (virement) QB facture %s ligne %s NON "
                "enregistré : %s",
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

    # On NE pousse PAS une facture en BROUILLON vers QBO : seules les
    # factures ENVOYÉES (sent / paid / overdue) deviennent des Invoice QB.
    # Le brouillon n'est pas un document émis — il partira quand on
    # cliquera « Envoyer au client ».
    if (fa.status or "") in ("draft", "void"):
        return {
            "skipped": True,
            "reason": "facture_draft_ou_annulee",
            "status": fa.status,
        }

    items = await _load_items(db, facture_id)
    client = await _load_client(db, fa.client_id)
    if client is None:
        raise FactureSyncError(
            "La facture doit être liée à un client avant d'être envoyée dans QBO."
        )

    # Modèle QB : la facture est rattachée au PROJET (sous-client converti
    # en projet QB, ex. « 30 Boul. Quévillon — Projet de Gabrielle Lauzon »).
    # CustomerRef = qbo_job_id du projet → le revenu apparaît dans l'onglet
    # Projets et roule sous le client parent. À défaut de projet relié, on
    # facture le client parent. On porte aussi la CLASSE = chantier.
    project = None
    if fa.project_id:
        from app.models.project import Project

        project = (
            await db.execute(
                select(Project).where(Project.id == fa.project_id)
            )
        ).scalar_one_or_none()

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

        # CustomerRef = PROJET (sous-client) si relié, sinon client parent.
        # On RÉSOUT le bon id même si le sous-client a été converti en projet
        # QB (ancien qbo_job_id supprimé → « client supprimé »).
        # ClassRef = chantier (adresse / nom du projet).
        invoice_customer_id = customer_id
        class_id: Optional[str] = None
        if project is not None:
            from app.services.qbo_project_resolve import (
                resolve_project_customer_id,
            )

            invoice_customer_id = await resolve_project_customer_id(
                qbo, db, project, customer_id
            )
            class_name = (
                (getattr(project, "address", None) or "").strip()
                or (project.name or "").strip()
            )
            if class_name:
                try:
                    klass = await qbo.ensure_class(name=class_name)
                    class_id = (
                        str(klass.get("Id"))
                        if klass and klass.get("Id")
                        else None
                    )
                except QuickBooksError as exc:
                    log.warning(
                        "QBO ensure_class facture %s: %s", fa.id, exc
                    )

        # Si la facture Kratos n'est pas encore liée à une Invoice QB mais
        # qu'une Invoice du MÊME numéro (DocNumber) existe déjà dans QB
        # (cas migration), on s'y RATTACHE pour la METTRE À JOUR et pour que
        # le PAIEMENT s'y enregistre — au lieu de créer une facture en double.
        if not fa.qbo_invoice_id and (fa.reference or "").strip():
            try:
                inv0 = await qbo.find_invoice_by_docnumber(fa.reference)
            except QuickBooksError as exc:
                log.warning(
                    "QBO lookup Invoice DocNumber=%s (facture %s): %s",
                    fa.reference, fa.id, exc,
                )
                inv0 = None
            if inv0:
                fa.qbo_invoice_id = str(inv0.get("Id") or "") or None
                fa.qbo_sync_token = str(inv0.get("SyncToken") or "") or None
                await db.flush()

        lines = await _build_lines(
            qbo, items, fallback_name=fa.reference
        )
        payload = _build_invoice_payload(
            facture=fa,
            customer_id=invoice_customer_id,
            lines=lines,
            class_id=class_id,
            existing_invoice_id=fa.qbo_invoice_id,
            existing_sync_token=fa.qbo_sync_token,
        )

        # Création/MAJ robuste : si QB refuse un DOUBLON de DocNumber, on se
        # RELIE à la facture existante (même numéro) et on la MET À JOUR pour
        # la corriger (projet/classe) — au lieu d'en créer une 2e. Si l'Id
        # stocké est obsolète/supprimé, on repart sans Id (puis le doublon
        # éventuel sera relié).
        _DUP_KEYS = (
            "duplicate document number",
            "numéro de document en double",
            "numero de document en double",
            "6140",
        )
        _STALE_KEYS = (
            "not found", "object not found", "introuvable", "deleted",
            "stale", "invalid reference", "5010", "610", "2010",
        )

        async def _push_invoice(p: Dict[str, Any]) -> Dict[str, Any]:
            try:
                return await qbo.create_invoice(p)
            except QuickBooksError as exc:
                m = str(exc).lower()
                # Doublon de numéro → relier à la facture existante + MAJ.
                if not p.get("Id") and any(k in m for k in _DUP_KEYS):
                    docnum = str(p.get("DocNumber") or "").strip()
                    found = (
                        await qbo.find_invoice_by_docnumber(docnum)
                        if docnum
                        else None
                    )
                    if found and found.get("Id"):
                        p["Id"] = str(found["Id"])
                        p["SyncToken"] = str(found.get("SyncToken") or "0")
                        p["sparse"] = True
                        return await qbo.create_invoice(p)
                # Id obsolète/supprimé → recréer à neuf.
                if p.get("Id") and any(k in m for k in _STALE_KEYS):
                    p.pop("Id", None)
                    p.pop("SyncToken", None)
                    p.pop("sparse", None)
                    return await _push_invoice(p)
                raise

        invoice = await _push_invoice(payload)

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


async def push_facture_payments_only(
    db: AsyncSession, facture_id: int
) -> Dict[str, Any]:
    """Enregistre les PAIEMENTS d'une facture sur l'Invoice QB SANS toucher
    au corps de la facture.

    Conçu pour le flux « j'enregistre un paiement » : on ne re-pousse PAS
    l'Invoice (modifier une facture migrée — lignes, client — est risqué et
    peut échouer côté QB, ce qui empêchait alors le paiement de partir). On
    se contente de :
      1. retrouver l'Invoice QB (qbo_invoice_id, sinon par DocNumber = n° de
         facture — les numéros correspondent entre Kratos et QB) ;
      2. créer les Payment manquants liés à cette Invoice (idempotent via
         Payment.qbo_payment_id).
    Si l'Invoice n'existe pas encore dans QB, on retombe sur la synchro
    complète (qui la crée puis pousse les paiements).
    """
    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        raise FactureSyncError("QuickBooks n'est pas configuré.")
    fa = await _load_facture(db, facture_id)
    if fa is None:
        raise FactureSyncError(f"Facture {facture_id} introuvable")
    if (fa.status or "") in ("draft", "void"):
        return {"skipped": True, "reason": "facture_draft_ou_annulee"}

    inv_id = (fa.qbo_invoice_id or "").strip()
    if not inv_id and (fa.reference or "").strip():
        try:
            inv0 = await qbo.find_invoice_by_docnumber(fa.reference)
        except QuickBooksError as exc:
            log.warning(
                "push_payments lookup Invoice DocNumber=%s (facture %s): %s",
                fa.reference, fa.id, exc,
            )
            inv0 = None
        if inv0:
            inv_id = str(inv0.get("Id") or "")
            fa.qbo_invoice_id = inv_id or None
            fa.qbo_sync_token = str(inv0.get("SyncToken") or "") or None
            await db.flush()

    if not inv_id:
        # Facture pas encore dans QB → synchro complète (crée + paiements).
        return await sync_facture_to_qbo(db, facture_id)

    # CustomerRef de repli pour les Payment ; sync_facture_payments_to_qbo
    # relit de toute façon le vrai CustomerRef de l'Invoice.
    customer_ref = ""
    client = await _load_client(db, fa.client_id)
    if client is not None:
        try:
            cust = await qbo.ensure_customer(
                display_name=client.name,
                email=client.email,
                phone=client.phone,
                billing_address=client.address,
            )
            customer_ref = str(cust.get("Id") or "")
        except QuickBooksError:
            customer_ref = ""

    pushed = await sync_facture_payments_to_qbo(
        qbo, db, fa, customer_ref, inv_id
    )
    await db.flush()
    return {"qbo_invoice_id": inv_id, "payments_pushed": len(pushed)}
