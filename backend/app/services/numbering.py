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

import re
from typing import Literal, Optional

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


def _ref_num(ref: Optional[str]) -> Optional[int]:
    """Numéro entier d'une référence (« 173 », « FA-173 »… → 173).
    None si la référence ne se termine pas par un nombre."""
    m = re.search(r"(\d+)\s*$", (ref or "").strip())
    return int(m.group(1)) if m else None


async def _recycle_deleted_number(
    db: AsyncSession,
    *,
    counter_column,
    deleted_reference: Optional[str],
    remaining_refs: list[Optional[str]],
) -> Optional[int]:
    """Recycle le numéro d'un document SUPPRIMÉ : recale le compteur sur
    (max des numéros restants + 1) pour que le prochain document reprenne
    le numéro libéré au lieu de continuer la séquence.

    Garde-fous :
    - jamais SOUS le numéro supprimé (l'historique QuickBooks peut être
      plus long que Kratos — on ne veut pas retomber sur un DocNumber
      déjà pris dans QB) ;
    - jamais AU-DESSUS du compteur courant (on recycle, on n'avance pas) ;
    - un trou « du milieu » reste un trou (seule la fin de séquence se
      recycle — supprimer la dernière facture 173 → la prochaine est 173).
    """
    deleted_num = _ref_num(deleted_reference)
    if deleted_num is None:
        return None
    max_num = 0
    for ref in remaining_refs:
        n = _ref_num(ref)
        if n is not None and n > max_num:
            max_num = n
    new_next = max(max_num + 1, deleted_num)
    row = await _ensure_row(db)
    current = int(
        (
            await db.execute(
                select(counter_column).where(NumberingCounter.id == 1)
            )
        ).scalar_one()
    )
    _ = row
    if new_next >= current:
        return None  # rien à recycler (suppression « du milieu »)
    await db.execute(
        update(NumberingCounter)
        .where(NumberingCounter.id == 1)
        .values({counter_column: new_next})
    )
    await db.flush()
    return new_next


async def resync_facture_counter(
    db: AsyncSession, deleted_reference: Optional[str]
) -> Optional[int]:
    """Après suppression d'une facture, recycle son numéro : supprimer la
    dernière facture « 173 » fait que la prochaine créée reprend 173."""
    from app.models.facture import Facture

    refs = list(
        (await db.execute(select(Facture.reference))).scalars().all()
    )
    return await _recycle_deleted_number(
        db,
        counter_column=NumberingCounter.next_facture_number,
        deleted_reference=deleted_reference,
        remaining_refs=refs,
    )


async def resync_soumission_counter(
    db: AsyncSession, deleted_reference: Optional[str]
) -> Optional[int]:
    """Même recyclage pour les soumissions supprimées."""
    from app.models.soumission import Soumission

    refs = list(
        (await db.execute(select(Soumission.reference))).scalars().all()
    )
    return await _recycle_deleted_number(
        db,
        counter_column=NumberingCounter.next_soumission_number,
        deleted_reference=deleted_reference,
        remaining_refs=refs,
    )


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
