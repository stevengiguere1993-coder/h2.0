"""Atomic sequential numbering for factures + soumissions.

Lit-incrémente-renvoie un compteur unique par type pour générer la
prochaine référence. L'opération est faite via UPDATE … RETURNING
pour rester correcte en cas d'accès concurrent (deux managers qui
créent une facture en même temps).

Utilisation :
    ref = await next_facture_number(db)  # ex. "97"
    ref = await next_soumission_number(db)  # ex. "1011"

Les valeurs sont écrites brutes, sans préfixe — on s'aligne sur la
convention QuickBooks (DocNumber = "97", "98"…). Si un préfixe est
souhaité plus tard, on l'ajoute à la lecture.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.numbering_counter import NumberingCounter


async def _ensure_row(db: AsyncSession) -> NumberingCounter:
    row = (
        await db.execute(select(NumberingCounter).where(NumberingCounter.id == 1))
    ).scalar_one_or_none()
    if row is None:
        await db.execute(
            insert(NumberingCounter).values(
                id=1, next_facture_number=1, next_soumission_number=1
            )
        )
        await db.flush()
        row = (
            await db.execute(
                select(NumberingCounter).where(NumberingCounter.id == 1)
            )
        ).scalar_one()
    return row


async def _next(
    db: AsyncSession, kind: Literal["facture", "soumission", "po"]
) -> int:
    """Atomic read+increment via UPDATE … RETURNING.

    Sur Postgres on aurait pu utiliser une SEQUENCE, mais une table
    config-modifiable par l'admin (UI Paramètres) est plus pratique :
    elle permet de réinitialiser la valeur si on change d'année,
    si on bascule QB sandbox→prod, etc.
    """
    await _ensure_row(db)
    if kind == "facture":
        column = NumberingCounter.next_facture_number
    elif kind == "soumission":
        column = NumberingCounter.next_soumission_number
    else:
        column = NumberingCounter.next_po_number
    stmt = (
        update(NumberingCounter)
        .where(NumberingCounter.id == 1)
        .values({column: column + 1})
        .returning(column)
    )
    result = await db.execute(stmt)
    new_value = int(result.scalar_one())
    await db.flush()
    # new_value est le compteur APRÈS incrément. Le numéro qu'on vient
    # d'attribuer est new_value - 1.
    return new_value - 1


async def next_facture_number(db: AsyncSession) -> str:
    n = await _next(db, "facture")
    return str(n)


async def next_soumission_number(db: AsyncSession) -> str:
    n = await _next(db, "soumission")
    return str(n)


async def next_po_number(db: AsyncSession) -> str:
    """Numérotation PO format `PO-0027` (préfixe + zero-pad 4 chiffres).
    Cohérent avec ce que la cie utilise déjà (PO-0026, PO-0025, …)."""
    n = await _next(db, "po")
    return f"PO-{n:04d}"


async def resync_po_counter(db: AsyncSession) -> int:
    """Recale `next_po_number` sur (max numéro restant + 1).

    Appelé après suppression d'un PO pour recycler son numéro :
    si on supprime le dernier PO-0030, le prochain créé sera PO-0030.
    Si on supprime un PO « du milieu », le compteur reste à max+1
    et le numéro supprimé reste un trou (acceptable).
    """
    from app.models.purchase_order import PurchaseOrder

    rows = (
        await db.execute(select(PurchaseOrder.reference))
    ).scalars().all()
    max_num = 0
    for ref in rows:
        if not ref:
            continue
        # Format "PO-0027" → 27.
        tail = ref.split("-")[-1] if "-" in ref else ref
        try:
            n = int(tail)
        except ValueError:
            continue
        if n > max_num:
            max_num = n
    new_next = max_num + 1
    await _ensure_row(db)
    await db.execute(
        update(NumberingCounter)
        .where(NumberingCounter.id == 1)
        .values(next_po_number=new_next)
    )
    await db.flush()
    return new_next
