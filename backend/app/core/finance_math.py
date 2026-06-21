"""Calculs de rentabilité d'un contrat — purs et testables.

Règle d'or : TOUTES les comparaisons de rentabilité se font HORS TAXES.
- Matériaux : stockés TTC → convertis en HT (taxes récupérables via
  CTI/RTI, donc PAS un coût réel).
- Main-d'œuvre : aucun ajustement (les salaires ne portent pas de taxe
  récupérable → vrai coût).
"""

from __future__ import annotations

from app.core.taxes import TPS_RATE, TVQ_RATE, ht_from_ttc


def actual_cost_ht(materials_ttc: float, labour_cost: float) -> float:
    """Coût réel HORS TAXES = matériaux convertis en HT + main-d'œuvre."""
    return round(ht_from_ttc(materials_ttc) + float(labour_cost or 0), 2)


def actual_profit_ht(
    revenue_ht: float, materials_ttc: float, labour_cost: float
) -> float:
    """Profit réel = revenu HT − coût réel HT."""
    return round(float(revenue_ht or 0) - actual_cost_ht(materials_ttc, labour_cost), 2)


def net_taxes_to_remit(
    tps_collected: float, tvq_collected: float, materials_ttc: float
) -> dict[str, float]:
    """Taxes nettes à remettre au gouvernement = taxes perçues sur les
    ventes − taxes payées sur les achats (CTI/RTI).

    Les taxes payées sont dérivées du matériel HT (matériaux supposés
    pleinement taxés). Retourne le détail TPS/TVQ + le total.
    """
    materials_ht = ht_from_ttc(materials_ttc)
    tps_paid = round(materials_ht * TPS_RATE, 2)
    tvq_paid = round(materials_ht * TVQ_RATE, 2)
    net_tps = round(float(tps_collected or 0) - tps_paid, 2)
    net_tvq = round(float(tvq_collected or 0) - tvq_paid, 2)
    return {
        "tps_paid": tps_paid,
        "tvq_paid": tvq_paid,
        "net_tps": net_tps,
        "net_tvq": net_tvq,
        "total": round(net_tps + net_tvq, 2),
    }
