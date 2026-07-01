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


def _is_stale_token(exc: Exception) -> bool:
    """Vrai si l'erreur QBO indique un SyncToken périmé (« Stale Object »,
    errorCode 5010) — l'objet a changé côté QBO depuis notre dernier
    token. Il faut relire le SyncToken courant et réessayer."""
    msg = str(exc).lower()
    return (
        "stale object" in msg
        or "périmé" in msg
        or "perime" in msg
        or "errorcode=5010" in msg
        or "code': '5010'" in msg
        or "en même temps" in msg
        or "en meme temps" in msg
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
    class_id: Optional[str] = None,
) -> Dict[str, Any]:
    # Montant HT de la ligne. Avec un TaxCodeRef + GlobalTaxCalculation=
    # TaxExcluded, QBO calcule la TPS/TVQ PAR-DESSUS ce HT, donc on doit
    # envoyer le HT (pas le TTC — sinon la taxe serait ajoutée sur un TTC,
    # ce qui gonfle le total, cf. bug « 739,95 au lieu de 643,57 » quand on
    # envoyait le TTC en pensant que QBO le traiterait comme taxe comprise :
    # QBO Purchase n'honore PAS TaxInclusive et ajoute la taxe).
    #   - Achat « normal » : amount = HT déjà (amount_taxes porte la taxe).
    #   - Achat « legacy » : amount = TTC et amount_taxes = 0/None →
    #     on décompose le TTC pour retrouver le HT (facteur 1,14975).
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


def _is_invalid_tax_rate(exc: Exception) -> bool:
    """Vrai si QBO rejette un TaxRateRef non valide pour ce type de
    transaction (« Invalid tax rate id » / « Taux de taxe non valide »).
    Déclenche le repli : on retire les lignes de taxe explicites et on laisse
    QBO calculer la taxe."""
    msg = str(exc).lower()
    return "invalid tax rate" in msg or "taux de taxe non valide" in msg


def _is_locked_txn(exc: Exception) -> bool:
    """Vrai si QBO refuse de MODIFIER la transaction parce qu'elle est
    verrouillée côté comptable : elle a des paiements liés / est rapprochée
    (bank feed), ou c'est un crédit de carte qu'on ne peut pas retransformer
    en dépense. Dans ce cas, on ne peut pas re-synchroniser automatiquement —
    on remonte un message clair à l'utilisateur."""
    msg = str(exc).lower()
    return (
        "a des paiements" in msg
        or "has payments" in msg
        or "ne pouvez pas le changer" in msg
        or "rapprochée" in msg
        or "rapprochee" in msg
        or "reconciled" in msg
        or ("cannot" in msg and "payment" in msg)
    )


def _strip_txn_tax_detail(payload: Dict[str, Any]) -> bool:
    """Retire le TxnTaxDetail explicite (lignes de taxe) du payload pour
    retomber sur le calcul QBO standard (HT + TaxExcluded). Renvoie True si
    le payload a été modifié → un nouvel essai a du sens."""
    if "TxnTaxDetail" in payload:
        payload.pop("TxnTaxDetail", None)
        return True
    return False


async def _resolve_purchase_tax_rate_ids(
    qbo,
) -> tuple[Optional[str], Optional[str]]:
    """(tps_rate_id, tvq_rate_id) VALIDES POUR LES ACHATS, lus depuis le
    PurchaseTaxRateList du code de taxe d'achat configuré (TPS/TVQ QC).

    C'est la clé pour imposer des montants de taxe EXACTS sans « Invalid tax
    rate id » : on prend les taux du VOLET ACHAT du code (pas les taux de
    vente, cause du 400 précédent). Best-effort : (None, None) si indisponible
    → l'appelant retombe sur le calcul QBO standard (~1 cent d'écart)."""
    code_id = settings.qbo_purchase_tax_code
    if not code_id:
        return (None, None)
    code = await qbo.get_tax_code(str(code_id))
    if not code:
        return (None, None)
    details = (
        (code.get("PurchaseTaxRateList") or {}).get("TaxRateDetail") or []
    )
    tps_id: Optional[str] = None
    tvq_id: Optional[str] = None
    for d in details:
        ref = (d.get("TaxRateRef") or {}).get("value")
        if not ref:
            continue
        rate = await qbo.get_tax_rate(str(ref))
        try:
            val = float(rate.get("RateValue")) if rate else None
        except (TypeError, ValueError):
            val = None
        if val is None:
            continue
        if tps_id is None and abs(val - 5.0) < 0.01:
            tps_id = str(ref)
        elif tvq_id is None and abs(val - 9.975) < 0.01:
            tvq_id = str(ref)
    return (tps_id, tvq_id)


def _apply_purchase_tax(
    payload: Dict[str, Any],
    achat: Achat,
    tps_rate_id: Optional[str] = None,
    tvq_rate_id: Optional[str] = None,
) -> None:
    """Applique la taxe d'achat. Le montant de ligne est le HT (cf.
    _build_line) ; deux modes selon ce qu'on a pu résoudre :

    1) EXACT (préféré) : si on connaît les taux d'ACHAT QBO (tps/tvq_rate_id)
       ET la ventilation Kratos (amount_tps/amount_tvq), on pousse des lignes
       de taxe explicites (TxnTaxDetail) avec les montants EXACTS → total QBO
       = HT + TPS + TVQ au cent près (colle au relevé, appariement bancaire).
    2) REPLI : sinon, GlobalTaxCalculation=TaxExcluded et QBO calcule la
       TPS/TVQ par-dessus le HT via le TaxCodeRef de la ligne (~1 cent d'écart
       possible dû à l'arrondi TVQ de QBO). Comportement sûr.

    On n'envoie JAMAIS le TTC en ligne (QBO ajouterait la taxe → total gonflé)
    ni un taux de VENTE (→ « Invalid tax rate id »). Sans code de taxe : rien."""
    if not settings.qbo_purchase_tax_code:
        return
    payload["GlobalTaxCalculation"] = "TaxExcluded"

    def _f(v) -> Optional[float]:
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return None

    tps = _f(achat.amount_tps)
    tvq = _f(achat.amount_tvq)
    if not (
        tps_rate_id
        and tvq_rate_id
        and tps is not None
        and tvq is not None
        and (tps > 0 or tvq > 0)
    ):
        return  # repli : QBO calcule la taxe sur le HT

    net = round(
        sum(float(ln.get("Amount") or 0) for ln in payload.get("Line", [])), 2
    )
    payload["TxnTaxDetail"] = {
        "TotalTax": round(tps + tvq, 2),
        "TaxLine": [
            {
                "Amount": tps,
                "DetailType": "TaxLineDetail",
                "TaxLineDetail": {
                    "TaxRateRef": {"value": str(tps_rate_id)},
                    "PercentBased": True,
                    "TaxPercent": 5,
                    "NetAmountTaxable": net,
                },
            },
            {
                "Amount": tvq,
                "DetailType": "TaxLineDetail",
                "TaxLineDetail": {
                    "TaxRateRef": {"value": str(tvq_rate_id)},
                    "PercentBased": True,
                    "TaxPercent": 9.975,
                    "NetAmountTaxable": net,
                },
            },
        ],
    }


def _build_bill_payload(
    *,
    achat: Achat,
    vendor_id: str,
    expense_account_id: str,
    po_reference: Optional[str],
    project_name: Optional[str],
    customer_id: Optional[str] = None,
    class_id: Optional[str] = None,
    tps_rate_id: Optional[str] = None,
    tvq_rate_id: Optional[str] = None,
    existing_bill_id: Optional[str] = None,
    existing_sync_token: Optional[str] = None,
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
    # HT en ligne ; taxe exacte (TxnTaxDetail) si taux d'achat résolus, sinon
    # QBO la calcule (repli).
    _apply_purchase_tax(payload, achat, tps_rate_id, tvq_rate_id)
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
    class_id: Optional[str] = None,
    payment_method_id: Optional[str] = None,
    tps_rate_id: Optional[str] = None,
    tvq_rate_id: Optional[str] = None,
    existing_purchase_id: Optional[str] = None,
    existing_sync_token: Optional[str] = None,
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
    # HT en ligne ; taxe exacte (TxnTaxDetail) si taux d'achat résolus, sinon
    # QBO la calcule (repli).
    _apply_purchase_tax(payload, achat, tps_rate_id, tvq_rate_id)
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

        # Taux TPS/TVQ d'ACHAT (résolus depuis le code de taxe d'achat) pour
        # imposer des montants de taxe EXACTS → total au cent près. Best-effort
        # (résolu une fois) : (None, None) si indisponible → QBO calcule la
        # taxe (repli, ~1 cent d'écart).
        tps_rate_id, tvq_rate_id = await _resolve_purchase_tax_rate_ids(qbo)

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
                # PAS de return : on continue vers la MAJ (sparse) pour
                # classer la transaction existante sous le projet.

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
                tps_rate_id=tps_rate_id,
                tvq_rate_id=tvq_rate_id,
                existing_purchase_id=achat.qbo_bill_id,
                existing_sync_token=achat.qbo_sync_token,
            )
            if payload.get("Id"):
                try:
                    qbo_obj = await qbo.update_purchase(payload)
                except QuickBooksError as exc:
                    if _is_stale_token(exc):
                        # SyncToken périmé : on relit le token courant
                        # depuis QBO et on réessaie la mise à jour.
                        fresh = await qbo.get_purchase(str(payload["Id"]))
                        payload["SyncToken"] = str(
                            fresh.get("SyncToken") or "0"
                        )
                        qbo_obj = await qbo.update_purchase(payload)
                    elif _is_stale_ref(exc):
                        # L'objet QBO référencé n'est pas une Purchase
                        # (souvent : l'achat était un Bill « sur compte »
                        # puis est passé payé → Purchase). On recrée la
                        # Purchase. NB : on NE SUPPRIME PAS automatiquement
                        # l'ancien Bill (+ paiement) — suppression mise en
                        # attente tant que la comptabilité n'a pas validé
                        # l'approche (cf. delete_bill/_payment disponibles).
                        log.warning(
                            "QBO purchase %s introuvable → recréation "
                            "(ancien Bill conservé) (achat %s)",
                            payload.get("Id"),
                            achat.id,
                        )
                        payload.pop("Id", None)
                        payload.pop("SyncToken", None)
                        payload.pop("sparse", None)
                        qbo_obj = await qbo.create_purchase(payload)
                        did_create = True
                    elif _is_invalid_tax_rate(exc) and _strip_txn_tax_detail(
                        payload
                    ):
                        # Taux d'achat refusé : on retire les lignes de taxe
                        # exactes et on laisse QBO calculer (repli 643,58).
                        log.warning(
                            "QBO taxe exacte refusée → repli calcul QBO "
                            "(achat %s)",
                            achat.id,
                        )
                        qbo_obj = await qbo.update_purchase(payload)
                    else:
                        raise
            else:
                try:
                    qbo_obj = await qbo.create_purchase(payload)
                except QuickBooksError as exc:
                    if _is_invalid_tax_rate(exc) and _strip_txn_tax_detail(
                        payload
                    ):
                        log.warning(
                            "QBO taxe exacte refusée → repli calcul QBO "
                            "(achat %s)",
                            achat.id,
                        )
                        qbo_obj = await qbo.create_purchase(payload)
                    else:
                        raise
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
                tps_rate_id=tps_rate_id,
                tvq_rate_id=tvq_rate_id,
                existing_bill_id=achat.qbo_bill_id,
                existing_sync_token=achat.qbo_sync_token,
            )
            if payload.get("Id"):
                try:
                    qbo_obj = await qbo.update_bill(payload)
                except QuickBooksError as exc:
                    if _is_stale_token(exc):
                        fresh = await qbo.get_bill(str(payload["Id"]))
                        payload["SyncToken"] = str(
                            fresh.get("SyncToken") or "0"
                        )
                        qbo_obj = await qbo.update_bill(payload)
                    elif _is_stale_ref(exc):
                        # Pas un Bill (souvent : l'achat était payé →
                        # Purchase, puis repassé « sur compte » → Bill). On
                        # recrée le Bill SANS supprimer l'ancienne Purchase
                        # (suppression en attente de validation comptable).
                        log.warning(
                            "QBO bill %s introuvable → recréation "
                            "(ancienne Purchase conservée) (achat %s)",
                            payload.get("Id"),
                            achat.id,
                        )
                        payload.pop("Id", None)
                        payload.pop("SyncToken", None)
                        payload.pop("sparse", None)
                        qbo_obj = await qbo.create_bill(payload)
                        did_create = True
                    elif _is_invalid_tax_rate(exc) and _strip_txn_tax_detail(
                        payload
                    ):
                        log.warning(
                            "QBO taxe exacte refusée → repli calcul QBO "
                            "(achat %s)",
                            achat.id,
                        )
                        qbo_obj = await qbo.update_bill(payload)
                    else:
                        raise
            else:
                try:
                    qbo_obj = await qbo.create_bill(payload)
                except QuickBooksError as exc:
                    if _is_invalid_tax_rate(exc) and _strip_txn_tax_detail(
                        payload
                    ):
                        log.warning(
                            "QBO taxe exacte refusée → repli calcul QBO "
                            "(achat %s)",
                            achat.id,
                        )
                        qbo_obj = await qbo.create_bill(payload)
                    else:
                        raise
                did_create = True
    except QuickBooksError as exc:
        if _is_locked_txn(exc):
            raise AchatSyncError(
                "Cette dépense est verrouillée dans QuickBooks (elle a des "
                "paiements liés ou est rapprochée), donc la synchro ne peut "
                "pas la modifier. Ajuste-la directement dans QuickBooks, ou "
                "annule le paiement / le rapprochement avant de "
                "re-synchroniser."
            ) from exc
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
