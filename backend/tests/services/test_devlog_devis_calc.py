"""Tests du moteur de calcul des soumissions « devis_dev »
(``app.services.devlog_devis_calc.compute_devis``).

Objectif principal : PROUVER la rétrocompatibilité de la refonte
2026-06 (Phase 2 — modules, tâches de chargé de projet, sélection,
gratuité conditionnelle). Une soumission SANS modules et SANS item
``manager_task`` doit produire EXACTEMENT les mêmes totaux qu'avant la
refonte (chemin legacy : tous les items comptés, coût manager =
``heures_manager`` scalaire × ``taux_manager``).

On utilise de simples stubs (pas de DB) : ``compute_devis`` ne lit que
des attributs via ``getattr``.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.devlog_devis_calc import compute_devis


# --------------------------------------------------------------------------
# Stubs légers (lecture seule par attribut, comme les modèles SQLAlchemy)
# --------------------------------------------------------------------------


class _Soum:
    def __init__(self, **kw):
        self.marge_recurrente_pct = kw.get("marge_recurrente_pct", 50)
        self.marge_initiale_pct = kw.get("marge_initiale_pct", 50)
        self.commission_closer_pct = kw.get("commission_closer_pct", 10)
        self.taux_dev_horaire = kw.get("taux_dev_horaire", 75)
        self.taux_manager_horaire = kw.get("taux_manager_horaire", 80)
        self.heures_manager = kw.get("heures_manager", 0)


class _Item:
    def __init__(
        self,
        id,
        kind="feature",
        heures=None,
        cost_per_unit=0,
        description="x",
        module_id=None,
    ):
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
# RÉTROCOMPATIBILITÉ (critique)
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
    """Appel historique à 2 arguments : coût manager = scalaire."""
    soum, items = _legacy_inputs()
    res = compute_devis(soum, items)
    ini = res["initial"]
    # couts_dev = (40+20)*75 = 4500
    assert ini["couts_dev"] == 4500.0
    # cout_manager = 10*80 = 800 (scalaire heures_manager)
    assert ini["cout_manager"] == 800.0
    # frais_fixes = 500
    assert ini["frais_fixes_total"] == 500.0
    # base = 4500 + 800 + 500 = 5800
    assert ini["base"] == 5800.0
    assert res["is_invalid"] is False


def test_legacy_modules_none_equals_two_args():
    """``modules=None`` explicite == appel à 2 arguments (bit à bit)."""
    soum, items = _legacy_inputs()
    assert compute_devis(soum, items) == compute_devis(soum, items, None)


def test_legacy_invariant_sum_client_equals_total():
    """Σ(prix client) == total_final (à 1 cent près)."""
    soum, items = _legacy_inputs()
    res = compute_devis(soum, items)
    ini = res["initial"]
    sum_client = sum(f["prix_client"] for f in ini["features_client"]) + sum(
        ff["prix_client"] for ff in ini["frais_fixes_client"]
    )
    assert abs(round(sum_client, 2) - ini["total_final"]) <= 0.01


def test_legacy_no_modules_field_empty():
    """Mode legacy : pas de détail par module ni de tâches manager."""
    soum, items = _legacy_inputs()
    ini = compute_devis(soum, items)["initial"]
    assert ini["modules"] == []
    assert ini["manager_tasks"] == []


# --------------------------------------------------------------------------
# 1. Tâche de chargé de projet (manager_task)
# --------------------------------------------------------------------------


def test_manager_task_replaces_scalar():
    """Dès qu'une ``manager_task`` existe, le scalaire est ignoré."""
    soum = _Soum(heures_manager=999)  # doit être IGNORÉ
    mods = [_Module(10, selected=True)]
    items = [
        _Item(1, "feature", heures=40, module_id=10),
        _Item(2, "feature", heures=10, module_id=10),
        _Item(3, "manager_task", heures=8, module_id=10),
        _Item(4, "manager_task", heures=2, module_id=10),
    ]
    ini = compute_devis(soum, items, mods)["initial"]
    assert ini["cout_manager"] == 800.0  # (8+2)*80, pas 999*80
    assert ini["couts_dev"] == 3750.0  # (40+10)*75


def test_manager_task_absent_falls_back_to_scalar():
    """Aucune ``manager_task`` => scalaire ``heures_manager`` utilisé."""
    soum = _Soum(heures_manager=10)
    mods = [_Module(10, selected=True)]
    items = [_Item(1, "feature", heures=40, module_id=10)]
    ini = compute_devis(soum, items, mods)["initial"]
    assert ini["cout_manager"] == 800.0  # 10*80


# --------------------------------------------------------------------------
# 2. Filtrage par modules sélectionnés
# --------------------------------------------------------------------------


def test_unselected_module_excluded():
    soum = _Soum(heures_manager=0)
    mods = [_Module(10, selected=True), _Module(20, selected=False)]
    items = [
        _Item(1, "feature", heures=40, module_id=10),  # compté
        _Item(2, "feature", heures=100, module_id=20),  # exclu
        _Item(3, "manager_task", heures=5, module_id=10),  # compté
        _Item(4, "manager_task", heures=99, module_id=20),  # exclu
        _Item(5, "feature", heures=10, module_id=None),  # sans module
    ]
    ini = compute_devis(soum, items, mods)["initial"]
    assert ini["couts_dev"] == 3750.0  # (40+10)*75
    assert ini["cout_manager"] == 400.0  # 5*80
    client_ids = [f["id"] for f in ini["features_client"]]
    assert 2 not in client_ids
    assert 5 in client_ids  # item sans module toujours compté


# --------------------------------------------------------------------------
# 3. Gratuité conditionnelle « module → module »
# --------------------------------------------------------------------------


def test_free_module_when_trigger_selected():
    soum = _Soum(heures_manager=0)
    mods = [
        _Module(10, selected=True),
        _Module(30, selected=True, free_when_module_id=10),
    ]
    items = [
        _Item(1, "feature", heures=40, module_id=10),
        _Item(2, "feature", heures=20, module_id=30),  # gratuit
        _Item(3, "manager_task", heures=4, module_id=30),  # offert
    ]
    ini = compute_devis(soum, items, mods)["initial"]
    assert ini["couts_dev"] == 3000.0  # 40*75, module 30 gratuit
    assert ini["cout_manager"] == 0.0
    f2 = next(f for f in ini["features_client"] if f["id"] == 2)
    assert f2["prix_client"] == 0.0
    assert f2["offert"] is True
    mod30 = next(m for m in ini["modules"] if m["id"] == 30)
    assert mod30["offert"] is True
    assert mod30["prix_client"] == 0.0
    # heures restent visibles côté interne
    assert mod30["total_heures_dev"] == 20.0
    assert mod30["total_heures_manager"] == 4.0


def test_free_module_inactive_when_trigger_unselected():
    soum = _Soum(heures_manager=0)
    mods = [
        _Module(10, selected=False),  # déclencheur OFF
        _Module(30, selected=True, free_when_module_id=10),
    ]
    items = [
        _Item(1, "feature", heures=40, module_id=10),  # exclu
        _Item(2, "feature", heures=20, module_id=30),  # PAYANT
    ]
    ini = compute_devis(soum, items, mods)["initial"]
    assert ini["couts_dev"] == 1500.0  # 20*75
    f2 = next(f for f in ini["features_client"] if f["id"] == 2)
    assert f2["offert"] is False
    assert f2["prix_client"] > 0


def test_invariant_holds_with_selection_and_free():
    soum = _Soum(heures_manager=0)
    mods = [
        _Module(10, selected=True),
        _Module(30, selected=True, free_when_module_id=10),
        _Module(40, selected=False),
    ]
    items = [
        _Item(1, "feature", heures=37, module_id=10),
        _Item(2, "feature", heures=13, module_id=10),
        _Item(3, "feature", heures=20, module_id=30),  # gratuit
        _Item(4, "feature", heures=50, module_id=40),  # exclu
        _Item(5, "fixed_cost", cost_per_unit=300),
        _Item(6, "manager_task", heures=6, module_id=10),
    ]
    ini = compute_devis(soum, items, mods)["initial"]
    sum_client = sum(f["prix_client"] for f in ini["features_client"]) + sum(
        ff["prix_client"] for ff in ini["frais_fixes_client"]
    )
    assert abs(round(sum_client, 2) - ini["total_final"]) <= 0.01


if __name__ == "__main__":
    # Permet `python test_devlog_devis_calc.py` sans pytest installé.
    import inspect

    fns = [
        (n, f)
        for n, f in sorted(globals().items())
        if n.startswith("test_") and inspect.isfunction(f)
    ]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:  # pragma: no cover
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} tests OK")
    sys.exit(1 if failed else 0)
