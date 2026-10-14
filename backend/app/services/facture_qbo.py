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


async def record_facture_sync_error(
    facture_id: int, message: Optional[str]
) -> None:
    """Persiste (session FRAÎCHE) la dernière erreur de synchro QBO sur la
    facture — pour qu'elle soit AFFICHÉE sur la fiche sans que l'utilisateur
    lise les logs. Session dédiée : la session appelante a généralement été
    invalidée par l'exception qu'on enregistre. None efface l'erreur."""
    try:
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            fa = await _load_facture(db, facture_id)
            if fa is not None:
                fa.qbo_sync_error = (str(message)[:500] if message else None)
                await db.commit()
    except Exception:  # noqa: BLE001
        log.warning(
            "record_facture_sync_error %s: échec", facture_id, exc_info=True
        )


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


#: Mémo interne posé sur chaque Invoice créée par Kratos : c'est la
#: signature « cette facture QB est de Kratos » (lisible dans QB, champ
#: « Mémo / note interne »).
MEMO_KRATOS = "Kratos facture #{id}"
#: Tolérance sur le total pour reconnaître « la même facture » (migration
#: d'une facture saisie dans QB avant Kratos).
TOLERANCE_TOTAL = 0.05


def _qb_total(inv: Dict[str, Any]) -> Optional[float]:
    try:
        return float(inv.get("TotalAmt"))
    except (TypeError, ValueError):
        return None


async def facture_kratos_liee(db: AsyncSession, qb_invoice_id: str) -> Optional[Facture]:
    """La facture Kratos déjà liée à cette Invoice QB, s'il y en a une."""
    if not qb_invoice_id:
        return None
    return (
        await db.execute(
            select(Facture).where(Facture.qbo_invoice_id == str(qb_invoice_id))
        )
    ).scalar_one_or_none()


def _est_de_kratos(inv: Dict[str, Any]) -> bool:
    return "kratos" in str(inv.get("PrivateNote") or "").lower()


def _meme_facture(
    inv: Dict[str, Any], fa: Facture, customer_ids: set[str]
) -> bool:
    """Une Invoice QB du même numéro est « la nôtre » (facture saisie dans
    QB avant Kratos, lien perdu) si elle est au MÊME client (parent ou
    sous-client/projet) ET au même total. Sinon c'est une autre facture
    qui porte ce numéro par hasard : on ne l'écrase JAMAIS."""
    cust = str((inv.get("CustomerRef") or {}).get("value") or "")
    if not cust or cust not in {str(c) for c in customer_ids if c}:
        return False
    tot = _qb_total(inv)
    try:
        notre = float(fa.total if fa.total is not None else 0)
    except (TypeError, ValueError):
        return False
    return tot is not None and abs(tot - notre) <= TOLERANCE_TOTAL


def est_meme_facture_qb(
    inv: Dict[str, Any], fa: Facture, customer_ids: set[str]
) -> bool:
    """L'Invoice QB du même numéro est-elle CETTE facture Kratos ? Oui si
    elle est signée Kratos (lien perdu) ou au même client et au même
    total (saisie dans QB avant Kratos)."""
    return _est_de_kratos(inv) or _meme_facture(inv, fa, customer_ids)


def desc_facture_qb(inv: Dict[str, Any]) -> str:
    """« client, montant, date » d'une Invoice QB, pour les messages."""
    cust = (inv.get("CustomerRef") or {}).get("name") or "client inconnu"
    tot = _qb_total(inv)
    tot_s = f"{tot:,.2f} $".replace(",", " ") if tot is not None else "montant inconnu"
    date = inv.get("TxnDate") or ""
    return f"{cust}, {tot_s}{', ' + date if date else ''}"


def message_conflit_numero(ref: str, inv: Dict[str, Any]) -> str:
    return (
        f"Une facture {ref} existe déjà dans QuickBooks et elle n'est pas de "
        f"Kratos ({desc_facture_qb(inv)}). Elle n'a pas été touchée."
    )


#: Renumérotations automatiques au plus par synchro. Chaque tour prend le
#: numéro suivant de la séquence ; la limite n'est qu'un filet contre une
#: boucle sans fin si QuickBooks refusait tous les numéros.
MAX_RENUMEROTATIONS = 25


async def renumeroter_facture(db: AsyncSession, fa: Facture, motif: str) -> str:
    """Le numéro de la facture est déjà pris dans QuickBooks par une AUTRE
    facture : on lui donne le prochain numéro libre (Kratos + QuickBooks)
    au lieu de bloquer la synchro (Steven 2026-10-09, facture 152 de
    Connor). Le changement est noté dans les notes internes et le journal.
    Renvoie la note lisible. Flush mais ne committe pas."""
    from app.services.audit import log_action
    from app.services.numbering import attribuer_numero_libre

    ancien = fa.reference
    await attribuer_numero_libre(db, fa)
    note = f"Numéro changé de {ancien} à {fa.reference} : {motif}."
    fa.internal_notes = (
        f"{fa.internal_notes.rstrip()}\n" if (fa.internal_notes or "").strip() else ""
    ) + f"{date.today().isoformat()} — {note}"
    await db.flush()
    log.warning("Facture %s : %s", fa.id, note)
    await log_action(
        db,
        user=None,
        action="facture.renumerotee",
        entity_type="facture",
        entity_id=fa.id,
        details={"ancien": ancien, "nouveau": fa.reference, "motif": motif},
    )
    return note


async def _famille_qb(db: AsyncSession, fa: Facture) -> set[str]:
    """Clients QB déjà connus de la facture (client parent, sous-client du
    projet) — sans appel à QuickBooks."""
    fam: set[str] = set()
    client = await _load_client(db, fa.client_id)
    if client is not None and getattr(client, "qbo_customer_id", None):
        fam.add(str(client.qbo_customer_id))
    if fa.project_id:
        from app.models.project import Project

        job = (
            await db.execute(
                select(Project.qbo_job_id).where(Project.id == fa.project_id)
            )
        ).scalar_one_or_none()
        if job:
            fam.add(str(job))
    return fam


async def numero_pris_dans_qb_pour(
    db: AsyncSession, fa: Facture, ref: str
) -> Optional[Dict[str, Any]]:
    """L'Invoice QB qui porte déjà ce numéro et qui n'est PAS celle de cette
    facture (sinon None). Sert à refuser tout de suite un numéro saisi à la
    main (crayon) que QuickBooks a déjà. None aussi si QB ne répond pas :
    on ne bloque pas la saisie, la synchro renumérotera au besoin."""
    ref = (ref or "").strip()
    if not ref:
        return None
    try:
        qbo = get_qbo()
        await qbo._load_refresh_from_db()
        if not qbo.ready:
            return None
        inv = await qbo.find_invoice_by_docnumber(ref)
    except Exception as exc:  # noqa: BLE001
        log.warning("Vérification du numéro %s dans QB impossible : %s", ref, exc)
        return None
    if not inv or not inv.get("Id"):
        return None
    iid = str(inv.get("Id"))
    if fa.qbo_invoice_id and iid == str(fa.qbo_invoice_id):
        return None
    autre = await facture_kratos_liee(db, iid)
    if autre is not None:
        return None if autre.id == fa.id else inv
    if fa.qbo_invoice_id:
        # La facture a déjà SON Invoice QB : ce numéro est à une autre.
        return inv
    if _est_de_kratos(inv) or _meme_facture(inv, fa, await _famille_qb(db, fa)):
        # Sa propre facture (lien perdu, saisie dans QB avant Kratos).
        return None
    return inv


async def numero_pris_hors_kratos(
    db: AsyncSession, ref: str
) -> Optional[Dict[str, Any]]:
    """L'Invoice QB qui porte déjà ce DocNumber et qui n'est NI liée à une
    facture Kratos NI signée Kratos — sinon None. None aussi si QB n'est
    pas configuré ou ne répond pas (on ne bloque pas la numérotation)."""
    ref = (ref or "").strip()
    if not ref:
        return None
    try:
        qbo = get_qbo()
        await qbo._load_refresh_from_db()
        if not qbo.ready:
            return None
        inv = await qbo.find_invoice_by_docnumber(ref)
    except Exception as exc:  # noqa: BLE001
        log.warning("Vérification du numéro %s dans QB impossible : %s", ref, exc)
        return None
    if not inv:
        return None
    if _est_de_kratos(inv):
        return None
    if await facture_kratos_liee(db, str(inv.get("Id") or "")) is not None:
        return None
    return inv


async def detacher_facture_qbo(db: AsyncSession, facture_id: int) -> Dict[str, Any]:
    """Oublie le lien Kratos ↔ Invoice QB (et les liens de paiements) SANS
    toucher à QuickBooks. Sert quand Kratos s'est accroché à la mauvaise
    Invoice (même numéro, autre facture) : on détache, on renumérote, on
    resynchronise → nouvelle Invoice QB."""
    from app.models.payment import Payment

    fa = await _load_facture(db, facture_id)
    if fa is None:
        raise FactureSyncError(f"Facture {facture_id} introuvable")
    ancien = {"qbo_invoice_id": fa.qbo_invoice_id, "qbo_doc_number": fa.qbo_doc_number}
    fa.qbo_invoice_id = None
    fa.qbo_sync_token = None
    fa.qbo_doc_number = None
    fa.qbo_sync_error = None
    fa.qbo_payment_id = None
    pays = (
        await db.execute(select(Payment).where(Payment.facture_id == facture_id))
    ).scalars().all()
    n_pay = 0
    for pmt in pays:
        if getattr(pmt, "qbo_payment_id", None):
            pmt.qbo_payment_id = None
            n_pay += 1
    await db.flush()
    return {"detache": True, "paiements_detaches": n_pay, **ancien}


async def _build_lines(
    qbo, items: list[FactureItem], fallback_name: str
) -> list[Dict[str, Any]]:
    from decimal import ROUND_HALF_UP, Decimal

    lines: list[Dict[str, Any]] = []
    for it in items:
        qty = float(it.quantity)
        # Le montant STOCKÉ de la ligne est la vérité (c'est lui qui
        # fait le total Kratos). L'ancien round(qty × prix) Python
        # (arrondi bancaire + floats binaires) divergeait parfois d'un
        # cent du calcul de QBO → refus 6070 « montant ≠ prix unitaire
        # × quantité » (vu sur 933.01). On envoie le montant réel et un
        # prix unitaire recalculé en haute précision pour que
        # Qty × UnitPrice retombe exactement dessus côté QBO.
        _total = (
            float(it.total)
            if it.total is not None
            else float(it.quantity) * float(it.unit_price)
        )
        amount = float(
            Decimal(str(_total)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        if qty > 0:
            unit_price = float(
                (Decimal(str(amount)) / Decimal(str(qty))).quantize(
                    Decimal("0.0000001"), rounding=ROUND_HALF_UP
                )
            )
        else:
            qty = 1.0
            unit_price = amount
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
    else:
        # Signature Kratos (mémo interne, invisible du client) : permet de
        # distinguer nos Invoices d'une facture saisie à la main dans QB.
        payload["PrivateNote"] = MEMO_KRATOS.format(id=facture.id)

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


async def _payment_applied_to_invoice(
    qbo, payment_id: str, inv_id: str
) -> bool:
    """Vrai si le Payment QB `payment_id` EXISTE encore ET est bien imputé
    à la facture `inv_id` (présent dans un LinkedTxn de type Invoice).

    Sert à détecter un `qbo_payment_id` PÉRIMÉ : quand le sous-client de la
    facture a été CONVERTI en projet (ou supprimé) dans QB APRÈS
    l'enregistrement du paiement, l'ancien Payment peut avoir disparu ou ne
    plus pointer sur cette facture. Dans ce cas l'appelant l'oublie et le
    recrée, au lieu de le sauter éternellement (idempotence trop stricte)."""
    try:
        data = await qbo._request("GET", f"/payment/{payment_id}")
    except Exception:  # noqa: BLE001
        return False  # 404 / supprimé → à recréer
    obj = data.get("Payment") or data
    if not obj.get("Id"):
        return False
    for line in obj.get("Line", []) or []:
        for lt in line.get("LinkedTxn", []) or []:
            if str(lt.get("TxnId") or "") == str(inv_id) and (
                lt.get("TxnType") == "Invoice"
            ):
                return True
    return False


async def sync_facture_payments_to_qbo(
    qbo,
    db: AsyncSession,
    facture: Facture,
    customer_ref: str,
    inv_id: str,
    errors_out: Optional[list[str]] = None,
) -> list[str]:
    """Pousse CHAQUE virement (ligne de paiement Kratos) de la facture
    comme un Payment QBO DISTINCT — pour qu'il corresponde à une opération
    bancaire appariable dans QB. Idempotent par `Payment.qbo_payment_id`.

    Repli : si la facture est payée mais sans ligne de paiement détaillée
    (ancien flux « marquée payée »), on solde en un seul Payment.
    Retourne la liste des IDs de Payment QBO créés.

    Si `errors_out` (liste) est fourni, chaque échec y ajoute une chaîne
    lisible (motif QBO) — pour que l'appelant puisse le REMONTER À L'ÉCRAN
    au lieu de le laisser en silence dans les logs."""
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
            # Idempotence AVEC garde-fou : on ne saute ce paiement que si son
            # Payment QB existe ENCORE et est bien imputé à cette facture.
            # Sinon (sous-client converti/supprimé depuis, Payment orphelin),
            # on oublie l'ancien id — best-effort delete du Payment orphelin —
            # et on le recrée sous le bon client. Corrige « le 2e virement ne
            # s'envoie pas » après conversion du sous-client.
            if await _payment_applied_to_invoice(qbo, p.qbo_payment_id, inv_id):
                continue
            log.warning(
                "Payment QB %s absent/non imputé à la facture %s → "
                "recréation (facture %s ligne %s)",
                p.qbo_payment_id, inv_id, facture.id, p.id,
            )
            try:
                await qbo.delete_payment(str(p.qbo_payment_id))
            except Exception:  # noqa: BLE001
                pass
            p.qbo_payment_id = None
            await db.flush()
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
            if errors_out is not None:
                errors_out.append(
                    f"Virement {p.amount} $ ({p.paid_at}): {exc}"
                )
    return pushed


async def void_qbo_invoice_now(qbo_invoice_id: str) -> None:
    """Arrière-plan : ANNULE (void) l'Invoice QB d'une facture supprimée
    dans Kratos. Jamais de suppression côté QB — la facture annulée reste
    dans la piste d'audit et la numérotation (retour 2026-09-12, point
    10). Best-effort : loggé, jamais bloquant."""
    try:
        qbo = get_qbo()
        await qbo._load_refresh_from_db()
        if not qbo.ready:
            return
        ok = await qbo.void_invoice(qbo_invoice_id)
        if ok:
            log.info("Invoice QB %s annulée (void)", qbo_invoice_id)
        else:
            log.warning(
                "Invoice QB %s introuvable — rien à annuler",
                qbo_invoice_id,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "void Invoice QB %s échoué : %s", qbo_invoice_id, exc
        )


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

    # Filet : jamais de référence provisoire (« BR-… ») dans QuickBooks —
    # si la facture a quitté le brouillon sans passer par les chemins qui
    # numérotent, on attribue le numéro ici avant de créer l'Invoice.
    from app.services.numbering import ensure_facture_number

    await ensure_facture_number(db, fa)

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

    # Pré-initialisés : utilisés dans le chemin de RÉCUPÉRATION ci-dessous
    # (si la MAJ du corps de facture échoue mais qu'une Invoice QB existe
    # déjà, on pousse quand même les paiements).
    customer_id = ""
    invoice_warning: Optional[str] = None
    #: Notes d'information (facture liée dans QB : client QB conservé).
    _notes: list[str] = []
    #: Renumérotations faites pendant cette synchro (numéro déjà pris dans
    #: QB par une autre facture), une note lisible par changement.
    _renumerotations: list[str] = []
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

        _famille = {
            customer_id,
            invoice_customer_id,
            str(getattr(client, "qbo_customer_id", "") or ""),
        }

        def _motif_numero_pris(inv: Dict[str, Any], autre: Optional[Facture]) -> str:
            if autre is not None:
                return (
                    f"le {fa.reference} est déjà utilisé dans QuickBooks par la "
                    f"facture Kratos {autre.reference} (#{autre.id})"
                )
            return (
                f"le {fa.reference} est déjà pris dans QuickBooks par une autre "
                f"facture ({desc_facture_qb(inv)})"
            )

        async def _renumeroter(motif: str) -> None:
            if len(_renumerotations) >= MAX_RENUMEROTATIONS:
                raise FactureSyncError(
                    f"Aucun numéro libre trouvé dans QuickBooks après "
                    f"{MAX_RENUMEROTATIONS} essais (dernier : {motif}). "
                    "Vérifier le compteur de factures dans Paramètres."
                )
            _renumerotations.append(await renumeroter_facture(db, fa, motif))

        # Si la facture Kratos n'est pas encore liée à une Invoice QB mais
        # qu'une Invoice du MÊME numéro (DocNumber) existe déjà dans QB :
        # - c'est la même facture (signée Kratos, ou même client et même
        #   total : saisie dans QB avant Kratos) → on s'y RATTACHE pour la
        #   mettre à jour et y enregistrer les paiements, sans doublon ;
        # - c'est une AUTRE facture → on ne la touche jamais (incident
        #   facture 145, Phil 2026-10-01) et la facture Kratos prend le
        #   prochain numéro libre, puis on recommence la vérification avec
        #   ce numéro, jusqu'à en trouver un libre (Steven 2026-10-09).
        while not fa.qbo_invoice_id and (fa.reference or "").strip():
            try:
                inv0 = await qbo.find_invoice_by_docnumber(fa.reference)
            except QuickBooksError as exc:
                log.warning(
                    "QBO lookup Invoice DocNumber=%s (facture %s): %s",
                    fa.reference, fa.id, exc,
                )
                inv0 = None
            if not inv0:
                break
            autre = await facture_kratos_liee(db, str(inv0.get("Id") or ""))
            if autre is None and (
                _est_de_kratos(inv0) or _meme_facture(inv0, fa, _famille)
            ):
                fa.qbo_invoice_id = str(inv0.get("Id") or "") or None
                fa.qbo_sync_token = str(inv0.get("SyncToken") or "") or None
                await db.flush()
                break
            await _renumeroter(_motif_numero_pris(inv0, autre))

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
        # « Vous avez tenté d'établir une facture pour une imputation, un
        # crédit, une dépense facturable, des heures ou un devis qui
        # n'existent pas » : l'Invoice QB est LIÉE (devis / heures /
        # dépense facturable) à un autre sous-client, et la MAJ change le
        # CustomerRef (deux projets du même client mélangés, Phil
        # 2026-10-01). QB refuse tout changement de client sur une facture
        # liée → on garde le client QB et les liens de l'Invoice existante.
        _LINK_KEYS = (
            "n'existent pas", "n\u2019existent pas", "does not exist",
            "d\u00e9pense facturable", "billable expense",
        )

        async def _push_invoice(p: Dict[str, Any], _lie_essaye: bool = False) -> Dict[str, Any]:
            try:
                return await qbo.create_invoice(p)
            except QuickBooksError as exc:
                m = str(exc).lower()
                if p.get("Id") and not _lie_essaye and any(k in m for k in _LINK_KEYS):
                    cur = await qbo.get_invoice(str(p["Id"]))
                    cur = cur.get("Invoice") or cur
                    if cur.get("Id"):
                        p2 = dict(p)
                        if cur.get("LinkedTxn"):
                            p2["LinkedTxn"] = cur["LinkedTxn"]
                        cust_qb = str((cur.get("CustomerRef") or {}).get("value") or "")
                        cust_voulu = str((p2.get("CustomerRef") or {}).get("value") or "")
                        if cust_qb and cust_qb != cust_voulu:
                            p2["CustomerRef"] = {"value": cust_qb}
                            nom_qb = (cur.get("CustomerRef") or {}).get("name") or cust_qb
                            _notes.append(
                                "Facture QB liée à un devis / des heures d'un autre "
                                f"sous-client : client QB conservé (« {nom_qb} »), le reste "
                                "mis à jour. Vérifie le projet de cette facture dans QuickBooks."
                            )
                        if cur.get("SyncToken") is not None:
                            p2["SyncToken"] = str(cur.get("SyncToken"))
                        log.warning(
                            "Facture %s : Invoice QB %s liée, MAJ rejouée avec le client QB %s",
                            fa.id, p["Id"], cust_qb,
                        )
                        return await _push_invoice(p2, _lie_essaye=True)
                # Doublon de numéro : la même facture → on s'y relie et on la
                # met à jour ; une AUTRE facture → prochain numéro libre et
                # nouvel essai, jusqu'à ce que QuickBooks accepte.
                if not p.get("Id") and any(k in m for k in _DUP_KEYS):
                    docnum = str(p.get("DocNumber") or "").strip()
                    found = (
                        await qbo.find_invoice_by_docnumber(docnum)
                        if docnum
                        else None
                    )
                    if found and found.get("Id"):
                        autre = await facture_kratos_liee(db, str(found["Id"]))
                        if autre is None and (
                            _est_de_kratos(found) or _meme_facture(found, fa, _famille)
                        ):
                            p["Id"] = str(found["Id"])
                            p["SyncToken"] = str(found.get("SyncToken") or "0")
                            p["sparse"] = True
                            p.pop("PrivateNote", None)
                            return await qbo.create_invoice(p)
                        motif = _motif_numero_pris(found, autre)
                    else:
                        motif = f"QuickBooks refuse le {docnum} (numéro de document en double)"
                    ref_avant = fa.reference
                    await _renumeroter(motif)
                    p["DocNumber"] = fa.reference[:21]
                    for line in p.get("Line") or []:
                        # Ligne de repli d'une facture sans items : son
                        # libellé est le numéro.
                        if line.get("Description") == ref_avant:
                            line["Description"] = fa.reference
                    return await _push_invoice(p)
                # Id obsolète/supprimé → recréer à neuf (avec la signature
                # Kratos, pour la reconnaître ensuite par son numéro).
                if p.get("Id") and any(k in m for k in _STALE_KEYS):
                    p.pop("Id", None)
                    p.pop("SyncToken", None)
                    p.pop("sparse", None)
                    p.setdefault("PrivateNote", MEMO_KRATOS.format(id=fa.id))
                    return await _push_invoice(p)
                raise

        invoice = await _push_invoice(payload)

    except FactureSyncError:
        raise
    except QuickBooksError as exc:
        # Le corps de la facture n'a pas pu être poussé/mis à jour. Si une
        # Invoice QB existe DÉJÀ (facture déjà synchronisée), on NE bloque
        # PAS les paiements : on garde l'Invoice existante et on tente quand
        # même de les pousser (le besoin réel de l'utilisateur). Sans
        # Invoice, impossible d'imputer un paiement → on lève.
        if not (fa.qbo_invoice_id or "").strip():
            raise FactureSyncError(str(exc)) from exc
        log.error(
            "Facture %s : MAJ du corps QB échouée, on tente quand même les "
            "paiements sur l'Invoice existante %s : %s",
            fa.id, fa.qbo_invoice_id, exc,
        )
        invoice = {
            "Id": fa.qbo_invoice_id,
            "SyncToken": fa.qbo_sync_token,
            "DocNumber": fa.qbo_doc_number,
        }
        invoice_warning = f"Corps de la facture non mis à jour dans QB : {exc}"

    inv = invoice.get("Invoice") or invoice
    if inv.get("Id"):
        fa.qbo_invoice_id = str(inv.get("Id"))
    if inv.get("SyncToken") is not None:
        fa.qbo_sync_token = str(inv.get("SyncToken") or "") or None
    if inv.get("DocNumber"):
        fa.qbo_doc_number = str(inv.get("DocNumber") or "") or None
    await db.flush()
    # Chaque virement Kratos → un Payment QBO distinct (appariable à une
    # opération bancaire). Repli sur 1 paiement global si pas de virement.
    # On COLLECTE les échecs pour les remonter à l'utilisateur (au lieu de
    # les laisser en silence dans les logs).
    payment_errors: list[str] = []
    await sync_facture_payments_to_qbo(
        qbo, db, fa, customer_id, str(inv.get("Id") or ""),
        errors_out=payment_errors,
    )
    await db.refresh(fa)

    warnings: list[str] = []
    if invoice_warning:
        warnings.append(invoice_warning)
    # Information, pas un échec : la facture EST à jour dans QB.
    result_notes = list(_renumerotations)
    for n in _notes:
        log.warning("Facture %s : %s", fa.id, n)
        result_notes.append(n)
        break
    if payment_errors:
        warnings.append(
            "Paiement(s) non enregistré(s) dans QuickBooks : "
            + " ; ".join(payment_errors)
        )
    result: Dict[str, Any] = {
        "qbo_invoice_id": fa.qbo_invoice_id or "",
        "qbo_doc_number": fa.qbo_doc_number or "",
        # Le numéro peut avoir changé (renumérotation automatique).
        "reference": fa.reference or "",
    }
    if warnings:
        result["sync_warning"] = " | ".join(warnings)
    if result_notes:
        result["sync_note"] = " ".join(result_notes)
    # Persiste l'état de la dernière synchro sur la facture : l'échec
    # partiel (paiement refusé, corps non mis à jour) devient VISIBLE sur
    # la fiche ; une synchro propre efface l'erreur précédente.
    fa.qbo_sync_error = (
        result.get("sync_warning") or ""
    )[:500] or None
    await db.flush()
    return result


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
        # On ne se relie qu'à SA facture (signée Kratos, ou même client et
        # même total). Une AUTRE facture qui porte ce numéro ne reçoit
        # jamais nos paiements : la synchro complète ci-dessous renumérote
        # et crée la bonne.
        if inv0 and await facture_kratos_liee(db, str(inv0.get("Id") or "")) is None:
            fam = await _famille_qb(db, fa)
            if customer_ref:
                fam.add(customer_ref)
            if _est_de_kratos(inv0) or _meme_facture(inv0, fa, fam):
                inv_id = str(inv0.get("Id") or "")
                fa.qbo_invoice_id = inv_id or None
                fa.qbo_sync_token = str(inv0.get("SyncToken") or "") or None
                await db.flush()

    if not inv_id:
        # Facture pas encore dans QB → synchro complète (crée + paiements).
        return await sync_facture_to_qbo(db, facture_id)

    pushed = await sync_facture_payments_to_qbo(
        qbo, db, fa, customer_ref, inv_id
    )
    await db.flush()
    return {"qbo_invoice_id": inv_id, "payments_pushed": len(pushed)}
