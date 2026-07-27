"""Facture MENSUELLE ouverte par client QuickBooks (2026-07-27).

Retour Phil : il voulait des « débits différés » QBO — l'API Intuit ne
permet PAS d'en créer (l'entité ChargeCredit est gérable uniquement dans
l'UI). Équivalent retenu : chaque clic de facturation (relocation, frais
de gestion, refacturation feuille de temps) AJOUTE UNE LIGNE à LA facture
du mois du client — créée au premier clic du mois, JAMAIS envoyée par
Kratos. Une fois par mois, Phil/sa comptable envoie cette facture depuis
QuickBooks : tout le mois y est déjà « greffé ».

Règles :
- Clé de la facture ouverte = (realm_id, client QBO, 1er du mois) — table
  ``qbo_monthly_invoices``. Le realm (compagnie QBO) est la vraie clé :
  chez Phil les scopes entreprise/immobilier pointent la même compagnie.
- Si la facture du mois est PAYÉE (Balance 0) ou ENVOYÉE (EmailSent) dans
  QBO, on n'y touche plus : on en démarre une NOUVELLE pour la suite du
  mois (la ligne en table est remplacée).
- Si elle a été supprimée dans QBO (404), on en recrée une.
- DocNumber calculé à la CRÉATION seulement (max numérique récent + 1,
  retry 6140) — même logique que les anciens flux.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.integrations.quickbooks import QuickBooksClient, QuickBooksError
from app.models.qbo_monthly_invoice import QboMonthlyInvoice

log = logging.getLogger("qbo.monthly_invoice")

#: Champs read-only/dérivés qu'on RETIRE de l'objet GET avant un full
#: update — QBO recalcule le reste (totaux, taxes, liens).
_STRIP_ON_UPDATE = (
    "TotalAmt", "HomeTotalAmt", "Balance", "HomeBalance", "TxnTaxDetail",
    "MetaData", "DeliveryInfo", "LinkedTxn", "EInvoiceStatus",
    "InvoiceLink", "RecurDataRef", "TaxExemptionRef",
)


async def _next_doc_number(qbo: QuickBooksClient) -> Optional[str]:
    """Prochain numéro de facture (compagnies QBO à « numéros
    personnalisés » : l'API laisse DocNumber vide sinon)."""
    try:
        rows = await qbo.query(
            "SELECT DocNumber FROM Invoice "
            "ORDERBY MetaData.CreateTime DESC MAXRESULTS 100"
        )
        nums = [
            int(str(r.get("DocNumber")))
            for r in rows
            if str(r.get("DocNumber") or "").isdigit()
        ]
        return str(max(nums) + 1) if nums else "1000"
    except QuickBooksError:
        return None


async def _create_monthly(
    qbo: QuickBooksClient,
    customer_id: str,
    lines: List[Dict[str, Any]],
    private_note: str,
) -> Dict[str, Any]:
    next_num = await _next_doc_number(qbo)
    base_payload: Dict[str, Any] = {
        "CustomerRef": {"value": str(customer_id)},
        "TxnDate": datetime.now(timezone.utc).date().isoformat(),
        "GlobalTaxCalculation": "TaxExcluded",
        "Line": lines,
        "PrivateNote": private_note,
    }
    tries = 0
    while True:
        body = dict(base_payload)
        if next_num:
            body["DocNumber"] = next_num
        try:
            inv = await qbo.create_invoice(body)
            break
        except QuickBooksError as exc:
            msg = str(exc)
            if (
                next_num
                and tries < 3
                and ("6140" in msg or "uplicate" in msg or "double" in msg)
            ):
                tries += 1
                next_num = str(int(next_num) + 1)
                continue
            raise
    return inv.get("Invoice") or inv


def _invoice_locked(invoice: Dict[str, Any]) -> bool:
    """La facture du mois ne doit plus bouger : payée (même en partie) ou
    déjà envoyée au client depuis QuickBooks."""
    try:
        total = float(invoice.get("TotalAmt") or 0.0)
        balance = float(invoice.get("Balance") or 0.0)
        if total > 0 and balance < total - 0.005:
            return True  # paiement (partiel ou complet) appliqué
    except (TypeError, ValueError):
        pass
    return str(invoice.get("EmailStatus") or "") == "EmailSent"


async def _append_lines(
    qbo: QuickBooksClient,
    invoice: Dict[str, Any],
    lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Full update : objet du GET + nouvelles lignes (les lignes
    existantes gardent leur Id → préservées telles quelles)."""
    body = {k: v for k, v in invoice.items() if k not in _STRIP_ON_UPDATE}
    body["Line"] = list(invoice.get("Line") or []) + lines
    body["sparse"] = False
    inv = await qbo.create_invoice(body)  # POST /invoice avec Id = update
    return inv.get("Invoice") or inv


async def add_lines_to_monthly_invoice(
    db,
    qbo: QuickBooksClient,
    *,
    scope: str,
    customer_id: str,
    lines: List[Dict[str, Any]],
    private_note: str,
) -> Dict[str, Any]:
    """Ajoute ``lines`` à LA facture du mois courant du client (créée au
    besoin, jamais envoyée). Renvoie ``{invoice_id, doc_number, created}``
    (``created`` = une nouvelle facture mensuelle a été démarrée).

    Lève ``QuickBooksError`` en cas de refus QBO — l'appelant traduit en
    HTTP 502 comme avant.
    """
    mois = datetime.now(timezone.utc).date().replace(day=1)
    realm = str(qbo.realm_id or "")
    row = (
        await db.execute(
            select(QboMonthlyInvoice).where(
                QboMonthlyInvoice.realm_id == realm,
                QboMonthlyInvoice.qbo_customer_id == str(customer_id),
                QboMonthlyInvoice.mois == mois,
            )
        )
    ).scalars().first()

    if row and row.qbo_invoice_id:
        try:
            existing = await qbo.get_invoice(row.qbo_invoice_id)
            invoice = existing.get("Invoice") or existing
            if not _invoice_locked(invoice):
                updated = await _append_lines(qbo, invoice, lines)
                row.qbo_doc_number = (
                    str(updated.get("DocNumber") or "") or row.qbo_doc_number
                )
                row.updated_at = datetime.now(timezone.utc)
                return {
                    "invoice_id": str(updated.get("Id") or row.qbo_invoice_id),
                    "doc_number": row.qbo_doc_number,
                    "created": False,
                }
            log.info(
                "Facture mensuelle #%s verrouillée (payée/envoyée) — "
                "nouvelle facture pour %s",
                row.qbo_doc_number or row.qbo_invoice_id, customer_id,
            )
        except QuickBooksError as exc:
            # Supprimée dans QBO (ou introuvable) → on en recrée une ;
            # toute autre erreur remonte telle quelle.
            msg = str(exc).lower()
            if not ("object not found" in msg or "610" in msg):
                raise
            log.info(
                "Facture mensuelle %s introuvable dans QBO — recréation "
                "pour %s", row.qbo_invoice_id, customer_id,
            )

    invoice = await _create_monthly(qbo, customer_id, lines, private_note)
    invoice_id = str(invoice.get("Id") or "")
    doc_number = str(invoice.get("DocNumber") or "") or None
    if row:
        row.qbo_invoice_id = invoice_id
        row.qbo_doc_number = doc_number
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(
            QboMonthlyInvoice(
                realm_id=realm,
                scope=scope,
                qbo_customer_id=str(customer_id),
                mois=mois,
                qbo_invoice_id=invoice_id,
                qbo_doc_number=doc_number,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    return {
        "invoice_id": invoice_id,
        "doc_number": doc_number,
        "created": True,
    }
