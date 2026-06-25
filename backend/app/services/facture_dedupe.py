"""Déduplication automatique des factures.

Cause des doublons : une facture créée dans Kratos (ex. « 116 ») est
poussée vers QuickBooks, puis RÉ-IMPORTÉE par le pull → une 2e facture
« QB-4310 » apparaît (avec qbo_doc_number = 116). C'est le MÊME document.

On regroupe les factures qui représentent sûrement la même facture :
  - même Invoice QB (qbo_invoice_id), OU
  - même NUMÉRO effectif (référence réelle vs qbo_doc_number) ET même total.

On garde la facture « réelle » (référence non « QB-… », avec items /
paiements) et on lui recopie le lien QB de la copie supprimée. Idempotent ;
ne committe pas (l'appelant gère la transaction).
"""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import func, select, update as _update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.facture import Facture
from app.models.payment import Payment

log = logging.getLogger(__name__)


def _is_qb_ref(ref: str | None) -> bool:
    return (ref or "").strip().upper().startswith("QB-")


def _effective_number(f: Facture) -> str:
    """Numéro « parlant » de la facture : la référence si elle n'est pas une
    référence d'import « QB-… », sinon le n° de doc QB (DocNumber)."""
    ref = (f.reference or "").strip()
    if ref and not _is_qb_ref(ref):
        return ref.lower()
    return (f.qbo_doc_number or ref or "").strip().lower()


def _total(f: Facture) -> float:
    try:
        return round(float(f.total or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _keeper_score(f: Facture, pay_counts: dict[int, int]) -> tuple:
    """Plus haut = à conserver : on garde la facture au VRAI numéro (pas
    « QB-… »), avec le plus de paiements, puis la plus ancienne."""
    return (
        0 if _is_qb_ref(f.reference) else 1,   # vraie référence > import QB
        pay_counts.get(f.id, 0),
        1 if f.qbo_invoice_id else 0,
        -f.id,
    )


async def dedupe_factures(db: AsyncSession) -> int:
    """Supprime les factures en double (même facture QB ré-importée).
    Retourne le nombre supprimé."""
    factures = list((await db.execute(select(Facture))).scalars().all())
    if len(factures) < 2:
        return 0

    # Nombre de paiements par facture (pour le choix du gardé + transfert).
    pay_counts: dict[int, int] = {
        int(fid): int(n)
        for fid, n in (
            await db.execute(
                select(Payment.facture_id, func.count(Payment.id)).group_by(
                    Payment.facture_id
                )
            )
        ).all()
    }

    # Union-find par signaux SÛRS.
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    rep: dict[str, int] = {}

    def link(key: str, fid: int) -> None:
        if key in rep:
            union(rep[key], fid)
        else:
            rep[key] = fid
            find(fid)

    for f in factures:
        find(f.id)
        if f.qbo_invoice_id:
            link(f"inv:{f.qbo_invoice_id}", f.id)
        num = _effective_number(f)
        if num:
            link(f"num:{num}|{_total(f):.2f}", f.id)

    comps: dict[int, list[Facture]] = defaultdict(list)
    for f in factures:
        comps[find(f.id)].append(f)

    removed = 0
    for members in comps.values():
        if len(members) < 2:
            continue
        keeper = max(members, key=lambda f: _keeper_score(f, pay_counts))
        for f in members:
            if f.id == keeper.id:
                continue
            # Recopier le lien QB manquant sur le gardé.
            if not keeper.qbo_invoice_id and f.qbo_invoice_id:
                keeper.qbo_invoice_id = f.qbo_invoice_id
                keeper.qbo_doc_number = f.qbo_doc_number or keeper.qbo_doc_number
                keeper.qbo_sync_token = f.qbo_sync_token
            # Si le gardé n'a AUCUN paiement mais la copie en a, on les
            # transfère (évite de perdre l'info de paiement). Sinon on
            # supprime la copie avec ses paiements (cascade) — pas de
            # double comptage.
            if pay_counts.get(keeper.id, 0) == 0 and pay_counts.get(f.id, 0) > 0:
                await db.execute(
                    _update(Payment)
                    .where(Payment.facture_id == f.id)
                    .values(facture_id=keeper.id)
                )
                pay_counts[keeper.id] = pay_counts.get(f.id, 0)
            # Refléter l'état payé sur le gardé.
            if (f.status or "") == "paid" and (keeper.status or "") != "paid":
                keeper.status = "paid"
                keeper.paid_at = keeper.paid_at or f.paid_at
            await db.delete(f)
            removed += 1
    if removed:
        await db.flush()
        log.info("dedupe_factures: %d doublon(s) supprimé(s)", removed)
    return removed
