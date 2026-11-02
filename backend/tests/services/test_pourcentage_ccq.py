"""Part CCQ de la fiche employé (Steven, 2026-11-02).

« Si je mets 50 % CCQ sur un employé, on calcule 50 % des heures en CCQ et
l'autre 50 % hors décret » : le coût de chantier d'une heure devient un
mélange des deux coûts, quel que soit le régime du punch. Fonctions pures
→ objets factices, sans base.
"""

import os
import sys
from datetime import date
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.cnesst import BaremeCnesst, PalierCnesst
from app.services.employe_rates import (
    RatePeriod,
    pourcentage_ccq,
    resolve_base_rate,
    resolve_real_cost,
)

BAREME = BaremeCnesst((PalierCnesst(date(2000, 1, 1), 0.02),))
JOUR = date(2026, 11, 2)


def _emp(**kw):
    base = dict(
        hourly_rate=30.0,
        hourly_rate_ccq=40.0,
        is_ccq=False,
        ccq_rate=0.25,
        cnesst_actif=True,
        cnesst_rate=None,
        pourcentage_ccq=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


HD = round(30 * 1.02, 2)  # 30,60
CCQ = round(40 * (1 + 0.02 + 0.25), 2)  # 50,80


def test_sans_pourcentage_le_cout_suit_le_regime_du_punch():
    emp = _emp()
    assert resolve_real_cost([], JOUR, emp, 35.0, regime="hors_decret", cnesst=BAREME) == HD
    assert resolve_real_cost([], JOUR, emp, 35.0, regime="ccq", cnesst=BAREME) == CCQ


def test_cinquante_pourcent_melange_les_deux_couts():
    emp = _emp(pourcentage_ccq=50)
    attendu = round(0.5 * CCQ + 0.5 * HD, 2)
    for regime in (None, "hors_decret", "ccq"):
        assert resolve_real_cost([], JOUR, emp, 35.0, regime=regime, cnesst=BAREME) == attendu


def test_bornes_zero_et_cent():
    assert resolve_real_cost([], JOUR, _emp(pourcentage_ccq=0), 35.0, regime="ccq", cnesst=BAREME) == HD
    assert resolve_real_cost([], JOUR, _emp(pourcentage_ccq=100), 35.0, regime="hors_decret", cnesst=BAREME) == CCQ
    assert pourcentage_ccq(_emp(pourcentage_ccq=150)) == 1.0
    assert pourcentage_ccq(_emp()) is None
    assert pourcentage_ccq(None) is None


def test_pourcentage_avec_historique_de_taux():
    periodes = [
        RatePeriod(
            effective_date=date(2026, 1, 1),
            hourly_rate=20.0,
            billing_rate=None,
            cnesst_rate=None,
            ccq_rate=0.2,
            is_ccq=False,
            hourly_rate_ccq=30.0,
        )
    ]
    emp = _emp(pourcentage_ccq=25)
    hd = round(20 * 1.02, 2)
    ccq = round(30 * 1.22, 2)
    assert resolve_real_cost(periodes, JOUR, emp, 35.0, cnesst=BAREME) == round(
        0.25 * ccq + 0.75 * hd, 2
    )


def test_la_paie_ne_change_pas():
    emp = _emp(pourcentage_ccq=50)
    assert resolve_base_rate([], JOUR, emp, "hors_decret") == 30.0
    assert resolve_base_rate([], JOUR, emp, "ccq") == 40.0
