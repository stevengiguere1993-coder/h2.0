"""Import depuis QuickBooks Online des Bills (factures fournisseur)
qui n'existent pas encore dans Kratos.

Trigger : bouton manuel sur /app/achats (POST /api/v1/achats/sync-
from-qbo). Garde anti-doublon : on saute tout Bill dont l'Id est
deja present comme `qbo_bill_id` sur un Achat Kratos.

Matching :
- Fournisseur : par nom exact (case-insensitive). Si absent, on
  cree un Fournisseur Kratos avec le nom QB.
- Projet : par adresse correspondant a la `Class` du Bill QB. Si
  pas de match (ou pas de Class), on cree l'Achat sans project_id
  (l'utilisateur l'assignera manuellement).
- Statut paiement : si une BillPayment QB pointe sur ce Bill,
  l'Achat est cree directement en `paid` (avec paid_at et methode
  inferee depuis le compte de paiement de la BillPayment).

is_billable : toujours False a l'import. La refacturation client se
pilote depuis Kratos, et la coche QB n'est pas alignee avec la
logique markup_percent de Kratos. L'utilisateur peut toggler dans
Kratos apres l'import s'il veut refacturer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.achat import Achat, AchatStatus, PaymentMethod
from app.models.fournisseur import Fournisseur
from app.models.project import Project


log = logging.getLogger(__name__)


DEFAULT_PAYMENT_TERMS_DAYS = 30


class QboPullError(Exception):
    pass


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


async def _existing_achats_by_qbo_bill_id(
    db: AsyncSession,
) -> Dict[str, Achat]:
    """Charge tous les Achats Kratos avec un qbo_bill_id, indexes par
    cet Id. Permet a la fois de detecter les doublons et de mettre a
    jour le statut paye lors d'un re-pull."""
    rows = (
        await db.execute(
            select(Achat).where(Achat.qbo_bill_id.isnot(None))
        )
    ).scalars().all()
    return {str(a.qbo_bill_id): a for a in rows if a.qbo_bill_id}


async def _find_or_create_fournisseur(
    db: AsyncSession, vendor: Dict[str, Any]
) -> Fournisseur:
    name = (vendor.get("DisplayName") or vendor.get("Name") or "").strip()
    if not name:
        raise QboPullError(
            f"Vendor QB sans nom (Id={vendor.get('Id')})"
        )
    from app.services.achat_qbo import _format_qbo_addr

    vendor_id = str(vendor.get("Id") or "") or None
    qbo_addr = _format_qbo_addr(vendor.get("BillAddr"))
    rows = (
        await db.execute(
            select(Fournisseur).where(
                Fournisseur.name.ilike(name)
            )
        )
    ).scalars().all()
    if rows:
        # Priorise un fournisseur actif si plusieurs matches.
        active = [r for r in rows if r.active]
        match = active[0] if active else rows[0]
        # Backfill l'id vendor QB et l'adresse si on ne les avait pas.
        if vendor_id and not match.qbo_vendor_id:
            match.qbo_vendor_id = vendor_id
        if qbo_addr and not (match.address or "").strip():
            match.address = qbo_addr
        return match
    # Cree le fournisseur a la volee avec ce qu'on connait du Vendor QB.
    email = vendor.get("PrimaryEmailAddr", {}).get("Address")
    phone = vendor.get("PrimaryPhone", {}).get("FreeFormNumber")
    new_f = Fournisseur(
        name=name[:255],
        email=(email or None),
        phone=(phone or None),
        address=qbo_addr,
        qbo_vendor_id=vendor_id,
        active=True,
    )
    db.add(new_f)
    await db.flush()
    return new_f


async def _find_project_by_class(
    db: AsyncSession, class_name: Optional[str]
) -> Optional[Project]:
    """Le push Kratos -> QB met l'adresse du chantier comme nom de
    Class (voir achat_qbo._build_line). On fait le chemin inverse."""
    if not class_name:
        return None
    cname = class_name.strip()
    if not cname:
        return None
    # Match exact d'abord, puis sous-chaine (Class QB peut etre
    # tronquee ou inclure un prefixe genre "Projet · 123 Rue Foo").
    row = (
        await db.execute(
            select(Project).where(Project.address.ilike(cname))
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    # Fallback : LIKE %adresse%
    row = (
        await db.execute(
            select(Project).where(
                Project.address.ilike(f"%{cname}%")
            )
        )
    ).scalar_one_or_none()
    return row


def _sum_bill_amounts(bill: Dict[str, Any]) -> Tuple[float, float]:
    """Retourne (amount_ht, amount_taxes) d'un Bill QB.

    QBO peut stocker TxnTaxDetail.TotalTax separement, ou inclure
    les taxes dans les lignes. On somme les AccountBasedExpenseLineDetail
    pour le HT et on lit TxnTaxDetail.TotalTax pour les taxes.
    """
    lines = bill.get("Line") or []
    ht = Decimal("0")
    for line in lines:
        if line.get("DetailType") == "AccountBasedExpenseLineDetail":
            amt = line.get("Amount")
            if amt is not None:
                ht += Decimal(str(amt))
    taxes = Decimal("0")
    tax_detail = bill.get("TxnTaxDetail") or {}
    total_tax = tax_detail.get("TotalTax")
    if total_tax is not None:
        taxes = Decimal(str(total_tax))
    return float(ht), float(taxes)


def _bill_description(bill: Dict[str, Any]) -> Optional[str]:
    """Tente d'extraire une description lisible : memo prive, sinon
    description de la 1ere ligne expense."""
    private = bill.get("PrivateNote")
    if private:
        return str(private)[:1000]
    for line in bill.get("Line") or []:
        if line.get("DetailType") == "AccountBasedExpenseLineDetail":
            desc = line.get("Description")
            if desc:
                return str(desc)[:1000]
    return None


def _bill_class_name(bill: Dict[str, Any]) -> Optional[str]:
    """Retourne le nom de Class du Bill — au niveau Bill (rare) ou
    de la premiere ligne (cas usuel pour les Bills pousses par
    Kratos qui mettent Class par ligne)."""
    cls = bill.get("ClassRef") or {}
    if cls.get("name"):
        return cls["name"]
    for line in bill.get("Line") or []:
        detail = (
            line.get("AccountBasedExpenseLineDetail") or {}
        )
        c = detail.get("ClassRef") or {}
        if c.get("name"):
            return c["name"]
    return None


async def _bill_payments_index(
    qbo: Any,
) -> Dict[str, Tuple[str, Optional[datetime], Optional[str]]]:
    """Index bill_id -> (billpayment_id, paid_at, payment_method_hint).
    On fait UNE query BillPayment pour ne pas hammer l'API.
    Heuristique de methode : on regarde le PayType (CheckPayment vs
    CreditCardPayment).
    """
    rows = await qbo.query(
        "SELECT * FROM BillPayment MAXRESULTS 1000"
    )
    idx: Dict[
        str, Tuple[str, Optional[datetime], Optional[str]]
    ] = {}
    for p in rows:
        bp_id = str(p.get("Id") or "")
        txn_date = _parse_qbo_date(p.get("TxnDate"))
        pay_type = (p.get("PayType") or "").lower()
        # Heuristique de mapping vers nos PaymentMethod
        if pay_type == "creditcard":
            method_hint = PaymentMethod.CC_STEVEN.value
        elif pay_type == "check":
            method_hint = PaymentMethod.CHEQUE_HORIZON.value
        else:
            method_hint = None
        for line in p.get("Line") or []:
            for ltxn in line.get("LinkedTxn") or []:
                if ltxn.get("TxnType") == "Bill":
                    bill_id = str(ltxn.get("TxnId") or "")
                    if bill_id and bill_id not in idx:
                        idx[bill_id] = (bp_id, txn_date, method_hint)
    return idx


def _parse_qbo_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # QBO renvoie "YYYY-MM-DD".
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def _fournisseur_terms(
    db: AsyncSession, fournisseur_id: int
) -> int:
    f = (
        await db.execute(
            select(Fournisseur).where(Fournisseur.id == fournisseur_id)
        )
    ).scalar_one_or_none()
    if f is None or f.payment_terms_days is None:
        return DEFAULT_PAYMENT_TERMS_DAYS
    return int(f.payment_terms_days)


async def pull_new_bills_from_qbo(
    db: AsyncSession, *, since_days: int = 180
) -> Dict[str, Any]:
    """Pull des Bills QB recents non encore presents dans Kratos.

    Args:
        since_days: fenetre de recherche cote QB (defaut 180j).
                    Utile pour eviter de remonter tout l'historique.

    Returns:
        {
          "imported": int,            # nouveaux Achats crees
          "unmatched_project": int,   # imports sans project_id
          "imported_paid": int,       # parmi les imports, deja payes
          "skipped_existing": int,    # Bills deja presents en Kratos
          "total_qbo_bills": int,     # total Bills QB scannes
        }
    """
    qbo = get_qbo()
    if not qbo.ready:
        raise QboPullError(
            "QuickBooks n'est pas configure (connecte QB d'abord)."
        )

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=since_days)
    ).strftime("%Y-%m-%d")
    try:
        bills = await qbo.query(
            f"SELECT * FROM Bill WHERE TxnDate >= '{cutoff}' "
            "ORDER BY TxnDate DESC MAXRESULTS 1000"
        )
    except QuickBooksError as exc:
        raise QboPullError(f"QB query Bills failed: {exc}")

    existing_by_id = await _existing_achats_by_qbo_bill_id(db)

    try:
        payments_idx = await _bill_payments_index(qbo)
    except QuickBooksError as exc:
        log.warning("BillPayment query failed: %s", exc)
        payments_idx = {}

    stats = {
        "imported": 0,
        "unmatched_project": 0,
        "imported_paid": 0,
        "skipped_existing": 0,
        "paid_synced": 0,  # Achats existants bascules en paye via QB
        "total_qbo_bills": len(bills),
    }

    for bill in bills:
        bill_id = str(bill.get("Id") or "")
        if not bill_id:
            continue
        if bill_id in existing_by_id:
            existing_achat = existing_by_id[bill_id]
            # Si QB a une BillPayment non encore enregistree cote
            # Kratos ET l'Achat n'est pas deja paye → on bascule.
            paid_info = payments_idx.get(bill_id)
            if (
                paid_info is not None
                and not existing_achat.qbo_bill_payment_id
                and existing_achat.status != AchatStatus.PAID.value
            ):
                bp_id, paid_at, method_hint = paid_info
                existing_achat.status = AchatStatus.PAID.value
                existing_achat.paid_at = paid_at
                existing_achat.payment_method = (
                    method_hint or PaymentMethod.CHEQUE_HORIZON.value
                )
                existing_achat.due_at = None
                existing_achat.qbo_bill_payment_id = bp_id or bill_id
                stats["paid_synced"] += 1
            else:
                stats["skipped_existing"] += 1
            continue

        vendor_ref = bill.get("VendorRef") or {}
        vendor_id = vendor_ref.get("value")
        if not vendor_id:
            log.warning("Bill QB %s sans VendorRef — skip", bill_id)
            continue
        try:
            vendor_data = await qbo.query(
                f"SELECT * FROM Vendor WHERE Id = '{vendor_id}'"
            )
            if not vendor_data:
                log.warning(
                    "Vendor QB %s introuvable pour Bill %s",
                    vendor_id,
                    bill_id,
                )
                continue
            fournisseur = await _find_or_create_fournisseur(
                db, vendor_data[0]
            )
        except (QuickBooksError, QboPullError) as exc:
            log.warning("Bill %s vendor lookup failed: %s", bill_id, exc)
            continue

        class_name = _bill_class_name(bill)
        project = await _find_project_by_class(db, class_name)

        amount_ht, amount_taxes = _sum_bill_amounts(bill)
        invoice_date = _parse_qbo_date(bill.get("TxnDate"))
        doc_number = bill.get("DocNumber")
        description = _bill_description(bill)

        paid_info = payments_idx.get(bill_id)
        is_paid = paid_info is not None

        if is_paid:
            bp_id, paid_at, method_hint = paid_info
            method = method_hint or PaymentMethod.CHEQUE_HORIZON.value
            status_value = AchatStatus.PAID.value
            due_at = None
        else:
            bp_id = None
            paid_at = None
            method = PaymentMethod.BILL_TO_PAY.value
            status_value = AchatStatus.RECEIVED.value
            terms = await _fournisseur_terms(db, fournisseur.id)
            base = invoice_date or datetime.now(timezone.utc)
            due_at = base + timedelta(days=terms)

        achat = Achat(
            qbo_bill_id=bill_id,
            qbo_doc_number=doc_number,
            qbo_sync_token=str(bill.get("SyncToken") or ""),
            fournisseur_id=fournisseur.id,
            project_id=project.id if project else None,
            kind="material",
            description=description,
            amount=amount_ht,
            amount_taxes=amount_taxes,
            supplier_invoice_number=(
                doc_number[:64] if doc_number else None
            ),
            invoice_date=(
                invoice_date.date() if invoice_date else None
            ),
            payment_method=method,
            status=status_value,
            received_at=invoice_date,
            paid_at=paid_at,
            due_at=due_at,
            qbo_bill_payment_id=bp_id,
            # Refacturation client pilotee depuis Kratos, pas
            # depuis la coche "Billable" de QB — defaut False a
            # l'import. L'utilisateur toggle dans Kratos s'il veut
            # refacturer.
            is_billable=False,
        )
        db.add(achat)
        stats["imported"] += 1
        if project is None:
            stats["unmatched_project"] += 1
        if is_paid:
            stats["imported_paid"] += 1

    await db.flush()
    log.info("QBO pull terminated: %s", stats)
    return stats
