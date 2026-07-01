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


async def _load_achat(db: AsyncSession, achat_id: int) -> Optional[Achat]:
    return (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()


def _build_line(
    achat: Achat,
    expense_account_id: str,
    project_name: Optional[str],
    customer_id: Optional[str] = None,
    class_id: Optional[str] = None,
) -> Dict[str, Any]:
    # Montant TTC de la ligne (mode « taxe comprise », GlobalTaxCalculation=
    # TaxInclusive au niveau de la transaction) : on envoie le MONTANT TOTAL
    # réel — celui du relevé — et QBO ventile la TPS/TVQ À L'INTÉRIEUR via le
    # code de taxe. Le total colle donc exactement (pas d'écart d'arrondi) et
    # aucun taux n'est référencé (pas d'« Invalid tax rate id »). C'est le
    # comportement d'une saisie manuelle « taxe comprise » dans QBO.
    #   - Achat « normal » : amount = HT, amount_taxes = taxe → TTC = somme.
    #   - Achat « legacy »  : amount = TTC, amount_taxes = 0     → TTC = amount.
    # `amount + taxes` couvre les deux cas.
    # NB : ce mode n'est correct QUE si la transaction est bien CRÉÉE en
    # « taxe comprise ». QBO ne rebascule pas fiablement une dépense existante
    # via un sparse update (la taxe serait ajoutée sur le TTC → total gonflé,
    # bug 739,95) : la re-synchro RECRÉE donc la dépense (cf. sync_achat).
    raw_amount = float(achat.amount or 0)
    taxes = float(achat.amount_taxes or 0)
    if settings.qbo_purchase_tax_code:
        amount = round(raw_amount + taxes, 2)
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
    # CustomerRef = le client réel. BillableStatus = « Billable »
    # seulement si on veut le repasser au client dans une facture,
    # sinon « NotBillable » (coût suivi, non refacturé).
    if customer_id:
        detail["CustomerRef"] = {"value": str(customer_id)}
        detail["BillableStatus"] = (
            "Billable" if achat.is_billable else "NotBillable"
        )
    # ClassRef = le projet (chantier), pour le suivi par classe.
    if class_id:
        detail["ClassRef"] = {"value": str(class_id)}
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


def _format_qbo_addr(addr: Optional[Dict[str, Any]]) -> Optional[str]:
    """Aplati un BillAddr QBO (Line1/City/Province/Code postal) en une
    seule ligne lisible pour la stocker sur le Fournisseur Kratos."""
    if not addr:
        return None
    parts = [
        addr.get("Line1"),
        addr.get("Line2"),
        addr.get("City"),
        addr.get("CountrySubDivisionCode"),
        addr.get("PostalCode"),
    ]
    flat = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return flat[:500] or None


def _apply_purchase_tax(payload: Dict[str, Any]) -> None:
    """Mode « taxe comprise » : le montant de ligne est le TTC et QBO ventile
    la TPS/TVQ À L'INTÉRIEUR via le code de taxe de la ligne (TaxCodeRef, posé
    dans _build_line). GlobalTaxCalculation=TaxInclusive → le total envoyé est
    le total réel, QBO n'ajoute rien par-dessus.

    Ne fonctionne QUE sur une transaction CRÉÉE dans ce mode : la re-synchro
    recrée la dépense plutôt que de la patcher (cf. sync_achat). Sans code de
    taxe configuré : on ne touche pas au payload."""
    if settings.qbo_purchase_tax_code:
        payload["GlobalTaxCalculation"] = "TaxInclusive"


async def _delete_old_qbo_txn(qbo, old_id: Optional[str]) -> None:
    """Supprime l'ancien objet QB (Purchase OU Bill) avant de recréer, pour ne
    pas laisser de doublon lors d'une re-synchro. Best-effort et tolérant au
    type : on tente les deux endpoints car l'achat a pu changer de type
    (Bill ↔ Purchase). Ne lève jamais (delete_* renvoie False si l'objet
    n'existe pas / n'est pas du bon type)."""
    if not old_id:
        return
    ok = await qbo.delete_purchase(str(old_id))
    if not ok:
        ok = await qbo.delete_bill(str(old_id))
    if not ok:
        log.warning(
            "QBO: suppression de l'ancien objet %s échouée (doublon possible)",
            old_id,
        )


def _build_bill_payload(
    *,
    achat: Achat,
    vendor_id: str,
    expense_account_id: str,
    po_reference: Optional[str],
    project_name: Optional[str],
    customer_id: Optional[str] = None,
    class_id: Optional[str] = None,
) -> Dict[str, Any]:
    lines = [
        _build_line(
            achat,
            expense_account_id,
            project_name,
            customer_id=customer_id,
            class_id=class_id,
        )
    ]
    payload: Dict[str, Any] = {
        "VendorRef": {"value": str(vendor_id)},
        "TxnDate": _txn_date(achat),
        "DocNumber": _doc_number(achat, po_reference),
        "PrivateNote": _private_note(achat, po_reference, project_name),
        "Line": lines,
    }
    # Taxe comprise : montant de ligne = TTC réel, QB ventile la taxe.
    _apply_purchase_tax(payload)
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
    class_id: Optional[str] = None,
    payment_method_id: Optional[str] = None,
) -> Dict[str, Any]:
    lines = [
        _build_line(
            achat,
            expense_account_id,
            project_name,
            customer_id=customer_id,
            class_id=class_id,
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
    if payment_method_id:
        payload["PaymentMethodRef"] = {"value": str(payment_method_id)}
    # Taxe comprise : montant de ligne = TTC réel, QB ventile la taxe.
    _apply_purchase_tax(payload)
    return payload


def _payment_type_for(method: Optional[str]) -> str:
    """QBO Purchase.PaymentType : Cash / Check / CreditCard."""
    if method and method.startswith("cc_"):
        return "CreditCard"
    if method == "cheque_horizon":
        return "Check"
    return "Cash"


def _payment_method_name_for(method: Optional[str]) -> Optional[str]:
    """Nom du « mode de paiement » QBO (PaymentMethod) à afficher sur la
    dépense — champ distinct du PaymentType. Demandé :
      - carte de crédit Horizon (cc_*) → « Carte de crédit »
      - compte chèque Horizon          → « Virement »
    Retourne None pour les autres modes (pas de PaymentMethodRef)."""
    if method and method.startswith("cc_"):
        return "Carte de crédit"
    if method == "cheque_horizon":
        return "Virement"
    return None


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


# Catégorie QuickBooks (= compte du plan comptable) sur laquelle classer
# une facture de SOUS-TRAITANT. « Sous-traitants » est la catégorie
# standard de QBO ; on essaie quelques variantes d'orthographe par
# robustesse. Ce n'est PAS un réglage : on cible directement la catégorie
# QB existante.
_SOUS_TRAITANT_CATEGORIES = (
    "Sous-traitants",
    "Sous-traitant",
    "Sous-traitance",
    "Subcontractors",
)


async def _resolve_expense_account(
    db, qbo, fournisseur: Optional[Fournisseur] = None,
    is_sous_traitant: bool = False,
) -> Optional[str]:
    """Compte de dépense (= « catégorie » QB) pour la ligne d'achat.

    Priorité :
    0. Facture de SOUS-TRAITANT (kind == 'sub_invoice' ou sous_traitant_id
       renseigné) → catégorie QB « Sous-traitants » (compte standard du
       plan comptable). Prioritaire pour que ces factures soient toujours
       catégorisées comme telles, peu importe le fournisseur.
    1. fournisseur.qbo_expense_account (auto-classification par
       fournisseur — ex. Rona → Matériaux)
    2. QboAccountMap.default_expense_account (fallback global)
    3. Premier compte d'expense disponible côté QB (dernier recours)
    """
    if is_sous_traitant:
        for name in _SOUS_TRAITANT_CATEGORIES:
            acc = await qbo.find_account_by_name(name)
            if acc:
                return str(acc.get("Id"))
        # Catégorie introuvable côté QB → on retombe sur la logique
        # standard plutôt que d'échouer (ne bloque pas l'envoi).
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
    class_id: Optional[str] = None
    if achat.project_id:
        project = (
            await db.execute(
                select(Project).where(Project.id == achat.project_id)
            )
        ).scalar_one_or_none()
        # Organisation QBO demandée :
        #   - Client (CustomerRef) = le client réel, créé s'il n'existe pas.
        #   - Classe (ClassRef)    = le projet (nom/adresse du chantier),
        #     créée si absente (si le suivi des classes est activé).
        if project:
            # RATTACHEMENT AU PROJET QBO : le coût doit pointer vers le
            # SOUS-CLIENT du projet (project.qbo_job_id) pour apparaître
            # dans l'onglet Projets (Revenu/Coût/Marge). Sans ça, le coût
            # va sur le client parent et le projet affiche 0 $.
            # On résout d'ABORD le client parent (nécessaire pour retrouver
            # le sous-client/projet converti), puis le bon CustomerRef du
            # projet — y compris si le sous-client a été converti en projet
            # QB (ancien qbo_job_id supprimé → « client supprimé »).
            parent_customer_id: Optional[str] = None
            if project.client_id:
                from app.models.client import Client

                client = (
                    await db.execute(
                        select(Client).where(Client.id == project.client_id)
                    )
                ).scalar_one_or_none()
                if client:
                    try:
                        cust = await qbo.ensure_customer(
                            display_name=client.name,
                            email=client.email,
                            phone=client.phone,
                            billing_address=client.address,
                        )
                        parent_customer_id = str(cust.get("Id") or "") or None
                    except QuickBooksError as exc:
                        log.warning(
                            "QBO: client introuvable/échec (achat %s): %s",
                            achat.id,
                            exc,
                        )
            if parent_customer_id:
                from app.services.qbo_project_resolve import (
                    resolve_project_customer_id,
                )

                customer_id = await resolve_project_customer_id(
                    qbo, db, project, parent_customer_id
                )
            elif getattr(project, "qbo_job_id", None):
                customer_id = str(project.qbo_job_id)
            # Classe = adresse du chantier (repli sur le nom du projet
            # si l'adresse est vide).
            class_name = (
                (getattr(project, "address", None) or "").strip()
                or (project.name or "").strip()
            )
            if class_name:
                klass = await qbo.ensure_class(name=class_name)
                class_id = (
                    str(klass.get("Id")) if klass and klass.get("Id") else None
                )
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

    # True seulement si on CRÉE un nouvel objet QBO (1ʳᵉ sync ou
    # recréation après suppression). On ne (ré)attache la pièce jointe
    # que dans ce cas, pour éviter de dupliquer la facture à chaque
    # re-synchro (update).
    did_create = False
    try:
        vendor = await qbo.ensure_vendor(
            display_name=fournisseur.name,
            email=fournisseur.email,
            phone=fournisseur.phone,
            billing_address=(fournisseur.address or None),
        )
        vendor_id = str(vendor.get("Id") or "")
        if not vendor_id:
            raise AchatSyncError("QBO n'a pas retourné d'id vendor.")

        # Backfill dans Kratos : on memorise l'id du vendor QB et, si le
        # fournisseur n'a pas encore d'adresse, on importe celle de QB
        # (« importer son adresse dans Kratos »).
        if not fournisseur.qbo_vendor_id:
            fournisseur.qbo_vendor_id = vendor_id
        if not (fournisseur.address or "").strip():
            qbo_addr = _format_qbo_addr(vendor.get("BillAddr"))
            if qbo_addr:
                fournisseur.address = qbo_addr

        # Facture de sous-traitant → compte « Sous-traitant » dédié
        # (kind == 'sub_invoice' OU un sous-traitant est rattaché).
        is_sous_traitant = (
            (achat.kind or "").lower() == "sub_invoice"
            or achat.sous_traitant_id is not None
        )
        expense_account_id = await _resolve_expense_account(
            db, qbo, fournisseur=fournisseur,
            is_sous_traitant=is_sous_traitant,
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

        # Anti-doublon : si cet Achat n'est pas encore lie a un objet QB,
        # on verifie qu'un Bill/Purchase equivalent (meme fournisseur,
        # meme total TTC, ~meme date) existe deja cote QuickBooks. Si oui,
        # on s'y RATTACHE (qbo_bill_id) PUIS on le MET A JOUR plus bas pour
        # le classer dans le bon PROJET (CustomerRef + ClassRef) — comme les
        # factures. Avant, on retournait ici sans classer → l'achat restait
        # dans QB mais hors du projet.
        if not achat.qbo_bill_id:
            total_ttc = float(achat.amount or 0) + float(achat.amount_taxes or 0)
            entity = "Purchase" if as_purchase else "Bill"
            docnum = _doc_number(achat, po_reference)
            try:
                # 1) Signal FORT : un Bill/Purchase QB avec le MÊME numéro de
                #    document (n° facture fournisseur / PO) existe déjà → on
                #    s'y relie au lieu de recréer (cas migration : la facture
                #    était déjà dans QB).
                dup = await qbo.find_txn_by_docnumber(entity, docnum)
                # 2) Repli : même fournisseur + même total TTC + ~même date.
                if not (dup and dup.get("Id")):
                    if as_purchase:
                        dup = await qbo.find_existing_purchase(
                            vendor_id=vendor_id,
                            total=total_ttc,
                            txn_date=_txn_date(achat),
                        )
                    else:
                        dup = await qbo.find_existing_bill(
                            vendor_id=vendor_id,
                            total=total_ttc,
                            txn_date=_txn_date(achat),
                        )
            except QuickBooksError as exc:
                # Recherche best-effort : si la query echoue, on continue
                # le push normal plutot que de bloquer.
                log.warning(
                    "Anti-doublon lookup failed for Achat %s: %s",
                    achat.id, exc,
                )
                dup = None
            if dup and dup.get("Id"):
                achat.qbo_bill_id = str(dup["Id"])
                achat.qbo_sync_token = str(dup.get("SyncToken") or "0")
                if dup.get("DocNumber"):
                    achat.qbo_doc_number = str(dup["DocNumber"])
                await db.flush()
                log.info(
                    "Achat %s rattache a un %s QB existant %s → MAJ projet",
                    achat.id,
                    "Purchase" if as_purchase else "Bill",
                    achat.qbo_bill_id,
                )
                # PAS de return : on continue vers le bloc de push, qui
                # supprimera cette transaction existante puis la recréera en
                # « taxe comprise », classée sous le projet.

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
            # Mode de paiement QBO (PaymentMethod) : CC → « Carte de
            # crédit », chèque Horizon → « Virement ». Créé si absent.
            pm_name = _payment_method_name_for(method)
            payment_method_id: Optional[str] = None
            if pm_name:
                pm = await qbo.ensure_payment_method(name=pm_name)
                payment_method_id = (
                    str(pm.get("Id")) if pm and pm.get("Id") else None
                )
            payload = _build_purchase_payload(
                achat=achat,
                vendor_id=vendor_id,
                expense_account_id=expense_account_id,
                payment_account_id=payment_account_id,
                payment_type=_payment_type_for(method),
                payment_method_id=payment_method_id,
                po_reference=po_reference,
                project_name=project.name if project else None,
                customer_id=customer_id,
                class_id=class_id,
            )
            # Re-synchro en « taxe comprise » : on SUPPRIME l'ancienne dépense
            # puis on en CRÉE une neuve, au lieu d'un sparse update. QBO ne
            # rebascule pas fiablement une dépense existante en « taxe
            # comprise » (il ajouterait la taxe sur le TTC → total gonflé,
            # bug 739,95) ; recréer garantit qu'elle naît dans le bon mode,
            # comme une saisie manuelle. Le nouvel Id remplace l'ancien.
            await _delete_old_qbo_txn(qbo, achat.qbo_bill_id)
            qbo_obj = await qbo.create_purchase(payload)
            did_create = True
        else:
            # Sur compte fournisseur (chèque / net-30) → Bill
            payload = _build_bill_payload(
                achat=achat,
                vendor_id=vendor_id,
                expense_account_id=expense_account_id,
                po_reference=po_reference,
                project_name=project.name if project else None,
                customer_id=customer_id,
                class_id=class_id,
            )
            # Re-synchro : delete + create (idem Purchase ci-dessus).
            await _delete_old_qbo_txn(qbo, achat.qbo_bill_id)
            qbo_obj = await qbo.create_bill(payload)
            did_create = True
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
    # On n'attache la pièce QUE lors d'une création (did_create), pas à
    # chaque re-synchro (update), pour éviter de dupliquer la facture
    # dans QBO.
    receipt_attached = False
    receipt_error: Optional[str] = None
    if did_create and qbo_id and achat.receipt_image_content_type:
        try:
            await db.refresh(achat, attribute_names=["receipt_image"])
        except Exception as exc:  # noqa: BLE001
            receipt_error = f"refresh: {exc}"
            log.warning("Refresh receipt_image failed: %s", exc)
    if did_create and qbo_id and achat.receipt_image:
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


async def push_bill_payment_to_qbo(
    db: AsyncSession, achat_id: int
) -> Dict[str, Any]:
    """Cree une BillPayment dans QB qui paye le Bill lie a cet Achat.

    Pre-conditions : l'Achat doit avoir status=paid, qbo_bill_id,
    payment_method != bill_to_pay, et pas encore de
    qbo_bill_payment_id (idempotence).

    Retourne {'ok': True, 'qbo_bill_payment_id': '...'} ou skip si
    deja sync ou pas applicable.
    """
    achat = await _load_achat(db, achat_id)
    if achat is None:
        return {"ok": False, "reason": "achat_not_found"}
    if not achat.qbo_bill_id:
        # Pas un Bill QB (probablement un Purchase paye direct) :
        # rien a payer dans QB.
        return {"ok": False, "reason": "no_qbo_bill"}
    if achat.qbo_bill_payment_id:
        # Deja sync, on ne re-cree pas.
        return {"ok": True, "qbo_bill_payment_id": achat.qbo_bill_payment_id}
    if (achat.payment_method or "") == "bill_to_pay":
        return {"ok": False, "reason": "method_is_bill_to_pay"}
    if achat.status != "paid":
        return {"ok": False, "reason": "not_paid"}

    qbo = get_qbo()
    if not qbo.ready:
        return {"ok": False, "reason": "qbo_not_configured"}

    method = (achat.payment_method or "").lower()
    payment_account_id = await _resolve_payment_account(db, qbo, method)
    if not payment_account_id:
        return {
            "ok": False,
            "reason": (
                f"no_payment_account_mapped_for_{method}"
            ),
        }

    fournisseur = (
        await db.execute(
            select(Fournisseur).where(
                Fournisseur.id == achat.fournisseur_id
            )
        )
    ).scalar_one_or_none() if achat.fournisseur_id else None
    if fournisseur is None:
        return {"ok": False, "reason": "no_fournisseur"}

    vendor = await qbo.ensure_vendor(
        display_name=fournisseur.name,
        email=fournisseur.email,
        phone=fournisseur.phone,
    )
    vendor_id = str(vendor.get("Id") or "")
    if not vendor_id:
        return {"ok": False, "reason": "vendor_resolve_failed"}

    # Montant total a payer (HT + taxes) — un BillPayment paie le
    # TOTAL TTC du Bill, pas juste le HT.
    total = float(achat.amount or 0) + float(achat.amount_taxes or 0)
    if total <= 0:
        return {"ok": False, "reason": "zero_amount"}

    pay_type_check = method == "cheque_horizon"
    payload: Dict[str, Any] = {
        "VendorRef": {"value": vendor_id},
        "TotalAmt": round(total, 2),
        "PayType": "Check" if pay_type_check else "CreditCard",
        "Line": [
            {
                "Amount": round(total, 2),
                "LinkedTxn": [
                    {
                        "TxnId": str(achat.qbo_bill_id),
                        "TxnType": "Bill",
                    }
                ],
            }
        ],
    }
    if achat.paid_at:
        payload["TxnDate"] = achat.paid_at.strftime("%Y-%m-%d")
    account_block = {
        "BankAccountRef": {"value": payment_account_id}
    } if pay_type_check else {
        "CCAccountRef": {"value": payment_account_id}
    }
    if pay_type_check:
        payload["CheckPayment"] = account_block
    else:
        payload["CreditCardPayment"] = account_block

    try:
        created = await qbo.create_bill_payment(payload)
    except QuickBooksError as exc:
        log.warning(
            "BillPayment push failed for Achat %s: %s",
            achat.id,
            exc,
        )
        return {"ok": False, "reason": f"qbo_error: {exc}"}

    bp_id = str(created.get("Id") or "")
    if bp_id:
        achat.qbo_bill_payment_id = bp_id
        await db.flush()
    return {"ok": True, "qbo_bill_payment_id": bp_id}
