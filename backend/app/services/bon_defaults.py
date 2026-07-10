"""Resolution des valeurs par defaut cout / refacturation / marge des bons.

Source de verite unique : la ligne singleton ``construction_bon_defaults``
(id=1). ``get_bon_defaults`` retourne le triplet (cout horaire, taux refac
horaire, marge %) en retombant sur les valeurs historiques (35/55/10) si la
ligne est absente ou un champ NULL — jamais de plantage, jamais d'ecriture.

Utilise par :
  - le moteur de refacturation du bon (``bon_items.create_item``) comme filet
    quand une ligne d'heures arrive sans cout/refac ;
  - le cockpit (fallback cout horaire employe) ;
  - l'endpoint de reglage (via ``get_or_create_bon_defaults``).
"""

from __future__ import annotations

from typing import Tuple

from sqlalchemy import select

from app.models.construction_bon_defaults import (
    CONSTRUCTION_BON_DEFAULT_VALUES,
    CONSTRUCTION_BON_DEFAULTS_ID,
    ConstructionBonDefaults,
)


async def get_or_create_bon_defaults(db) -> ConstructionBonDefaults:
    """Recupere la ligne singleton (id=1), la cree avec les valeurs historiques
    si absente (idempotent — couvre un boot ou le seed n'a pas encore tourne).
    Reserve aux endpoints (ecriture) ; les lecteurs chauds utilisent
    ``get_bon_defaults`` (lecture seule)."""
    rec = (
        await db.execute(
            select(ConstructionBonDefaults).where(
                ConstructionBonDefaults.id == CONSTRUCTION_BON_DEFAULTS_ID
            )
        )
    ).scalar_one_or_none()
    if rec is None:
        rec = ConstructionBonDefaults(
            id=CONSTRUCTION_BON_DEFAULTS_ID,
            default_cost_rate=CONSTRUCTION_BON_DEFAULT_VALUES["default_cost_rate"],
            default_bill_rate=CONSTRUCTION_BON_DEFAULT_VALUES["default_bill_rate"],
            default_marge_pct=CONSTRUCTION_BON_DEFAULT_VALUES["default_marge_pct"],
        )
        db.add(rec)
        await db.flush()
        await db.refresh(rec)
    return rec


async def get_bon_defaults(db) -> Tuple[float, float, float]:
    """(cout horaire, taux refac horaire, marge %) — lecture seule.

    Retombe sur les valeurs historiques 35/55/10 si la ligne est absente ou un
    champ NULL. N'ecrit jamais (pas de get_or_create) : sur pour les chemins
    chauds (cockpit) et neutre pour un caller sans droit d'ecriture."""
    d = CONSTRUCTION_BON_DEFAULT_VALUES
    rec = (
        await db.execute(
            select(ConstructionBonDefaults).where(
                ConstructionBonDefaults.id == CONSTRUCTION_BON_DEFAULTS_ID
            )
        )
    ).scalar_one_or_none()
    if rec is None:
        return (
            float(d["default_cost_rate"]),
            float(d["default_bill_rate"]),
            float(d["default_marge_pct"]),
        )
    cost = (
        rec.default_cost_rate
        if rec.default_cost_rate is not None
        else d["default_cost_rate"]
    )
    bill = (
        rec.default_bill_rate
        if rec.default_bill_rate is not None
        else d["default_bill_rate"]
    )
    marge = (
        rec.default_marge_pct
        if rec.default_marge_pct is not None
        else d["default_marge_pct"]
    )
    return (float(cost), float(bill), float(marge))
