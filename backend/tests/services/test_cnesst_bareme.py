"""Tests du taux CNESST global daté et de la prime appliquée au coût.

Steven (2026-10-14) : un taux global réglable dans Paramètres, une case
« Prime CNESST » sur la fiche employé (décochée = aucune prime) et un taux
personnalisé facultatif. Fonctions pures → objets factices, sans base.
"""

import os
import sys
from datetime import date
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.cnesst import (
    BaremeCnesst,
    PalierCnesst,
    bareme_depuis_config,
    config_cnesst,
    taux_cnesst,
)
from app.services.employe_rates import RatePeriod, resolve_real_cost

BAREME = BaremeCnesst(
    (
        PalierCnesst(date(2000, 1, 1), 0.0216),
        PalierCnesst(date(2027, 1, 1), 0.0205),
    )
)


def test_taux_au_suit_la_date_du_palier():
    assert BAREME.taux_au(date(2026, 12, 31)) == 0.0216
    assert BAREME.taux_au(date(2027, 1, 1)) == 0.0205
    assert BAREME.taux_au(date(2030, 6, 1)) == 0.0205
    # Avant le premier palier : le premier couvre le passé.
    assert BAREME.taux_au(date(1999, 1, 1)) == 0.0216


def test_bareme_vide_vaut_zero():
    assert BaremeCnesst().taux_au(date(2026, 1, 1)) == 0.0
    assert BaremeCnesst().taux_actuel == 0.0


def test_avec_palier_remplace_la_meme_date_et_trie():
    b = BAREME.avec_palier(date(2026, 7, 1), 0.03).avec_palier(date(2027, 1, 1), 0.019)
    assert [(p.depuis, p.taux) for p in b.paliers] == [
        (date(2000, 1, 1), 0.0216),
        (date(2026, 7, 1), 0.03),
        (date(2027, 1, 1), 0.019),
    ]
    assert b.sans_palier(date(2026, 7, 1)).taux_au(date(2026, 8, 1)) == 0.0216


def test_config_illisible_ignoree():
    b = bareme_depuis_config(
        {
            "paliers": [
                {"depuis": "2026-01-01", "taux": 0.02},
                {"depuis": "pas une date", "taux": 0.5},
                {"depuis": "2026-02-01", "taux": 7},
                {"taux": 0.1},
            ]
        }
    )
    assert [(p.depuis, p.taux) for p in b.paliers] == [(date(2026, 1, 1), 0.02)]
    assert bareme_depuis_config(None).paliers == ()


def test_taux_cnesst_case_perso_global():
    jour = date(2026, 5, 1)
    assert taux_cnesst(True, None, BAREME, jour) == 0.0216
    assert taux_cnesst(True, 0.05, BAREME, jour) == 0.05
    assert taux_cnesst(False, 0.05, BAREME, jour) == 0.0
    # Case pas encore posée (None) : cochée.
    assert taux_cnesst(None, None, BAREME, jour) == 0.0216
    # Sans barème : aucun taux global (calcul d'avant le réglage).
    assert taux_cnesst(True, None, None, jour) == 0.0


def test_config_cnesst_normalise():
    assert config_cnesst(SimpleNamespace(cnesst_actif=True, cnesst_rate=None)) == (True, None)
    assert config_cnesst(SimpleNamespace(cnesst_actif=None, cnesst_rate=0.02160000001)) == (True, 0.0216)
    assert config_cnesst(SimpleNamespace(cnesst_actif=False, cnesst_rate=None)) == (False, None)


def _emp(**kw):
    base = dict(
        hourly_rate=30.0,
        hourly_rate_ccq=None,
        cnesst_actif=True,
        cnesst_rate=None,
        ccq_rate=None,
        is_ccq=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_cout_reel_fiche_sans_historique():
    jour = date(2026, 5, 1)
    assert resolve_real_cost([], jour, _emp(), 35.0, cnesst=BAREME) == round(30 * 1.0216, 2)
    assert resolve_real_cost([], jour, _emp(cnesst_rate=0.05), 35.0, cnesst=BAREME) == 31.5
    assert resolve_real_cost([], jour, _emp(cnesst_actif=False), 35.0, cnesst=BAREME) == 30.0
    # Le taux global suit la date du punch.
    assert resolve_real_cost([], date(2027, 3, 1), _emp(), 35.0, cnesst=BAREME) == round(
        30 * 1.0205, 2
    )


def test_cout_reel_suit_le_palier_de_l_employe():
    periodes = [
        RatePeriod(
            effective_date=date(2026, 1, 1),
            hourly_rate=40.0,
            billing_rate=None,
            cnesst_rate=None,
            ccq_rate=0.0,
            is_ccq=False,
        ),
        RatePeriod(
            effective_date=date(2026, 6, 1),
            hourly_rate=50.0,
            billing_rate=None,
            cnesst_rate=None,
            ccq_rate=0.0,
            is_ccq=False,
            cnesst_actif=False,
        ),
    ]
    emp = _emp(hourly_rate=50.0, cnesst_actif=False)
    assert resolve_real_cost(periodes, date(2026, 3, 1), emp, 35.0, cnesst=BAREME) == round(
        40 * 1.0216, 2
    )
    assert resolve_real_cost(periodes, date(2026, 7, 1), emp, 35.0, cnesst=BAREME) == 50.0
