"""Tests du calcul de refacturation des achats (`_compute_billed_amount`).

Logique argent à fort enjeu : c'est elle qui décide combien on facture au
client pour un achat matériel ou une facture de sous-traitant (majoration
par défaut 10 %, coûtant volontaire, surcharge à l'import, ou règles de
contrat sous-traitant : markup %, taux horaire, forfait).

Fonction pure (accès par attributs) → on la teste avec des objets factices
(`SimpleNamespace`), sans modèle SQLAlchemy ni base de données.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.api.v1.endpoints.facture_import import _compute_billed_amount


def _achat(**kw):
    base = dict(
        id=1,
        amount=100.0,
        kind="materiel",
        sous_traitant_id=None,
        markup_percent=None,
        hours=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _contract(**kw):
    base = dict(
        billing_mode="markup_pct",
        markup_percent=None,
        flat_hourly_rate=None,
        lump_sum_amount=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── Achat matériel : majoration individuelle ──────────────────────────


def test_materiel_majoration_par_defaut_10pct():
    # markup_percent NULL = non saisi → 10 % par défaut.
    amount, label = _compute_billed_amount(
        _achat(amount=100, markup_percent=None), {}, {}
    )
    assert amount == 110.0
    assert "10" in label


def test_materiel_markup_zero_est_coutant():
    # 0 = coûtant volontaire (≠ NULL). On facture au prix coûtant.
    amount, label = _compute_billed_amount(
        _achat(amount=250, markup_percent=0), {}, {}
    )
    assert amount == 250.0
    assert label == "coûtant"


def test_materiel_markup_explicite():
    amount, label = _compute_billed_amount(
        _achat(amount=200, markup_percent=15), {}, {}
    )
    assert amount == 230.0
    assert "15" in label


def test_override_a_l_import_prioritaire_sur_achat():
    # La surcharge passée à l'import a priorité sur markup_percent de l'achat.
    ac = _achat(id=7, amount=100, markup_percent=10)
    amount, label = _compute_billed_amount(ac, {7: 25}, {})
    assert amount == 125.0
    assert "25" in label


def test_arrondi_deux_decimales():
    # 33.33 * 1.10 = 36.663 → arrondi à 36.66.
    amount, _ = _compute_billed_amount(
        _achat(amount=33.33, markup_percent=10), {}, {}
    )
    assert amount == 36.66


def test_amount_none_donne_zero():
    amount, _ = _compute_billed_amount(
        _achat(amount=None, markup_percent=10), {}, {}
    )
    assert amount == 0.0


# ── Sous-traitant avec contrat ────────────────────────────────────────


def test_sous_traitant_contrat_markup_pct():
    ac = _achat(amount=1000, kind="sub_invoice", sous_traitant_id=5)
    contracts = {5: _contract(billing_mode="markup_pct", markup_percent=12)}
    amount, label = _compute_billed_amount(ac, {}, contracts)
    assert amount == 1120.0
    assert "contrat" in label and "12" in label


def test_sous_traitant_contrat_taux_horaire():
    ac = _achat(amount=0, kind="sub_invoice", sous_traitant_id=5, hours=8)
    contracts = {5: _contract(billing_mode="flat_hourly", flat_hourly_rate=75)}
    amount, label = _compute_billed_amount(ac, {}, contracts)
    assert amount == 600.0
    assert "75" in label and "8" in label


def test_sous_traitant_contrat_forfait():
    ac = _achat(amount=999, kind="sub_invoice", sous_traitant_id=5)
    contracts = {5: _contract(billing_mode="lump_sum", lump_sum_amount=1500)}
    amount, label = _compute_billed_amount(ac, {}, contracts)
    assert amount == 1500.0
    assert label == "contrat forfait"


def test_sous_traitant_sans_contrat_retombe_sur_markup_defaut():
    # Facture de sous-traitant SANS contrat → comme un achat matériel :
    # majoration manuelle (NULL → 10 % par défaut).
    ac = _achat(
        amount=500, kind="sub_invoice", sous_traitant_id=9, markup_percent=None
    )
    amount, label = _compute_billed_amount(ac, {}, {})
    assert amount == 550.0
    assert "10" in label
