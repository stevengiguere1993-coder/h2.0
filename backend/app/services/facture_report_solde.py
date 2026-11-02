"""Report d'un petit solde impayé sur la prochaine facture du même client.

Steven (2026-11-02) : « parfois les clients reçoivent de très gros montants
et de petits montants sont oubliés de payer, ex. 15 $ sur une facture de
18 000 $ […] pour que tout balance dans QuickBooks et qu'on n'ait pas une
facture en retard pour rien ». Puis : « lorsque nous classons la facture
dans payé, le report devrait se faire automatiquement s'il reste un montant
sur la facture à payer ».

Mécanique (option A retenue) :

1. Facture d'origine : le solde est FERMÉ. Dans QuickBooks, un Payment du
   montant restant est imputé à l'Invoice et déposé dans le compte de
   transit « Soldes reportés » (actif à court terme) — pas dans la banque.
   L'Invoice passe « Payée », plus de retard ni de rappels.
2. Prochaine facture du client : ligne ``kind="report"`` « Solde reporté de
   la facture X », HORS TAXES (le montant est déjà TTC), dont le produit QB
   pointe sur le MÊME compte de transit. Le compte revient à 0 ; revenus et
   taxes ne bougent pas ; les comptes clients restent exacts.

Pourquoi un Payment vers le compte de transit plutôt qu'une note de
crédit : même écriture comptable, mais une note de crédit peut être
appliquée d'office par QuickBooks à une AUTRE facture ouverte du client
(réglage « Appliquer automatiquement les crédits ») ; le Payment, lui, est
imputé explicitement à la facture d'origine.

Un report n'est PAS un paiement Kratos (table à part) : il ne compte ni
dans les entrées de fonds, ni dans les finances de projet, ni dans le
profit. La facture d'origine est soldée par « paiements + reports ».
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.facture import Facture, FactureStatus
from app.models.facture_item import FactureItem
from app.models.facture_report_solde import (
    REPORT_ANNULE,
    REPORT_APPLIQUE,
    REPORT_EN_ATTENTE,
    FactureReportSolde,
)
from app.models.payment import Payment
from app.services.facture_lignes import KIND_REPORT

log = logging.getLogger(__name__)

#: Type de compte QB du compte de transit.
COMPTE_TYPE = "Other Current Asset"
COMPTE_SOUS_TYPE = "OtherCurrentAssets"

#: Noms de codes de taxe QB acceptés pour la ligne reportée, par ordre de
#: préférence (comparés sans accents ni casse).
_NOMS_TAXE_EXONEREE = (
    "hors champ",
    "out of scope",
    "exonere",
    "exempt",
    "detaxe",
    "zero-rated",
    "zero rated",
    "taux zero",
)


class ReportImpossible(ValueError):
    """Le report demandé n'est pas permis (motif lisible pour l'écran)."""


def plafond() -> float:
    return float(settings.facture_report_plafond or 0)


def _money(v: float) -> str:
    return f"{v:,.2f} $".replace(",", " ").replace(".", ",")


def libelle_report(reference: Optional[str]) -> str:
    return f"Solde reporté de la facture {reference or '?'}"


# ── Montants ────────────────────────────────────────────────────────────


async def montant_paye(db: AsyncSession, facture_id: int) -> float:
    v = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.facture_id == facture_id
            )
        )
    ).scalar_one()
    return round(float(v or 0), 2)


async def montant_reporte(db: AsyncSession, facture_id: int) -> float:
    """Soldes de cette facture déjà reportés (reports non annulés)."""
    v = (
        await db.execute(
            select(func.coalesce(func.sum(FactureReportSolde.montant), 0)).where(
                FactureReportSolde.origine_facture_id == facture_id,
                FactureReportSolde.statut != REPORT_ANNULE,
            )
        )
    ).scalar_one()
    return round(float(v or 0), 2)


async def solde_restant(db: AsyncSession, fa: Facture) -> float:
    """Total − paiements − soldes déjà reportés."""
    total = float(fa.total or 0)
    reste = total - await montant_paye(db, fa.id) - await montant_reporte(db, fa.id)
    return round(max(0.0, reste), 2)


# ── Création ────────────────────────────────────────────────────────────


async def reporter_solde(
    db: AsyncSession,
    fa: Facture,
    *,
    user_id: Optional[int] = None,
    automatique: bool = False,
) -> FactureReportSolde:
    """Ferme le petit solde de ``fa`` et le met en attente de la prochaine
    facture du client (ajouté tout de suite à un brouillon s'il y en a un).
    La facture d'origine passe « payée ». Le Payment QB est poussé ensuite
    (``pousser_report_qbo``). Lève ReportImpossible avec un motif lisible."""
    statut = fa.status or ""
    if statut in (FactureStatus.DRAFT.value, FactureStatus.VOID.value):
        raise ReportImpossible(
            "Seule une facture envoyée au client peut reporter son solde."
        )
    if not fa.client_id:
        raise ReportImpossible(
            "La facture n'a pas de client : impossible de reporter le solde "
            "sur sa prochaine facture."
        )
    montant = await solde_restant(db, fa)
    if montant < 0.01:
        raise ReportImpossible("La facture n'a plus de solde à reporter.")
    if montant > plafond() + 0.005:
        raise ReportImpossible(
            f"Le solde de {_money(montant)} dépasse le maximum reportable "
            f"({_money(plafond())}) : c'est un vrai impayé, pas un oubli."
        )
    rep = FactureReportSolde(
        client_id=fa.client_id,
        origine_facture_id=fa.id,
        montant=montant,
        statut=REPORT_EN_ATTENTE,
        automatique=automatique,
        created_by_id=user_id,
    )
    db.add(rep)
    await db.flush()
    if fa.status != FactureStatus.PAID.value:
        fa.status = FactureStatus.PAID.value
    if fa.paid_at is None:
        fa.paid_at = datetime.now(timezone.utc)
    fa.balance = 0
    await db.flush()
    await attacher_a_un_brouillon(db, rep, fa)
    log.info(
        "Facture %s : solde de %s reporté (report %s%s)",
        fa.reference, montant, rep.id, ", automatique" if automatique else "",
    )
    return rep


async def reporter_au_classement_paye(
    db: AsyncSession, fa: Facture, *, user_id: Optional[int] = None
) -> Optional[FactureReportSolde]:
    """Facture classée « payée » à la main alors qu'il reste un petit solde :
    report automatique (Steven 2026-11-02). Seulement si au moins un
    paiement est enregistré (sinon « payée » veut dire payée en entier hors
    Kratos, l'ancien flux) et si le reste ne dépasse pas le plafond."""
    if await montant_paye(db, fa.id) <= 0:
        return None
    reste = await solde_restant(db, fa)
    if reste < 0.01 or reste > plafond() + 0.005 or not fa.client_id:
        if reste > plafond() + 0.005:
            log.info(
                "Facture %s classée payée avec un solde de %s : au-dessus "
                "du plafond de report, rien n'est reporté",
                fa.reference, reste,
            )
        return None
    try:
        return await reporter_solde(db, fa, user_id=user_id, automatique=True)
    except ReportImpossible as exc:
        log.info("Report automatique facture %s non fait : %s", fa.reference, exc)
        return None


# ── Ligne sur la facture cible ──────────────────────────────────────────


async def _recalculer_totaux(db: AsyncSession, facture_id: int) -> None:
    from app.api.v1.endpoints.facture_items import _recompute_facture_totals

    await _recompute_facture_totals(db, facture_id)


async def appliquer_sur(
    db: AsyncSession, rep: FactureReportSolde, cible: Facture
) -> FactureItem:
    """Ajoute la ligne « Solde reporté de la facture X » en fin de facture."""
    origine = await db.get(Facture, rep.origine_facture_id)
    positions = (
        await db.execute(
            select(FactureItem.position).where(FactureItem.facture_id == cible.id)
        )
    ).scalars().all()
    montant = round(float(rep.montant or 0), 2)
    item = FactureItem(
        facture_id=cible.id,
        position=(max(positions) + 1) if positions else 0,
        description=libelle_report(getattr(origine, "reference", None)),
        quantity=1,
        unit_price=montant,
        total=montant,
        kind=KIND_REPORT,
        # Ni avancement de soumission, ni revenu : déjà facturé ailleurs.
        hors_soumission=True,
    )
    db.add(item)
    await db.flush()
    rep.cible_facture_id = cible.id
    rep.cible_item_id = item.id
    rep.statut = REPORT_APPLIQUE
    await db.flush()
    await _recalculer_totaux(db, cible.id)
    return item


def _cible_possible(
    rep: FactureReportSolde, cible: Facture, *, sortie_de_brouillon: bool = False
) -> bool:
    statut_ok = (cible.status or "") == FactureStatus.DRAFT.value or (
        sortie_de_brouillon and (cible.status or "") != FactureStatus.VOID.value
    )
    return (
        cible.id != rep.origine_facture_id
        and cible.id != rep.facture_exclue_id
        and statut_ok
        and cible.client_id == rep.client_id
    )


async def attacher_a_un_brouillon(
    db: AsyncSession, rep: FactureReportSolde, origine: Facture
) -> Optional[Facture]:
    """Brouillon déjà ouvert pour le client → la ligne y va tout de suite
    (même projet d'abord, sinon le plus récent). Sinon le report attend."""
    brouillons = (
        await db.execute(
            select(Facture)
            .where(
                Facture.client_id == rep.client_id,
                Facture.status == FactureStatus.DRAFT.value,
                Facture.id != origine.id,
            )
            .order_by(Facture.id.desc())
        )
    ).scalars().all()
    brouillons = [b for b in brouillons if _cible_possible(rep, b)]
    if not brouillons:
        return None
    meme_projet = [
        b for b in brouillons
        if origine.project_id and b.project_id == origine.project_id
    ]
    cible = (meme_projet or brouillons)[0]
    await appliquer_sur(db, rep, cible)
    return cible


async def appliquer_reports_en_attente(
    db: AsyncSession, cible: Facture, *, sortie_de_brouillon: bool = False
) -> int:
    """Ajoute à ce BROUILLON les soldes du client qui attendent leur
    prochaine facture. Idempotent. Appelé à l'ouverture d'un brouillon, à
    l'envoi et à la sortie de l'état brouillon (``sortie_de_brouillon`` :
    le statut vient de quitter « brouillon » dans la même requête)."""
    if not cible.client_id:
        return 0
    if not sortie_de_brouillon and (cible.status or "") != FactureStatus.DRAFT.value:
        return 0
    attente = (
        await db.execute(
            select(FactureReportSolde)
            .where(
                FactureReportSolde.client_id == cible.client_id,
                FactureReportSolde.statut == REPORT_EN_ATTENTE,
            )
            .order_by(FactureReportSolde.id.asc())
        )
    ).scalars().all()
    n = 0
    for rep in attente:
        if _cible_possible(rep, cible, sortie_de_brouillon=sortie_de_brouillon):
            await appliquer_sur(db, rep, cible)
            n += 1
    return n


async def liberer_ligne(db: AsyncSession, item: FactureItem) -> None:
    """La ligne reportée est retirée d'un brouillon à la main : le report
    retourne en attente de la facture SUIVANTE (pas celle-ci)."""
    rep = (
        await db.execute(
            select(FactureReportSolde).where(
                FactureReportSolde.cible_item_id == item.id
            )
        )
    ).scalar_one_or_none()
    if rep is None or rep.statut == REPORT_ANNULE:
        return
    rep.statut = REPORT_EN_ATTENTE
    rep.facture_exclue_id = item.facture_id
    rep.cible_facture_id = None
    rep.cible_item_id = None
    await db.flush()


async def liberer_facture_supprimee(db: AsyncSession, facture_id: int) -> None:
    """Facture cible supprimée : ses reports attendent la prochaine."""
    reps = (
        await db.execute(
            select(FactureReportSolde).where(
                FactureReportSolde.cible_facture_id == facture_id,
                FactureReportSolde.statut == REPORT_APPLIQUE,
            )
        )
    ).scalars().all()
    for rep in reps:
        rep.statut = REPORT_EN_ATTENTE
        rep.cible_facture_id = None
        rep.cible_item_id = None
    if reps:
        await db.flush()


async def facture_supprimee(db: AsyncSession, facture_id: int) -> None:
    """Facture supprimée. Cible : ses reports attendent la prochaine
    facture. Origine : ses reports sont annulés (ligne retirée du brouillon,
    Payment QB supprimé) ; s'il est déjà facturé ailleurs, il reste."""
    await liberer_facture_supprimee(db, facture_id)
    reps = (
        await db.execute(
            select(FactureReportSolde).where(
                FactureReportSolde.origine_facture_id == facture_id,
                FactureReportSolde.statut != REPORT_ANNULE,
            )
        )
    ).scalars().all()
    for rep in reps:
        try:
            await annuler_report(db, rep, recalculer_origine=False)
        except ReportImpossible as exc:
            log.warning(
                "Facture %s supprimée : report %s gardé (%s)",
                facture_id, rep.id, exc,
            )


# ── Annulation ──────────────────────────────────────────────────────────


async def annuler_report(
    db: AsyncSession, rep: FactureReportSolde, *, recalculer_origine: bool = True
) -> None:
    """Annule le report : la ligne est retirée du brouillon, le Payment QB
    supprimé et la facture d'origine redevient ouverte. Refusé si la ligne
    est déjà sur une facture envoyée au client."""
    if rep.statut == REPORT_ANNULE:
        return
    if rep.cible_facture_id:
        cible = await db.get(Facture, rep.cible_facture_id)
        if cible is not None and (cible.status or "") != FactureStatus.DRAFT.value:
            raise ReportImpossible(
                f"Le solde est déjà facturé sur la facture {cible.reference}, "
                "envoyée au client : le report ne peut plus être annulé."
            )
        if rep.cible_item_id:
            item = await db.get(FactureItem, rep.cible_item_id)
            if item is not None:
                await db.delete(item)
                await db.flush()
        if cible is not None:
            await _recalculer_totaux(db, cible.id)
    if rep.qbo_payment_id:
        from app.integrations.quickbooks import get_qbo

        qbo = get_qbo()
        await qbo._load_refresh_from_db()
        if not qbo.ready or not await qbo.delete_payment(str(rep.qbo_payment_id)):
            raise ReportImpossible(
                "QuickBooks n'a pas pu supprimer le paiement qui ferme le "
                "solde : rien n'a été annulé."
            )
        rep.qbo_payment_id = None
    rep.statut = REPORT_ANNULE
    rep.cible_facture_id = None
    rep.cible_item_id = None
    rep.annule_le = datetime.now(timezone.utc)
    await db.flush()
    origine = (
        await db.get(Facture, rep.origine_facture_id) if recalculer_origine else None
    )
    if origine is not None:
        from app.api.v1.endpoints.payments import _recompute_facture_status

        await _recompute_facture_status(db, origine)
        origine.balance = await solde_restant(db, origine)
        await db.flush()


# ── QuickBooks ──────────────────────────────────────────────────────────

_cache_qbo: Dict[str, str] = {}


def _sans_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


async def compte_transit_id(qbo) -> str:
    if "compte" not in _cache_qbo:
        acc = await qbo.ensure_account(
            name=settings.qbo_report_compte,
            account_type=COMPTE_TYPE,
            account_sub_type=COMPTE_SOUS_TYPE,
        )
        if not acc or not acc.get("Id"):
            from app.integrations.quickbooks import QuickBooksError

            raise QuickBooksError(
                f"Compte « {settings.qbo_report_compte} » introuvable dans QuickBooks."
            )
        _cache_qbo["compte"] = str(acc["Id"])
    return _cache_qbo["compte"]


async def code_taxe_report(qbo) -> str:
    """Code de taxe « hors champ / exonéré » de la compagnie QB."""
    if settings.qbo_report_tax_code:
        return str(settings.qbo_report_tax_code)
    if "taxe" in _cache_qbo:
        return _cache_qbo["taxe"]
    rows = await qbo.query("SELECT * FROM TaxCode MAXRESULTS 200")
    actifs = [r for r in rows if r.get("Active", True) and r.get("Id")]
    for cle in _NOMS_TAXE_EXONEREE:
        for r in actifs:
            if cle in _sans_accents(str(r.get("Name") or "")):
                _cache_qbo["taxe"] = str(r["Id"])
                return _cache_qbo["taxe"]
    from app.integrations.quickbooks import QuickBooksError

    raise QuickBooksError(
        "Aucun code de taxe « Exonéré » ou « Hors champ » dans QuickBooks pour "
        "la ligne de solde reporté (déjà taxée sur la facture d'origine). "
        "Configure QBO_REPORT_TAX_CODE avec l'Id du bon code."
    )


async def ligne_qbo_report(qbo, it: FactureItem, montant: float) -> Dict[str, Any]:
    """Ligne d'Invoice QB d'un solde reporté : produit relié au compte de
    transit, code de taxe exonéré — jamais un revenu ni une taxe."""
    compte = await compte_transit_id(qbo)
    if "produit" not in _cache_qbo:
        produit = await qbo.ensure_item_sur_compte(
            name=settings.qbo_report_produit,
            account_id=compte,
            description="Solde impayé reporté d'une facture précédente",
        )
        _cache_qbo["produit"] = str(produit.get("Id") or "")
    taxe = await code_taxe_report(qbo)
    detail: Dict[str, Any] = {
        "Qty": 1,
        "UnitPrice": montant,
        "TaxCodeRef": {"value": taxe},
    }
    if _cache_qbo["produit"]:
        detail["ItemRef"] = {"value": _cache_qbo["produit"]}
    return {
        "DetailType": "SalesItemLineDetail",
        "Amount": montant,
        "Description": it.description,
        "SalesItemLineDetail": detail,
        # Marqueur interne retiré avant l'envoi : exclu de la base taxable
        # du calcul manuel des taxes.
        "_kratos_report": True,
    }


async def pousser_report_qbo(db: AsyncSession, rep: FactureReportSolde) -> bool:
    """Crée le Payment QB qui ferme le solde de l'Invoice d'origine, déposé
    dans le compte de transit. True si fait (ou déjà fait), False si
    l'Invoice d'origine n'est pas encore dans QB. Lève sur refus de QB."""
    from app.integrations.quickbooks import QuickBooksError, get_qbo

    if rep.statut == REPORT_ANNULE or rep.qbo_payment_id:
        return True
    origine = await db.get(Facture, rep.origine_facture_id)
    if origine is None or not origine.qbo_invoice_id:
        return False
    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        return False
    inv_id = str(origine.qbo_invoice_id)
    data = await qbo.get_invoice(inv_id)
    inv = data.get("Invoice") or data
    montant = round(float(rep.montant or 0), 2)
    solde_qb = round(float(inv.get("Balance") or 0), 2)
    if solde_qb + 0.009 < montant:
        raise QuickBooksError(
            f"Le solde de la facture {origine.reference} dans QuickBooks "
            f"({_money(solde_qb)}) est plus petit que le montant reporté "
            f"({_money(montant)}) : un paiement y manque dans Kratos."
        )
    cref = str((inv.get("CustomerRef") or {}).get("value") or "")
    if not cref:
        raise QuickBooksError("Client QuickBooks de la facture introuvable.")
    payload: Dict[str, Any] = {
        "TotalAmt": montant,
        "CustomerRef": {"value": cref},
        "DepositToAccountRef": {"value": await compte_transit_id(qbo)},
        "TxnDate": datetime.now(timezone.utc).date().isoformat(),
        "PaymentRefNum": f"REPORT {origine.reference}"[:21],
        "PrivateNote": (
            f"Kratos : solde de la facture {origine.reference} reporté sur "
            f"la prochaine facture du client (report #{rep.id})."
        ),
        "Line": [
            {
                "Amount": montant,
                "LinkedTxn": [{"TxnId": inv_id, "TxnType": "Invoice"}],
            }
        ],
    }
    res = await qbo.create_payment(payload)
    pay = res.get("Payment") or res
    rep.qbo_payment_id = str(pay.get("Id") or "") or None
    rep.qbo_error = None
    await db.flush()
    return True


async def pousser_reports_facture(facture_id: int) -> None:
    """Arrière-plan, après le push de la facture d'origine (même verrou :
    l'Invoice QB existe alors). Un refus reste sur le report ; le filet
    horaire réessaie."""
    from app.db.session import AsyncSessionLocal
    from app.services.qbo_auto_sync import verrou_facture

    try:
        async with verrou_facture(facture_id):
            async with AsyncSessionLocal() as db:
                reps = (
                    await db.execute(
                        select(FactureReportSolde).where(
                            FactureReportSolde.origine_facture_id == facture_id,
                            FactureReportSolde.statut != REPORT_ANNULE,
                            FactureReportSolde.qbo_payment_id.is_(None),
                        )
                    )
                ).scalars().all()
                for rep in reps:
                    try:
                        await pousser_report_qbo(db, rep)
                    except Exception as exc:  # noqa: BLE001
                        rep.qbo_error = str(exc)[:2000]
                        log.error(
                            "Report %s (facture %s) non fermé dans QB : %s",
                            rep.id, facture_id, exc,
                        )
                await db.commit()
    except Exception:  # noqa: BLE001
        log.warning("pousser_reports_facture %s", facture_id, exc_info=True)


def lancer_push_reports(facture_id: int) -> None:
    import asyncio

    from app.services.facture_qbo import quickbooks_branche

    if not quickbooks_branche():
        return
    try:
        asyncio.create_task(pousser_reports_facture(int(facture_id)))
    except RuntimeError:
        return


async def filet_reports_qbo() -> Dict[str, int]:
    """Filet horaire : reports dont le Payment QB manque (facture d'origine
    arrivée dans QB depuis, refus passager)."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        fids = sorted(
            {
                int(r[0])
                for r in (
                    await db.execute(
                        select(FactureReportSolde.origine_facture_id)
                        .join(Facture, Facture.id == FactureReportSolde.origine_facture_id)
                        .where(
                            FactureReportSolde.statut != REPORT_ANNULE,
                            FactureReportSolde.qbo_payment_id.is_(None),
                            Facture.qbo_invoice_id.is_not(None),
                        )
                    )
                ).all()
            }
        )
    for fid in fids[:50]:
        await pousser_reports_facture(fid)
    return {"factures": len(fids)}


async def ids_paiements_qb_des_reports(db: AsyncSession) -> set[str]:
    """Payments QB des reports : le rapatriement QB → Kratos ne doit pas
    les recopier comme de vrais paiements (ce n'est pas de l'argent reçu)."""
    return {
        str(r[0])
        for r in (
            await db.execute(
                select(FactureReportSolde.qbo_payment_id).where(
                    FactureReportSolde.qbo_payment_id.is_not(None)
                )
            )
        ).all()
    }


def lire(rep: FactureReportSolde, refs: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    refs = refs or {}
    return {
        "id": rep.id,
        "client_id": rep.client_id,
        "origine_facture_id": rep.origine_facture_id,
        "origine_reference": refs.get(rep.origine_facture_id),
        "cible_facture_id": rep.cible_facture_id,
        "cible_reference": refs.get(rep.cible_facture_id) if rep.cible_facture_id else None,
        "cible_item_id": rep.cible_item_id,
        "montant": float(rep.montant or 0),
        "statut": rep.statut,
        "automatique": bool(rep.automatique),
        "qbo_payment_id": rep.qbo_payment_id,
        "qbo_error": rep.qbo_error,
        "created_at": rep.created_at.isoformat() if rep.created_at else None,
        "annule_le": rep.annule_le.isoformat() if rep.annule_le else None,
    }
