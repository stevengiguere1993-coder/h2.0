"""Calculs de rentabilité d'un contrat — purs et testables.

DEUX calculs totalement SÉPARÉS, chacun sur sa propre base (aucun ne
contamine l'autre) :

1. PROFIT RÉEL — base HT pure, ne touche jamais aux taxes.
   - Matériaux : convertis en HT (taxes récupérables via CTI/RTI → PAS un
     coût). Fournisseur NON inscrit : pas de taxe → montant déjà HT.
   - Main-d'œuvre : aucun ajustement (vrai coût, pas de taxe récupérable).
   - profit = revenu_HT − (matériaux_HT + main-d'œuvre)

2. TAXES À REMETTRE — base = montant réellement FACTURÉ (pas le contrat) :
   - perçue = facturé_HT × taux
   - récupérée (CTI/RTI) = achats_HT_taxés × taux
   - net = perçue − récupérée
   Se recalcule à chaque facture / avenant / rabais. N'entre JAMAIS dans
   le profit (sinon double comptage).
"""

from __future__ import annotations

from app.core.taxes import TPS_RATE, TVQ_RATE, ht_from_ttc  # noqa: F401


def actual_cost_ht(materials_ht: float, labour_cost: float) -> float:
    """Coût réel HORS TAXES = matériaux HT + main-d'œuvre (telle quelle).

    ``materials_ht`` est DÉJÀ hors taxes — on ne redivise jamais."""
    return round(float(materials_ht or 0) + float(labour_cost or 0), 2)


def actual_profit_ht(
    revenue_ht: float, materials_ht: float, labour_cost: float
) -> float:
    """Profit réel = revenu HT − coût réel HT.

    Ne dépend PAS du montant facturé ni des taxes : si une facture change,
    le profit ne bouge pas — seuls le revenu HT et les coûts engagés le font.
    """
    return round(
        float(revenue_ht or 0) - actual_cost_ht(materials_ht, labour_cost), 2
    )


def taxes_to_remit(
    facture_ht: float, recoverable_materials_ht: float
) -> dict[str, float]:
    """Taxes nettes à remettre au gouvernement.

    Base = montant FACTURÉ (factures émises, hors brouillons), PAS le
    contrat. ``recoverable_materials_ht`` = total HT des achats portant une
    taxe récupérable (fournisseurs inscrits uniquement).
    """
    fh = float(facture_ht or 0)
    mh = float(recoverable_materials_ht or 0)
    tps_percue = round(fh * TPS_RATE, 2)
    tvq_percue = round(fh * TVQ_RATE, 2)
    cti = round(mh * TPS_RATE, 2)   # TPS récupérée sur les achats
    rti = round(mh * TVQ_RATE, 2)   # TVQ récupérée sur les achats
    net_tps = round(tps_percue - cti, 2)
    net_tvq = round(tvq_percue - rti, 2)
    return {
        "facture_ht": round(fh, 2),
        "tps_percue": tps_percue,
        "tvq_percue": tvq_percue,
        "cti": cti,
        "rti": rti,
        "net_tps": net_tps,
        "net_tvq": net_tvq,
        "total": round(net_tps + net_tvq, 2),
    }
