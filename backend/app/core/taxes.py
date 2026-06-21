"""Taux de taxes québécoises (TPS/TVQ) — source unique de vérité.

L'entreprise est INSCRITE à la TPS/TVQ : les taxes payées sur les achats
(matériaux, sous-traitants) sont récupérées via les crédits d'intrants
(CTI/RTI) et ne sont donc PAS un coût réel. Toutes les comparaisons de
rentabilité se font HORS TAXES (HT), des deux côtés.

Centraliser ici le facteur de taxe évite de le coder en dur dans
plusieurs fichiers (KPI projet, items de facture, items de soumission…).
"""

from __future__ import annotations

#: TPS fédérale — 5 %.
TPS_RATE = 0.05
#: TVQ Québec — 9,975 %.
TVQ_RATE = 0.09975
#: Facteur TTC quand les DEUX taxes s'appliquent : 1 + TPS + TVQ = 1.14975.
#: Diviser un montant taxes incluses par ce facteur donne le montant HT.
TAX_FACTOR = round(1.0 + TPS_RATE + TVQ_RATE, 5)  # = 1.14975


def ht_from_ttc(amount_ttc: float) -> float:
    """Convertit un montant TAXES INCLUSES en montant HORS TAXES.

    Suppose que les deux taxes (TPS + TVQ) s'appliquent — cas normal
    d'un achat de matériaux au Québec.
    """
    if not amount_ttc:
        return 0.0
    return round(float(amount_ttc) / TAX_FACTOR, 2)
