"""Tests du calcul de rentabilité HORS TAXES d'un contrat.

L'entreprise étant inscrite à la TPS/TVQ, les taxes payées sur les
achats sont récupérables (CTI/RTI) et ne comptent PAS dans le coût réel.
Toutes les comparaisons se font HT.
"""

from app.core.taxes import TAX_FACTOR, ht_from_ttc
from app.core.finance_math import (
    actual_cost_ht,
    actual_profit_ht,
    net_taxes_to_remit,
)


# Valeurs de référence fournies par le métier (capture du projet réel).
MATERIAUX_TTC = 23920.89
MAIN_DOEUVRE = 3869.21
REVENU_HT = 26190.58
TPS_PERCUE = 1309.53
TVQ_PERCUE = 2612.51


def test_tax_factor_is_quebec_combined_rate():
    assert TAX_FACTOR == 1.14975


def test_materiaux_converted_to_ht():
    # 23 920,89 / 1.14975 ≈ 20 805,30 $
    assert abs(ht_from_ttc(MATERIAUX_TTC) - 20805.30) <= 0.05


def test_cout_reel_ht():
    # Matériaux HT + main-d'œuvre (non convertie) ≈ 24 674,51 $
    assert abs(actual_cost_ht(MATERIAUX_TTC, MAIN_DOEUVRE) - 24674.51) <= 0.05


def test_profit_reel_est_positif():
    # Le bug affichait −420,32 $ ; le profit réel attendu est +1 516,07 $.
    profit = actual_profit_ht(REVENU_HT, MATERIAUX_TTC, MAIN_DOEUVRE)
    assert abs(profit - 1516.07) <= 0.05
    assert profit > 0


def test_pct_consomme_sous_100():
    cost_ht = actual_cost_ht(MATERIAUX_TTC, MAIN_DOEUVRE)
    pct = cost_ht / REVENU_HT * 100
    # ~94 % consommé (et non 102 %).
    assert abs(pct - 94.0) <= 1.0
    assert pct < 100


def test_main_doeuvre_non_convertie():
    # Sans matériaux, le coût réel HT == main-d'œuvre telle quelle.
    assert actual_cost_ht(0, MAIN_DOEUVRE) == round(MAIN_DOEUVRE, 2)


def test_net_taxes_a_remettre():
    net = net_taxes_to_remit(TPS_PERCUE, TVQ_PERCUE, MATERIAUX_TTC)
    assert abs(net["net_tps"] - 269.26) <= 0.05
    assert abs(net["net_tvq"] - 537.18) <= 0.05
    assert abs(net["total"] - 806.44) <= 0.05
