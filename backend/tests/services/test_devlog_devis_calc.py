"""Tests du moteur de calcul des soumissions « devis_dev »
(``app.services.devlog_devis_calc.compute_devis``).

Couvre :
* la RÉTROCOMPATIBILITÉ du chemin legacy (sans modules / sans
  ``manager_task``) — totaux agrégés inchangés ;
* l'INVARIANT « prix de ligne autonome » de la refonte 2026-06 : le prix
  client de chaque ligne ne dépend que de ses propres heures, et décocher
  un module ne change AUCUNE autre ligne (TEST D'ACCEPTATION) ;
* la gestion de projet en POURCENTAGE baked-in (stable, proportionnel au
  scope) ;
* la gratuité « module → module » bakée dans les fonctionnalités directes
  (jamais redistribuée sur les modules payants).

Stubs en lecture seule par attribut (comme les modèles SQLAlchemy).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.devlog_devis_calc import compute_devis


class _Soum:
    def __init__(self, **kw):
        self.marge_recurrente_pct = kw.get("marge_recurrente_pct", 50)
        self.marge_initiale_pct = kw.get("marge_initiale_pct", 50)
        self.commission_closer_pct = kw.get("commission_closer_pct", 10)
        self.taux_dev_horaire = kw.get("taux_dev_horaire", 75)
        self.taux_manager_horaire = kw.get("taux_manager_horaire", 80)
        self.heures_manager = kw.get("heures_manager", 0)


class _Item:
    def __init__(self, id, kind="feature", heures=None, cost_per_unit=0,
                 description="x", module_id=None):
        self.id = id
        self.item_kind = kind
        self.heures = heures
        self.cost_per_unit = cost_per_unit
        self.description = description
        self.module_id = module_id


class _Module:
    def __init__(self, id, selected=True, free_when_module_id=None, name="M"):
        self.id = id
        self.selected = selected
        self.free_when_module_id = free_when_module_id
        self.name = name


# --------------------------------------------------------------------------
# RÉTROCOMPATIBILITÉ (chemin legacy : sans modules / sans manager_task)
# --------------------------------------------------------------------------


def _legacy_inputs():
    soum = _Soum(heures_manager=10)
    items = [
        _Item(1, "feature", heures=40),
        _Item(2, "feature", heures=20),
        _Item(3, "fixed_cost", cost_per_unit=500),
        _Item(4, "recurring_cost", cost_per_unit=200),
    ]
    return soum, items


def test_legacy_two_args_unchanged():
    soum, items = _legacy_inputs()
    ini = compute_devis(soum, items)["initial"]
    assert ini["couts_dev"] == 4500.0
    assert ini["cout_manager"] == 800.0
    assert ini["frais_fixes_total"] == 500.0
    assert ini["base"] == 5800.0
    assert compute_devis(soum, items)["is_invalid"] is False


def test_legacy_modules_none_equals_two_args():
    soum, items = _legacy_inputs()
    assert compute_devis(soum, items) == compute_devis(soum, items, None)


def test_legacy_invariant_sum_client_equals_total():
    soum, items = _legacy_inputs()
    ini = compute_devis(soum, items)["initial"]
    s = sum(f["prix_client"] for f in ini["features_client"]) + sum(
        ff["prix_client"] for ff in ini["frais_fixes_client"])
    assert abs(round(s, 2) - ini["total_final"]) <= 0.01


def test_legacy_no_modules_field_empty():
    soum, items = _legacy_inputs()
    ini = compute_devis(soum, items)["initial"]
    assert ini["modules"] == []
    assert ini["manager_tasks"] == []


# --------------------------------------------------------------------------
# Gestion de projet en POURCENTAGE baked-in
# --------------------------------------------------------------------------


def test_manager_task_replaces_scalar():
    soum = _Soum(heures_manager=999)  # ignoré dès qu'une manager_task existe
    mods = [_Module(10, selected=True)]
    items = [
        _Item(1, "feature", heures=40, module_id=10),
        _Item(2, "feature", heures=10, module_id=10),
        _Item(3, "manager_task", heures=8, module_id=10),
        _Item(4, "manager_task", heures=2, module_id=10),
    ]
    ini = compute_devis(soum, items, mods)["initial"]
    assert ini["cout_manager"] == 800.0  # (8+2)*80
    assert ini["couts_dev"] == 3750.0


def test_manager_task_absent_falls_back_to_scalar():
    soum = _Soum(heures_manager=10)
    mods = [_Module(10, selected=True)]
    items = [_Item(1, "feature", heures=40, module_id=10)]
    ini = compute_devis(soum, items, mods)["initial"]
    assert ini["cout_manager"] == 800.0  # 10*80


def test_unselected_module_excluded():
    soum = _Soum(heures_manager=0)
    mods = [_Module(10, selected=True), _Module(20, selected=False)]
    items = [
        _Item(1, "feature", heures=40, module_id=10),
        _Item(2, "feature", heures=100, module_id=20),
        _Item(3, "manager_task", heures=5, module_id=10),
        _Item(4, "manager_task", heures=99, module_id=20),
        _Item(5, "feature", heures=10, module_id=None),
    ]
    ini = compute_devis(soum, items, mods)["initial"]
    # Module non sélectionné EXCLU : sa feature ne compte pas.
    assert ini["couts_dev"] == 3750.0  # (40+10)*75
    # Gestion de projet = % baked-in : coût manager global (8320) / dev
    # total de TOUTES les features (11250), appliqué au scope retenu
    # (3750) => 2773.33. (Proportionnel au scope, plus un pool fixe.)
    assert ini["cout_manager"] == 2773.33
    client_ids = [f["id"] for f in ini["features_client"]]
    assert 2 not in client_ids
    assert 5 in client_ids


def test_manager_baked_percent_stable_under_selection():
    """Décocher un module ne change pas le prix d'un autre module ; le
    total baisse exactement du prix affiché du module décoché."""
    soum = _Soum(heures_manager=0, taux_manager_horaire=80)
    mods = [_Module(1), _Module(2)]
    items = [
        _Item(1, "feature", heures=40, module_id=1),
        _Item(2, "feature", heures=20, module_id=2),
        _Item(3, "manager_task", heures=12, module_id=1),
    ]
    full = compute_devis(soum, items, mods)["initial"]
    part = compute_devis(
        soum, items, [_Module(1, selected=True), _Module(2, selected=False)]
    )["initial"]
    p1_full = next(m for m in full["modules"] if m["id"] == 1)["prix_client"]
    p1_part = next(m for m in part["modules"] if m["id"] == 1)["prix_client"]
    assert abs(p1_full - p1_part) <= 0.01
    p2 = next(m for m in full["modules"] if m["id"] == 2)["prix_client"]
    assert abs((full["total_final"] - p2) - part["total_final"]) <= 0.01


# --------------------------------------------------------------------------
# TEST D'ACCEPTATION — invariant prix de ligne (échoue sur l'ancien moteur)
# --------------------------------------------------------------------------


def _realistic_inputs():
    soum = _Soum(heures_manager=0)
    mods = [_Module(1, name="Calendrier"), _Module(2, name="Flotte"),
            _Module(3, name="PO"), _Module(4, name="Billets")]
    items = [
        _Item(101, "feature", heures=20, module_id=1),
        _Item(102, "feature", heures=14, module_id=1),
        _Item(201, "feature", heures=30, module_id=2),
        _Item(301, "feature", heures=18, module_id=3),
        _Item(401, "feature", heures=22, module_id=4),
        _Item(501, "feature", heures=8, module_id=None),
        _Item(502, "feature", heures=5, module_id=None),
        _Item(601, "fixed_cost", cost_per_unit=400),
        _Item(701, "manager_task", heures=10, module_id=1),
        _Item(702, "manager_task", heures=6, module_id=2),
    ]
    return soum, mods, items


def _module_price(ini, module_id):
    return next(m["prix_client"] for m in ini["modules"] if m["id"] == module_id)


def _other_lines_signature(ini, exclude_module_id):
    mods = tuple(sorted(
        (m["id"], m["prix_client"]) for m in ini["modules"]
        if m["id"] != exclude_module_id))
    direct = tuple(sorted(
        (f["id"], f["prix_client"]) for f in ini["features_client"]
        if f.get("module_id") is None))
    fixed = tuple(sorted(
        (ff["id"], ff["prix_client"]) for ff in ini["frais_fixes_client"]))
    return mods, direct, fixed


def test_acceptance_line_price_independent_of_selection():
    """Pour CHAQUE module : le décocher => nouveau total = ancien total
    moins le prix AFFICHÉ de ce module (au cent près), et TOUTES les autres
    lignes (modules, fonctionnalités directes, frais fixes) sont identiques
    au cent près. (Échoue sur l'ancien moteur, passe sur le nouveau.)"""
    soum, mods, items = _realistic_inputs()
    full = compute_devis(soum, items, mods)["initial"]
    total_full = full["total_final"]
    for target in (1, 2, 3, 4):
        price_target = _module_price(full, target)
        base_sig = _other_lines_signature(full, target)
        mods2 = [_Module(m.id, selected=(m.id != target), name=m.name)
                 for m in mods]
        part = compute_devis(soum, items, mods2)["initial"]
        assert abs((total_full - price_target) - part["total_final"]) <= 0.01
        assert _other_lines_signature(part, target) == base_sig


# --------------------------------------------------------------------------
# Gratuité « module → module » bakée dans les fonctionnalités directes
# --------------------------------------------------------------------------


def test_offered_module_zero_and_baked_into_direct():
    soum = _Soum(heures_manager=0)
    mods = [_Module(10, selected=True),
            _Module(30, selected=True, free_when_module_id=10)]
    items = [
        _Item(1, "feature", heures=40, module_id=10),
        _Item(2, "feature", heures=20, module_id=30),   # offert
        _Item(5, "feature", heures=8, module_id=None),  # directe
    ]
    ini = compute_devis(soum, items, mods)["initial"]
    f2 = next(f for f in ini["features_client"] if f["id"] == 2)
    assert f2["prix_client"] == 0.0 and f2["offert"] is True
    mod30 = next(m for m in ini["modules"] if m["id"] == 30)
    assert mod30["offert"] is True and mod30["prix_client"] == 0.0
    s = sum(f["prix_client"] for f in ini["features_client"]) + sum(
        ff["prix_client"] for ff in ini["frais_fixes_client"])
    assert abs(round(s, 2) - ini["total_final"]) <= 0.01


def test_offered_module_does_not_inflate_paying_modules():
    """Ajouter un module OFFERT ne change PAS le prix des modules payants :
    son coût va dans les fonctionnalités directes."""
    soum = _Soum(heures_manager=0)
    ini_a = compute_devis(
        soum,
        [_Item(1, "feature", heures=40, module_id=10),
         _Item(5, "feature", heures=8, module_id=None)],
        [_Module(10, selected=True)],
    )["initial"]
    ini_b = compute_devis(
        soum,
        [_Item(1, "feature", heures=40, module_id=10),
         _Item(5, "feature", heures=8, module_id=None),
         _Item(2, "feature", heures=20, module_id=30)],
        [_Module(10, selected=True),
         _Module(30, selected=True, free_when_module_id=10)],
    )["initial"]
    p10_a = _module_price(ini_a, 10)
    p10_b = _module_price(ini_b, 10)
    assert abs(p10_a - p10_b) <= 0.01
    d5_a = next(f for f in ini_a["features_client"] if f["id"] == 5)["prix_client"]
    d5_b = next(f for f in ini_b["features_client"] if f["id"] == 5)["prix_client"]
    assert d5_b > d5_a
    assert ini_b["total_final"] > ini_a["total_final"]


def test_trigger_deselected_direct_unchanged_module_charged():
    soum = _Soum(heures_manager=0)
    items = [_Item(1, "feature", heures=40, module_id=10),
             _Item(2, "feature", heures=20, module_id=30),
             _Item(5, "feature", heures=8, module_id=None)]
    on = compute_devis(soum, items, [
        _Module(10, selected=True),
        _Module(30, selected=True, free_when_module_id=10)])["initial"]
    off = compute_devis(soum, items, [
        _Module(10, selected=False),
        _Module(30, selected=True, free_when_module_id=10)])["initial"]
    d_on = next(f for f in on["features_client"] if f["id"] == 5)["prix_client"]
    d_off = next(f for f in off["features_client"] if f["id"] == 5)["prix_client"]
    assert abs(d_on - d_off) <= 0.01  # fonctionnalités directes inchangées
    m30_on = next(m for m in on["modules"] if m["id"] == 30)
    m30_off = next(m for m in off["modules"] if m["id"] == 30)
    assert m30_on["offert"] is True and m30_on["prix_client"] == 0.0
    assert m30_off["offert"] is False and m30_off["prix_client"] > 0


def test_all_offered_recovered_in_direct_no_crash():
    soum = _Soum(heures_manager=0)
    mods = [_Module(10, selected=True),
            _Module(30, selected=True, free_when_module_id=10)]
    items = [_Item(2, "feature", heures=20, module_id=30),
             _Item(3, "feature", heures=10, module_id=30),
             _Item(5, "fixed_cost", cost_per_unit=1000)]
    res = compute_devis(soum, items, mods)
    ini = res["initial"]
    assert res["is_invalid"] is False
    for f in ini["features_client"]:
        if f.get("id") in (2, 3):
            assert f["prix_client"] == 0.0
    s = sum(f["prix_client"] for f in ini["features_client"]) + sum(
        ff["prix_client"] for ff in ini["frais_fixes_client"])
    assert abs(round(s, 2) - ini["total_final"]) <= 0.01


def test_empty_submission_invalid_no_crash():
    res = compute_devis(_Soum(heures_manager=0), [], [])
    assert res["is_invalid"] is True
    assert res["initial"]["total_final"] == 0.0


def test_invariant_sum_equals_total_mixed():
    soum = _Soum(heures_manager=0)
    mods = [_Module(10, selected=True),
            _Module(30, selected=True, free_when_module_id=10),
            _Module(40, selected=False)]
    items = [_Item(1, "feature", heures=37, module_id=10),
             _Item(2, "feature", heures=13, module_id=10),
             _Item(3, "feature", heures=20, module_id=30),
             _Item(4, "feature", heures=50, module_id=40),
             _Item(5, "feature", heures=9, module_id=None),
             _Item(6, "fixed_cost", cost_per_unit=300),
             _Item(7, "manager_task", heures=6, module_id=10)]
    ini = compute_devis(soum, items, mods)["initial"]
    s = sum(f["prix_client"] for f in ini["features_client"]) + sum(
        ff["prix_client"] for ff in ini["frais_fixes_client"])
    assert abs(round(s, 2) - ini["total_final"]) <= 0.01


if __name__ == "__main__":
    import inspect

    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and inspect.isfunction(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} tests OK")
    sys.exit(1 if failed else 0)
