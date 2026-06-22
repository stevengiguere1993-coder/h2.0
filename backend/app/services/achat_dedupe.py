"""Déduplication automatique des achats.

Cause des doublons : un achat saisi dans Kratos est poussé vers QB puis
RÉ-IMPORTÉ par un pull → 2e achat identique. Objectif : chaque facture
fournisseur n'existe QU'UNE fois dans Kratos (et une fois dans QB).

Cette dédup est appelée AUTOMATIQUEMENT à la fin de chaque synchro QB
(`pull_new_bills_from_qbo`, `pull_costs`) — pas de bouton manuel. Elle est
sûre : elle ne regroupe que des achats certainement identiques.
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
    facturé / avec pièce jointe / paiement QB, sinon le plus ancien."""
    return (
        1 if a.facture_item_id is not None else 0,
        1 if a.invoiced_at is not None else 0,
        1 if a.has_receipt_image else 0,
        1 if a.qbo_bill_payment_id else 0,
        -a.id,  # tie-break : garder le plus ancien (id min)
    )


async def dedupe_achats(db: AsyncSession) -> int:
    """Supprime les achats en double, en conservant le plus complet.

    Deux clés de regroupement, toutes deux SÛRES :
      1. Même transaction QuickBooks — un Id présent dans ``qbo_bill_id``
         OU ``qbo_purchase_id`` de plusieurs achats (un achat poussé stocke
         l'Id de la Purchase dans qbo_bill_id, pas qbo_purchase_id).
      2. Même (fournisseur, n° de facture fournisseur) — un n° de facture
         identifie un seul document fournisseur.

    Retourne le nombre d'achats supprimés. Ne committe pas (l'appelant
    gère la transaction).
    """
    achats = list((await db.execute(select(Achat))).scalars().all())

    grouped_ids: set[int] = set()
    groups: list[list[Achat]] = []

    # 1) Même transaction QB (cross-champ qbo_bill_id / qbo_purchase_id).
    by_qb: dict[str, dict[int, Achat]] = defaultdict(dict)
    for a in achats:
        for qid in (a.qbo_bill_id, a.qbo_purchase_id):
            if qid:
                by_qb[str(qid)][a.id] = a
    for members in by_qb.values():
        if len(members) > 1:
            groups.append(list(members.values()))
            grouped_ids.update(members.keys())

    # 2) Même (fournisseur, n° facture fournisseur) pour le reste.
    by_inv: dict[tuple, dict[int, Achat]] = defaultdict(dict)
    for a in achats:
        if a.id in grouped_ids:
            continue
        inv = (a.supplier_invoice_number or "").strip().lower()
        if inv and a.fournisseur_id:
            by_inv[(a.fournisseur_id, inv)][a.id] = a
    for members in by_inv.values():
        if len(members) > 1:
            groups.append(list(members.values()))

    removed = 0
    for members in groups:
        keeper = max(members, key=_keeper_score)
        for a in members:
            if a.id == keeper.id:
                continue
            # Conserver le LIEN QB sur l'achat gardé : si le doublon
            # supprimé portait l'Id QB (Bill/Purchase/paiement) et pas le
            # gardé, on le recopie → la case « QB » reste cochée et le
            # re-pull ne recréera pas l'achat.
            if not keeper.qbo_bill_id and a.qbo_bill_id:
                keeper.qbo_bill_id = a.qbo_bill_id
                keeper.qbo_sync_token = a.qbo_sync_token
                keeper.qbo_doc_number = a.qbo_doc_number or keeper.qbo_doc_number
            if not keeper.qbo_purchase_id and a.qbo_purchase_id:
                keeper.qbo_purchase_id = a.qbo_purchase_id
            if not keeper.qbo_bill_payment_id and a.qbo_bill_payment_id:
                keeper.qbo_bill_payment_id = a.qbo_bill_payment_id
            await db.delete(a)
            removed += 1
    if removed:
        await db.flush()
        log.info("dedupe_achats: %d doublon(s) supprimé(s)", removed)
    return removed
