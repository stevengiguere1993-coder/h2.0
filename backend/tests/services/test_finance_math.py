"""Tests du calcul de rentabilité HT et des taxes à remettre.

L'entreprise étant inscrite à la TPS/TVQ, les taxes payées sur les achats
sont récupérables (CTI/RTI) → PAS un coût. Deux calculs SÉPARÉS :
  - profit réel : base HT pure, indépendant du montant facturé.
  - taxes à remettre : base = montant FACTURÉ (pas le contrat).
"""

from app.core.taxes import TAX_FACTOR, ht_from_ttc
from app.core.finance_math import (
    actual_cost_ht,
    actual_profit_ht,
    taxes_to_remit,
)


# Valeurs de référence fournies par le métier.
MATERIAUX_TTC = 23920.89
MATERIAUX_HT = ht_from_ttc(MATERIAUX_TTC)  # ≈ 20 805,30
MAIN_DOEUVRE = 3869.21
REVENU_HT = 26190.58
FACTURE_HT = 25618.27  # montant réellement facturé (≠ contrat)


def test_tax_factor_is_quebec_combined_rate():
    assert TAX_FACTOR == 1.14975


def test_materiaux_converted_to_ht():
    assert abs(MATERIAUX_HT - 20805.30) <= 0.05


def test_cout_reel_ht():
    assert abs(actual_cost_ht(MATERIAUX_HT, MAIN_DOEUVRE) - 24674.51) <= 0.05


def test_profit_reel_est_positif():
    # Le bug affichait −420,32 $ ; le profit réel attendu est +1 516,07 $.
    profit = actual_profit_ht(REVENU_HT, MATERIAUX_HT, MAIN_DOEUVRE)
    assert abs(profit - 1516.07) <= 0.05
    assert profit > 0


def test_pct_consomme_sous_100():
    cost_ht = actual_cost_ht(MATERIAUX_HT, MAIN_DOEUVRE)
    pct = cost_ht / REVENU_HT * 100
    assert abs(pct - 94.0) <= 1.0
    assert pct < 100


def test_main_doeuvre_non_convertie():
    assert actual_cost_ht(0, MAIN_DOEUVRE) == round(MAIN_DOEUVRE, 2)


def test_net_taxes_a_remettre_sur_facture():
    # Base FACTURÉE 25 618,27 $ HT (≠ contrat) → net 720,73 $.
    tx = taxes_to_remit(FACTURE_HT, MATERIAUX_HT)
    assert abs(tx["tps_percue"] - 1280.91) <= 0.05
    assert abs(tx["tvq_percue"] - 2555.42) <= 0.05
    assert abs(tx["cti"] - 1040.27) <= 0.05
    assert abs(tx["rti"] - 2075.33) <= 0.05
    assert abs(tx["net_tps"] - 240.64) <= 0.05
    assert abs(tx["net_tvq"] - 480.09) <= 0.05
    assert abs(tx["total"] - 720.73) <= 0.05


def test_profit_independant_du_facture_mais_taxes_non():
    """Un avenant qui change le FACTURÉ ne doit PAS bouger le profit réel,
    mais DOIT changer le net de taxes à remettre."""
    profit_avant = actual_profit_ht(REVENU_HT, MATERIAUX_HT, MAIN_DOEUVRE)
    net_avant = taxes_to_remit(FACTURE_HT, MATERIAUX_HT)["total"]

    # Avenant : on facture 3 000 $ HT de plus (le revenu HT du contrat et
    # les coûts engagés, eux, ne changent pas).
    facture_apres = FACTURE_HT + 3000.0
    profit_apres = actual_profit_ht(REVENU_HT, MATERIAUX_HT, MAIN_DOEUVRE)
    net_apres = taxes_to_remit(facture_apres, MATERIAUX_HT)["total"]

    assert profit_apres == profit_avant            # profit inchangé
    assert net_apres > net_avant                   # net de taxes augmente
    # +3 000 $ facturé → +3 000 × 14,975 % de taxes nettes perçues.
    assert abs((net_apres - net_avant) - 3000.0 * 0.14975) <= 0.05
