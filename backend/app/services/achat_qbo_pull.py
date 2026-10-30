"""Import depuis QuickBooks Online des Bills (factures fournisseur)
qui n'existent pas encore dans Kratos.

Trigger : bouton manuel sur /app/achats (POST /api/v1/achats/sync-
from-qbo). Garde anti-doublon : on saute tout Bill dont l'Id est
deja present comme `qbo_bill_id` sur un Achat Kratos.

Matching :
- Fournisseur : par nom exact (case-insensitive). Si absent, on
  cree un Fournisseur Kratos avec le nom QB.
- Projet : ligne par ligne, par le CustomerRef (sous-client QB d'un
  projet Kratos) ou par la `Class` de ligne (= adresse du chantier).
  Une facture sans aucune ligne reliee a un projet Kratos reste dans QB.
  Une facture FRACTIONNEE dans QB (plusieurs projets, ou projet + part
  hors projet : client mere, autre client, aucun client) donne un achat
  PAR projet, chacun pour SA part (HT des lignes du projet, taxes au
  prorata) ; la part hors projet reste dans QB (retour Steven
  2026-10-06 : « importer la separation de factures »).
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
) -> Dict[str, List[Achat]]:
    """Charge tous les Achats Kratos avec un qbo_bill_id, indexes par
    cet Id — en LISTE : une facture divisee sur plusieurs projets donne
    plusieurs achats partageant le meme Id QB. Permet a la fois de
    detecter les doublons et de mettre a jour le statut paye lors d'un
    re-pull."""
    rows = (
        await db.execute(
            select(Achat).where(Achat.qbo_bill_id.isnot(None))
        )
    ).scalars().all()
    out: Dict[str, List[Achat]] = {}
    for a in rows:
        if a.qbo_bill_id:
            out.setdefault(str(a.qbo_bill_id), []).append(a)
    return out


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
        # Créé par un IMPORT QB : lié à l'achat mais HORS annuaire —
        # la section Fournisseurs n'est pas un miroir des Vendors QB.
        in_directory=False,
    )
    db.add(new_f)
    await db.flush()
    return new_f


async def _find_project_by_class(
    db: AsyncSession, class_name: Optional[str]
) -> Optional[Project]:
    """Le push Kratos -> QB mettait l'adresse du chantier comme nom de
    Class (voir achat_qbo._build_line). On fait le chemin inverse.

    Une classe de VOLET (« Construction », « Kratos »…, posee par Kratos
    depuis 2026-10-17) ne designe aucun chantier ; une classe qui
    correspond a PLUSIEURS projets non plus (on ne devine pas — avant,
    `scalar_one_or_none` levait MultipleResultsFound et faisait echouer
    tout l'import)."""
    if not class_name:
        return None
    cname = class_name.strip()
    if not cname or len(cname) < 5:
        return None
    from app.services.qbo_cost_pull import _classe_generique

    if _classe_generique(cname):
        return None
    # Match exact d'abord, puis sous-chaine (Class QB peut etre
    # tronquee ou inclure un prefixe genre "Projet · 123 Rue Foo").
    rows = (
        await db.execute(
            select(Project).where(Project.address.ilike(cname))
        )
    ).scalars().all()
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        return None
    # Fallback : LIKE %adresse% — seulement si UN SEUL projet correspond.
    rows = (
        await db.execute(
            select(Project).where(
                Project.address.ilike(f"%{cname}%")
            )
        )
    ).scalars().all()
    return rows[0] if len(rows) == 1 else None


_LINE_DETAILS = ("AccountBasedExpenseLineDetail", "ItemBasedExpenseLineDetail")


def _ligne_depense(line: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Detail d'une ligne de depense QB (par compte ou par article),
    None pour les autres lignes (sous-totaux, etc.)."""
    for key in _LINE_DETAILS:
        d = line.get(key)
        if d:
            return d
    return None


async def _bill_project_allocations(
    db: AsyncSession,
    bill: Dict[str, Any],
    proj_by_job: Optional[Dict[str, Project]] = None,
) -> Tuple[List[Tuple[Project, float, Optional[str]]], float]:
    """Ventile les lignes de depense du Bill PAR PROJET Kratos.

    Resolution par ligne : CustomerRef → sous-client QB d'un projet
    (``proj_by_job``), sinon la Class de la ligne (= adresse du chantier,
    cf. _find_project_by_class). Une facture fournisseur peut etre
    FRACTIONNEE dans QB entre plusieurs projets, ou entre un projet et
    autre chose (client mere, autre client, aucun client) : seules les
    lignes reliees a un projet Kratos sont retenues, le reste de la
    facture reste dans QuickBooks.

    Retourne ``(allocations, ht_total)`` : les allocations dans l'ordre
    des lignes, un triplet ``(project, ht, description)`` par projet
    DISTINCT ; ``ht_total`` = HT de TOUTES les lignes de depense
    (denominateur des parts).
    """
    out: List[Tuple[Project, float, Optional[str]]] = []
    slots: Dict[int, int] = {}  # project_id -> index dans out
    cache: Dict[str, Optional[Project]] = {}
    ht_total = Decimal("0")
    for line in bill.get("Line") or []:
        detail = _ligne_depense(line)
        if detail is None:
            continue
        amt = line.get("Amount")
        if amt is None:
            continue
        montant = Decimal(str(amt))
        ht_total += montant
        proj: Optional[Project] = None
        cref = str((detail.get("CustomerRef") or {}).get("value") or "")
        if cref and proj_by_job and cref in proj_by_job:
            proj = proj_by_job[cref]
        if proj is None:
            cname = (
                (detail.get("ClassRef") or {}).get("name") or ""
            ).strip()
            if cname:
                if cname not in cache:
                    cache[cname] = await _find_project_by_class(db, cname)
                proj = cache[cname]
        if proj is None:
            continue  # part hors projet : reste dans QB
        desc = (
            str(line.get("Description"))[:1000]
            if line.get("Description")
            else None
        )
        if proj.id in slots:
            idx = slots[proj.id]
            prev_proj, prev_ht, prev_desc = out[idx]
            out[idx] = (prev_proj, prev_ht + float(montant), prev_desc or desc)
        else:
            slots[proj.id] = len(out)
            out.append((proj, float(montant), desc))
    return out, float(ht_total)


def _split_tax_shares(
    taxes: float, hts: List[float], ht_total: Optional[float] = None
) -> List[float]:
    """Repartit les taxes au prorata des HT. ``ht_total`` = HT de TOUTES
    les lignes de la facture : quand il depasse la somme des ``hts``
    (part hors projet), chaque part est calculee sur ce total et la
    somme des parts reste inferieure aux taxes (le reste est dans QB).
    Sinon le dernier slot recoit le reliquat d'arrondi pour retomber
    exactement sur le total."""
    connu = sum(hts)
    if connu <= 0 or not hts:
        return [0.0 for _ in hts]
    if ht_total is not None and ht_total > connu + 0.005:
        return [round(taxes * h / ht_total, 2) for h in hts]
    shares = [round(taxes * h / connu, 2) for h in hts[:-1]]
    shares.append(round(taxes - sum(shares), 2))
    return shares


def _bill_total(
    bill: Dict[str, Any], amount_ht: float, amount_taxes: float
) -> float:
    """Total TTC de la facture QB (TotalAmt), sinon HT + taxes."""
    try:
        if bill.get("TotalAmt") is not None:
            return round(float(bill["TotalAmt"]), 2)
    except (TypeError, ValueError):
        pass
    return round(amount_ht + amount_taxes, 2)


def _sum_bill_amounts(bill: Dict[str, Any]) -> Tuple[float, float]:
    """Retourne (amount_ht, amount_taxes) d'un Bill QB.

    QBO peut stocker TxnTaxDetail.TotalTax separement, ou inclure
    les taxes dans les lignes. On somme les AccountBasedExpenseLineDetail
    pour le HT et on lit TxnTaxDetail.TotalTax pour les taxes.
    """
    lines = bill.get("Line") or []
    ht = Decimal("0")
    for line in lines:
        if _ligne_depense(line) is not None:
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

    # Index de CLASSEMENT Kratos : sous-clients de projets/BT
    # (qbo_job_id). Une facture QB n'est importee QUE si elle se relie a
    # un projet/BT (via sa Class de ligne ou un CustomerRef).
    proj_by_job: Dict[str, Project] = {
        str(p.qbo_job_id): p
        for p in (
            await db.execute(
                select(Project).where(Project.qbo_job_id.isnot(None))
            )
        ).scalars().all()
        if p.qbo_job_id
    }

    stats = {
        "imported": 0,
        "unmatched_project": 0,
        "imported_paid": 0,
        "skipped_existing": 0,
        "paid_synced": 0,  # Achats existants bascules en paye via QB
        # Factures QB sans PROJET/BT Kratos identifiable : laissees dans
        # QB, jamais importees (un client seul ne suffit pas).
        "skipped_unlinked": 0,
        # Factures FRACTIONNEES dans QB : divisees entre plusieurs projets
        # (un achat par projet) / importees pour la seule part des projets.
        "split_multi_projets": 0,
        "parts_partielles": 0,
        "total_qbo_bills": len(bills),
    }

    for bill in bills:
        bill_id = str(bill.get("Id") or "")
        if not bill_id:
            continue
        if bill_id in existing_by_id:
            # Si QB a une BillPayment non encore enregistree cote
            # Kratos ET l'Achat n'est pas deja paye → on bascule. Une
            # facture DIVISEE (plusieurs achats pour le meme Bill) voit
            # TOUTES ses parts basculer.
            paid_info = payments_idx.get(bill_id)
            any_paid = False
            for existing_achat in existing_by_id[bill_id]:
                if (
                    paid_info is not None
                    and not existing_achat.qbo_bill_payment_id
                    and existing_achat.status
                    not in (
                        AchatStatus.PAID.value,
                        AchatStatus.CANCELLED.value,
                    )
                ):
                    bp_id, paid_at, method_hint = paid_info
                    existing_achat.status = AchatStatus.PAID.value
                    existing_achat.paid_at = paid_at
                    existing_achat.payment_method = (
                        method_hint or PaymentMethod.CHEQUE_HORIZON.value
                    )
                    existing_achat.due_at = None
                    existing_achat.qbo_bill_payment_id = bp_id or bill_id
                    any_paid = True
            if any_paid:
                stats["paid_synced"] += 1
            else:
                stats["skipped_existing"] += 1
            continue

        # CLASSEMENT Kratos OBLIGATOIRE avant tout import : la facture
        # doit se relier a un PROJET ou un BON DE TRAVAIL Kratos (donc
        # client + chantier) — ligne par ligne, via le CustomerRef
        # pointant le sous-client d'un projet/BT ou la Class de ligne
        # (= adresse du chantier). Un client seul NE suffit PAS (sinon
        # toute facture QB posee sur un client mere serait aspiree). Les
        # autres factures QB (depenses generales) RESTENT dans QB — Kratos
        # n'est pas un miroir comptable complet. Une facture FRACTIONNEE
        # (plusieurs projets, ou projet + part hors projet) n'entre que
        # pour la part de ses projets.
        allocations, ht_total = await _bill_project_allocations(
            db, bill, proj_by_job
        )
        if not allocations:
            stats["skipped_unlinked"] += 1
            continue
        project = allocations[0][0]

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
            # Échéance prévue dans QB (DueDate) en priorité ; sinon
            # date de facture + conditions du fournisseur.
            # Midi UTC pour ne pas reculer d'un jour en heure de l'Est.
            due_at = _parse_qbo_date(bill.get("DueDate"))
            if due_at is not None:
                due_at = due_at.replace(hour=12)
            else:
                terms = await _fournisseur_terms(db, fournisseur.id)
                base = invoice_date or datetime.now(timezone.utc)
                due_at = base + timedelta(days=terms)

        # Facture FRACTIONNEE dans QB : plusieurs projets → un achat PAR
        # projet ; projet + part hors projet → seule la part du projet
        # entre dans Kratos, le reste reste dans QB. HT = somme des lignes
        # du projet, taxes au prorata du HT de TOUTES les lignes. Sinon,
        # un seul achat au montant complet (comportement historique).
        hts = [ht for _p, ht, _d in allocations]
        partiel = ht_total > round(sum(hts), 2) + 0.005
        qbo_total = _bill_total(bill, amount_ht, amount_taxes)
        if len(allocations) >= 2 or partiel:
            tax_shares = _split_tax_shares(
                amount_taxes, hts, ht_total if partiel else None
            )
            for (proj_i, ht_i, desc_i), tax_i in zip(
                allocations, tax_shares
            ):
                db.add(
                    Achat(
                        qbo_bill_id=bill_id,
                        qbo_doc_number=doc_number,
                        qbo_sync_token=str(bill.get("SyncToken") or ""),
                        fournisseur_id=fournisseur.id,
                        project_id=proj_i.id,
                        kind="material",
                        description=desc_i or description,
                        amount=round(ht_i, 2),
                        amount_taxes=tax_i,
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
                        qbo_txn_total=qbo_total,
                        is_billable=False,
                    )
                )
            stats["imported"] += 1
            if len(allocations) >= 2:
                stats["split_multi_projets"] += 1
            if partiel:
                stats["parts_partielles"] += 1
            if is_paid:
                stats["imported_paid"] += 1
            continue
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
            qbo_txn_total=qbo_total,
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
    # Filet automatique : supprime tout doublon (ex. achat saisi dans
    # Kratos puis ré-importé). Garantit « 1 facture = 1 achat » sans
    # action manuelle.
    from app.services.achat_dedupe import dedupe_achats

    stats["deduped"] = await dedupe_achats(db)
    log.info("QBO pull terminated: %s", stats)
    return stats
