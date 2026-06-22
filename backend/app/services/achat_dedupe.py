"""Déduplication automatique des achats.

Cause des doublons : un achat saisi dans Kratos est poussé vers QB puis
RÉ-IMPORTÉ par un pull → 2e achat identique. Cas vu en prod : un achat
« à payer » (Sur compte) part en Bill QB ; une fois payé on lui met le
mode réel (Chèque) ; le pull QB ré-importe une version « Sur compte »
SANS fournisseur ni description → 2 lignes, même n° de référence, même
montant, mais ce n'est qu'UN document.

Cette dédup est appelée AUTOMATIQUEMENT à la fin de chaque synchro QB
(`pull_new_bills_from_qbo`, `pull_costs`) — pas de bouton manuel. Elle ne
regroupe que des achats reliés par un signal FORT (même transaction QB,
même n° de facture fournisseur, ou même référence + même montant TTC), et
l'achat conservé hérite du mode de paiement RÉEL (jamais « sur compte »
quand un paiement a été fait).
"""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.achat import Achat


log = logging.getLogger(__name__)


def _keeper_score(a: Achat) -> tuple:
    """Plus haut = plus « riche » → à conserver. On garde l'achat
    facturé / le plus complet (fournisseur, description, ventilation des
    taxes), à défaut le plus ancien."""
    return (
        1 if a.facture_item_id is not None else 0,
        1 if a.invoiced_at is not None else 0,
        1 if a.fournisseur_id is not None else 0,
        1 if a.sous_traitant_id is not None else 0,
        1 if (a.description or "").strip() else 0,
        1 if float(a.amount_taxes or 0) > 0 else 0,  # vrai split HT/taxes
        1 if a.project_id is not None else 0,
        1 if a.has_receipt_image else 0,
        1 if a.qbo_bill_payment_id else 0,
        -a.id,  # tie-break : garder le plus ancien (id min)
    )


def _ttc(a: Achat) -> float:
    return round(float(a.amount or 0) + float(a.amount_taxes or 0), 2)


def _tokens(a: Achat) -> set[str]:
    """Identifiants « parlants » de l'achat (référence interne, n° de
    facture fournisseur, n° de doc QB), normalisés."""
    out: set[str] = set()
    for v in (a.reference, a.supplier_invoice_number, a.qbo_doc_number):
        t = (v or "").strip().lower()
        if t:
            out.add(t)
    return out


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _merge_into_keeper(keeper: Achat, other: Achat) -> None:
    """Recopie sur l'achat conservé les infos présentes sur le doublon
    supprimé mais absentes du gardé (lien QB, fournisseur, projet,
    description…), et reflète l'état de paiement le PLUS avancé — avec le
    mode de paiement RÉEL, jamais « sur compte » si un paiement a eu lieu."""
    # Lien QB : ne jamais perdre la transaction QuickBooks rattachée.
    if not keeper.qbo_bill_id and other.qbo_bill_id:
        keeper.qbo_bill_id = other.qbo_bill_id
        keeper.qbo_sync_token = other.qbo_sync_token
        keeper.qbo_doc_number = other.qbo_doc_number or keeper.qbo_doc_number
    if not keeper.qbo_purchase_id and other.qbo_purchase_id:
        keeper.qbo_purchase_id = other.qbo_purchase_id
    if not keeper.qbo_bill_payment_id and other.qbo_bill_payment_id:
        keeper.qbo_bill_payment_id = other.qbo_bill_payment_id
    # Champs descriptifs : compléter ce qui manque sur le gardé.
    if keeper.fournisseur_id is None and other.fournisseur_id is not None:
        keeper.fournisseur_id = other.fournisseur_id
    if keeper.sous_traitant_id is None and other.sous_traitant_id is not None:
        keeper.sous_traitant_id = other.sous_traitant_id
    if keeper.project_id is None and other.project_id is not None:
        keeper.project_id = other.project_id
    if not (keeper.description or "").strip() and (other.description or "").strip():
        keeper.description = other.description
    if not (keeper.supplier_invoice_number or "").strip() and (
        other.supplier_invoice_number or ""
    ).strip():
        keeper.supplier_invoice_number = other.supplier_invoice_number
    if keeper.invoice_date is None and other.invoice_date is not None:
        keeper.invoice_date = other.invoice_date
    if not (keeper.receipt_url or "").strip() and (other.receipt_url or "").strip():
        keeper.receipt_url = other.receipt_url
    # État de paiement : on garde le plus avancé. Si l'un des deux porte un
    # mode de paiement RÉEL (pas « sur compte »), c'est lui qui fait foi
    # (la facture a fini par être payée par chèque / carte).
    if other.status == "paid" and keeper.status != "paid":
        keeper.status = "paid"
    if keeper.paid_at is None and other.paid_at is not None:
        keeper.paid_at = other.paid_at
    other_pm = (other.payment_method or "").strip()
    keeper_pm = (keeper.payment_method or "").strip()
    if other_pm and other_pm != "bill_to_pay" and (
        not keeper_pm or keeper_pm == "bill_to_pay"
    ):
        keeper.payment_method = other.payment_method


async def dedupe_achats(db: AsyncSession) -> int:
    """Supprime les achats en double, en conservant le plus complet.

    Trois signaux de regroupement, tous SÛRS (fusionnés par union-find,
    donc transitifs) :
      1. Même transaction QuickBooks — un Id présent dans ``qbo_bill_id``
         OU ``qbo_purchase_id`` (un achat poussé stocke l'Id de la Purchase
         dans qbo_bill_id, pas qbo_purchase_id).
      2. Même (fournisseur, n° de facture fournisseur).
      3. Même RÉFÉRENCE (reference / n° facture fournisseur / n° doc QB) ET
         même montant TTC — couvre le doublon « Sur compte » ré-importé
         sans fournisseur : la réf et le montant suffisent à l'identifier.

    Retourne le nombre d'achats supprimés. Ne committe pas (l'appelant
    gère la transaction).
    """
    achats = list((await db.execute(select(Achat))).scalars().all())

    uf = _UnionFind()
    # Index : clé de signal → premier achat vu portant cette clé. On unionne
    # chaque nouvel achat avec ce représentant.
    rep: dict[str, int] = {}

    def link(key: str, aid: int) -> None:
        if key in rep:
            uf.union(rep[key], aid)
        else:
            rep[key] = aid
            uf.find(aid)

    for a in achats:
        uf.find(a.id)
        # 1) Transaction QB (cross-champ).
        for qid in (a.qbo_bill_id, a.qbo_purchase_id):
            if qid:
                link(f"qb:{qid}", a.id)
        # 2) Fournisseur + n° facture fournisseur.
        inv = (a.supplier_invoice_number or "").strip().lower()
        if inv and a.fournisseur_id:
            link(f"inv:{a.fournisseur_id}:{inv}", a.id)
        # 3) Référence + montant TTC (identique = même document).
        ttc = _ttc(a)
        if ttc > 0:
            for tok in _tokens(a):
                link(f"tok:{tok}|{ttc:.2f}", a.id)

    # Reconstruit les groupes à partir des composantes connexes.
    comps: dict[int, list[Achat]] = defaultdict(list)
    for a in achats:
        comps[uf.find(a.id)].append(a)

    removed = 0
    for members in comps.values():
        if len(members) < 2:
            continue
        keeper = max(members, key=_keeper_score)
        for a in members:
            if a.id == keeper.id:
                continue
            _merge_into_keeper(keeper, a)
            await db.delete(a)
            removed += 1
    if removed:
        await db.flush()
        log.info("dedupe_achats: %d doublon(s) supprimé(s)", removed)
    return removed
