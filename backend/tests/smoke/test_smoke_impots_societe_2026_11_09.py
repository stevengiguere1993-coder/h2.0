"""Smoke — impôts de la société dans Revenus et dépenses (2026-11-09).

Phil : « rajoute les impôts… je peux écrire par exemple le taux marginal… les
dividendes sont versés après le paiement d'impôts ». Deux paliers visibles et
modifiables, impôt sur le bénéfice avant impôts (jamais sur une perte), les
dividendes se versent sur le bénéfice après impôts.
"""
from __future__ import annotations

from app.services import revenus_depenses as svc


def test_calcul_impots_par_paliers():
    regles = svc.scenario_defaut()["depenses"]["impots"]
    assert regles == {"taux_pct": 12.2, "plafond": 500000.0, "taux_au_dela_pct": 26.5}
    # Sous le plafond : un seul taux.
    r = svc.calcul_impots(232_241.41, regles)
    assert r["total"] == round(232_241.41 * 0.122, 2) and r["tranche_2"] == 0 and r["taux_effectif_pct"] == 12.2
    # Au-dessus : le taux général sur l'excédent seulement (comme l'impôt, pas d'effet de seuil).
    r = svc.calcul_impots(700_000, regles)
    assert r["tranche_1"] == 61_000 and r["tranche_2_base"] == 200_000 and r["tranche_2"] == 53_000 and r["total"] == 114_000
    assert r["taux_effectif_pct"] == round(100 * 114_000 / 700_000, 2)
    # Perte : rien. Plafond à 0 : un seul taux partout.
    assert svc.calcul_impots(-5_000, regles)["total"] == 0
    assert svc.calcul_impots(700_000, {"taux_pct": 20.0, "plafond": 0.0, "taux_au_dela_pct": 26.5})["total"] == 140_000
    # Normalisation : défauts quand absent, bornes.
    n = svc.normaliser({"depenses": {"impots": {"taux_pct": 150, "plafond": -1}}})["depenses"]["impots"]
    assert n == {"taux_pct": 100.0, "plafond": 0.0, "taux_au_dela_pct": 26.5}
    assert svc.normaliser({})["depenses"]["impots"] == regles
    assert "impots_note" in svc.referentiel()


def test_dividendes_apres_impots_dans_le_calcul():
    data = svc.normaliser({
        "immeubles": [svc.immeuble_vide(nom="x", nb_logements=10, loyers_bruts_mensuels=20_000, valeur_rapport=3_000_000, taux_cap_pct=5.0, dette=1_000_000)],
        "depenses": {"frais_fixes": [], "associes": [{"nom": "P", "salaire_annuel": 0, "dividendes_annuels": 50_000}]},
    })
    r = svc.calculer(data)
    t, imp = r["totaux"], r["depenses"]["impots"]
    assert t["benefice"] > 0 and t["impots"] == imp["total"] == round(t["benefice"] * 0.122, 2)
    assert t["benefice_apres_impots"] == round(t["benefice"] - t["impots"], 2)
    assert t["benefice_retenu"] == round(t["benefice_apres_impots"] - 50_000, 2)
    assert t["marge_apres_impots_pct"] == round(100 * t["benefice_apres_impots"] / t["revenus"], 2)
    # Les impôts ne sont pas une « dépense » : le bénéfice avant impôts ne bouge pas, le bénéfice avant associés non plus.
    assert t["depenses"] == r["depenses"]["total"] and t["benefice_avant_associes"] == t["benefice"]
    # Dividendes au-delà du bénéfice après impôts → avertissement ; résumé enrichi.
    data["depenses"]["associes"][0]["dividendes_annuels"] = 1_000_000
    r2 = svc.calculer(data)
    assert any("après impôts" in a for a in r2["avertissements"]) and r2["totaux"]["benefice_retenu"] < 0
    res = svc.resume(r2)
    assert res["impots"] == r2["totaux"]["impots"] and res["benefice_apres_impots"] == r2["totaux"]["benefice_apres_impots"]
    # Taux à 0 : rien ne change par rapport à avant.
    data["depenses"]["impots"] = {"taux_pct": 0, "plafond": 0, "taux_au_dela_pct": 0}
    r3 = svc.calculer(data)
    assert r3["totaux"]["impots"] == 0 and r3["totaux"]["benefice_apres_impots"] == r3["totaux"]["benefice"]
