"""Import des coûts QB : une facture FRACTIONNÉE dans QuickBooks entre
dans Kratos comme dans QB (retour Steven 2026-10-06, « importer la
séparation de factures »).

Règles couvertes (helpers purs, sans base) :
- une ligne non imputée à un projet Kratos (client mère, autre client,
  aucun client) n'entre pas : sa part reste dans QuickBooks ;
- plusieurs projets → une part par projet, au prorata du HT des lignes,
  la somme retombant exactement sur le total quand tout est imputé ;
- un projet + une part hors projet → l'achat ne porte que la part du
  projet, et le passage suivant ne le ramène PAS au total (pas
  d'oscillation) ;
- import des Bills (HT + taxes) : taxes au prorata du HT de TOUTES les
  lignes, total QB = TotalAmt.
"""

from types import SimpleNamespace

import pytest

from app.services.achat_qbo_pull import (
    _bill_total,
    _split_tax_shares,
    _sum_bill_amounts,
)
from app.services.qbo_cost_pull import (
    _compter_division,
    _lignes_ht_total,
    _montant_attendu,
    _part_hors_projet,
    _parts_a_importer,
    _project_allocations,
    _split_amounts,
    _statut_division,
)

A = SimpleNamespace(id=11, name="Chantier A")
B = SimpleNamespace(id=22, name="Chantier B")


def _ligne(montant, *, job=None, classe=None, desc=None, item=False, detail=None):
    key = "ItemBasedExpenseLineDetail" if item else "AccountBasedExpenseLineDetail"
    d = dict(detail or {"AccountRef": {"value": "60"}})
    if job:
        d["CustomerRef"] = {"value": job}
    if classe:
        d["ClassRef"] = {"name": classe}
    line = {"Amount": montant, "DetailType": key, key: d}
    if desc:
        line["Description"] = desc
    return line


def _txn(*lignes):
    return {"Id": "1", "TotalAmt": 0, "Line": list(lignes)}


PROJ_BY_JOB = {"JA": A, "JB": B}


def _resolver(cname):
    return B if cname == "Classe B" else None


# ── Ventilation des lignes ───────────────────────────────────────────


def test_lignes_ht_total_somme_toutes_les_lignes_de_depense():
    txn = _txn(
        _ligne(600, job="JA"),
        _ligne(300, job="JB", item=True),
        _ligne(100),
        {"Amount": 1000, "DetailType": "SubTotalLineDetail",
         "SubTotalLineDetail": {}},
    )
    assert _lignes_ht_total(txn) == 1000.0
    assert _lignes_ht_total({"Line": []}) == 0.0


def test_allocations_lignes_mixtes_en_ordre_avec_hors_projet():
    txn = _txn(
        _ligne(600, job="JA", desc="Bois A"),
        _ligne(300, classe="Classe B", desc="Gypse B"),
        _ligne(100, desc="Atelier"),            # aucun projet → reste dans QB
        _ligne(50, job="JA", desc="Vis A"),     # 2e ligne du même projet
    )
    allocs = _project_allocations(txn, PROJ_BY_JOB, _resolver)
    assert [a["project"].id for a in allocs] == [A.id, B.id]
    assert [a["ht"] for a in allocs] == [650.0, 300.0]
    assert [a["description"] for a in allocs] == ["Bois A", "Gypse B"]
    assert _part_hors_projet(txn, allocs) is True


def test_part_hors_projet_fausse_quand_tout_est_impute():
    txn = _txn(_ligne(600, job="JA"), _ligne(400, job="JB"))
    allocs = _project_allocations(txn, PROJ_BY_JOB)
    assert _part_hors_projet(txn, allocs) is False
    assert _part_hors_projet({"Line": []}, []) is False


# ── Répartition des montants ─────────────────────────────────────────


def test_split_complet_retombe_exactement_sur_le_total():
    allocs = [{"ht": 1.0}, {"ht": 1.0}, {"ht": 1.0}]
    parts = _split_amounts(100.0, allocs)
    assert parts == [33.33, 33.33, 33.34]
    assert round(sum(parts), 2) == 100.0
    assert _split_amounts(1000.0, [{"ht": 600.0}, {"ht": 400.0}]) == [600.0, 400.0]


def test_split_partiel_laisse_le_reste_dans_qb():
    # 1 149,75 $ TTC pour 1 000 $ HT dont 100 $ hors projet.
    parts = _split_amounts(1149.75, [{"ht": 600.0}, {"ht": 300.0}], base_ht=1000.0)
    assert parts == [round(1149.75 * 0.6, 2), round(1149.75 * 0.3, 2)]
    assert sum(parts) < 1149.75
    # Le reste (114,975 $ hors projet) demeure dans QuickBooks, à l'arrondi
    # du cent près.
    assert 1149.75 - sum(parts) == pytest.approx(114.975, abs=0.011)
    # base_ht égal au HT connu = pas de part hors projet → split complet.
    assert _split_amounts(1000.0, [{"ht": 600.0}, {"ht": 400.0}], base_ht=1000.0) == [600.0, 400.0]
    assert _split_amounts(100.0, []) == []
    assert _split_amounts(100.0, [{"ht": 0.0}]) == []


def test_parts_a_importer_vide_pour_un_seul_projet_entier():
    txn = _txn(_ligne(600, job="JA"), _ligne(400, job="JA"))
    allocs = _project_allocations(txn, PROJ_BY_JOB)
    assert _parts_a_importer(1149.75, txn, allocs) == []


def test_parts_a_importer_un_projet_plus_hors_projet():
    txn = _txn(_ligne(600, job="JA"), _ligne(400))
    allocs = _project_allocations(txn, PROJ_BY_JOB)
    assert _parts_a_importer(1149.75, txn, allocs) == [round(1149.75 * 0.6, 2)]


def test_parts_a_importer_deux_projets():
    txn = _txn(_ligne(600, job="JA"), _ligne(400, job="JB"))
    allocs = _project_allocations(txn, PROJ_BY_JOB)
    assert _parts_a_importer(1000.0, txn, allocs) == [600.0, 400.0]


# ── Montant attendu d'un achat déjà importé (pas d'oscillation) ──────


def test_montant_attendu_part_du_projet_quand_fractionnee():
    txn = _txn(_ligne(600, job="JA"), _ligne(400))
    allocs = _project_allocations(txn, PROJ_BY_JOB)
    ach = SimpleNamespace(amount=689.85, amount_taxes=None)
    attendu = _montant_attendu(ach, 1149.75, allocs, _lignes_ht_total(txn))
    assert attendu == round(1149.75 * 0.6, 2)


def test_montant_attendu_total_quand_tout_au_projet_ou_multi_projets():
    txn = _txn(_ligne(600, job="JA"), _ligne(400, job="JA"))
    allocs = _project_allocations(txn, PROJ_BY_JOB)
    ach = SimpleNamespace(amount=1000.0, amount_taxes=None)
    assert _montant_attendu(ach, 1149.75, allocs, _lignes_ht_total(txn)) == 1149.75
    # Deux projets : on vise le total pour que la division en parts
    # (réparation) puisse se faire au passage suivant.
    txn2 = _txn(_ligne(600, job="JA"), _ligne(400, job="JB"))
    allocs2 = _project_allocations(txn2, PROJ_BY_JOB)
    assert _montant_attendu(ach, 1000.0, allocs2, _lignes_ht_total(txn2)) == 1000.0
    # Aucun projet : le total (comportement historique).
    assert _montant_attendu(ach, 1000.0, [], 1000.0) == 1000.0


# ── Compteurs affichés après l'import ────────────────────────────────


def test_compteurs_et_statuts_de_division():
    stats: dict = {}
    deux = [{"project": A, "ht": 600.0}, {"project": B, "ht": 400.0}]
    un = [{"project": A, "ht": 600.0}]
    _compter_division(stats, deux, False, reparation=False)
    _compter_division(stats, un, True, reparation=False)
    _compter_division(stats, un, True, reparation=True)
    assert stats == {
        "split_multi_projets": 1,
        "parts_partielles": 2,
        "reduits_part_projet": 1,
    }
    assert _statut_division(deux) == "divise_multi_projets"
    assert _statut_division(un) == "reduit_part_projet"


# ── Import des Bills (sync-from-qbo, HT + taxes) ─────────────────────


def test_taxes_au_prorata_complet_puis_partiel():
    assert _split_tax_shares(100.0, [1.0, 1.0, 1.0]) == [33.33, 33.33, 33.34]
    partiel = _split_tax_shares(149.75, [600.0, 300.0], ht_total=1000.0)
    assert partiel == [round(149.75 * 0.6, 2), round(149.75 * 0.3, 2)]
    assert sum(partiel) < 149.75
    assert _split_tax_shares(10.0, []) == []
    assert _split_tax_shares(10.0, [0.0, 0.0]) == [0.0, 0.0]


def test_total_et_sommes_du_bill():
    bill = {
        "TotalAmt": "1149.75",
        "TxnTaxDetail": {"TotalTax": 149.75},
        "Line": [
            _ligne(600, job="JA"),
            _ligne(300, job="JB", item=True),
            _ligne(100),
            {"Amount": 1000, "DetailType": "SubTotalLineDetail",
             "SubTotalLineDetail": {}},
        ],
    }
    ht, taxes = _sum_bill_amounts(bill)
    assert (ht, taxes) == (1000.0, 149.75)
    assert _bill_total(bill, ht, taxes) == 1149.75
    assert _bill_total({"TotalAmt": "n/a"}, 1000.0, 149.75) == 1149.75
    assert _bill_total({}, 1000.0, 149.75) == 1149.75
