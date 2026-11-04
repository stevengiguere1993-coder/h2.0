"""Smoke — Gestion d'entreprise → Revenus et dépenses (simulation, 2026-11-04).

1. le moteur : chaque source de revenus et chaque dépense tombe sur le chiffre
   attendu (paliers de développement, prospection seulement si prospecté par
   nous, cost-plus en marge nette, immeubles non gérés exclus, relocations au
   roulement ou saisies, charges sociales, associés salaire/dividendes,
   point mort) ;
2. l'API : admins seulement, scénario par défaut créé au premier appel,
   enregistrement + recalcul, copie, suppression, calcul sans enregistrer.
"""
from __future__ import annotations

from app.services import revenus_depenses as svc

RD = "/api/v1/entreprises/revenus-depenses"


def _scenario_test() -> dict:
    d = svc.scenario_defaut()
    d["fonds"] = {"valeur_parc": 20_000_000, "cash": 1_000_000, "dettes": 13_000_000, "taux_pct": 1.5}
    d["immeubles"] = [
        {"id": "a", "nom": "A", "nb_logements": 20, "nb_chambres": 0, "loyers_bruts_mensuels": 25_000, "gere_par_nous": True,
         "phase": "stabilisation", "acquisition_cette_annee": True, "prix_acquisition": 4_500_000, "prospecte_par_nous": True,
         "travaux_initiaux": 500_000},
        {"id": "b", "nom": "B", "nb_logements": 10, "nb_chambres": 4, "loyers_bruts_mensuels": 12_000, "gere_par_nous": True,
         "phase": "stabilise", "acquisition_cette_annee": False, "prix_acquisition": 0, "prospecte_par_nous": False,
         "travaux_initiaux": 0},
        {"id": "c", "nom": "C (gestion externe)", "nb_logements": 30, "nb_chambres": 0, "loyers_bruts_mensuels": 40_000,
         "gere_par_nous": False, "phase": "stabilise", "acquisition_cette_annee": True, "prix_acquisition": 12_000_000,
         "prospecte_par_nous": False, "travaux_initiaux": 0},
    ]
    d["refacturation"] = {"marge_pct": 10, "lignes": [{"id": "r1", "libelle": "Avocat", "montant_annuel": 120_000}]}
    d["construction"] = {"marge_pct": 10, "pct_logements_renoves_par_an": 10, "cout_reno_logement": 15_000}
    d["maintenance"] = {"heures_par_an": 1_000, "cout_horaire": 50, "taux_facture": 75, "materiaux_annuels": 50_000, "marge_materiaux_pct": 10}
    d["gestion"] = {"taux_pct": 10, "loyers_additionnels_mensuels": 100_000, "inclure_projection": False}
    d["location"] = {"frais_logement": 600, "frais_chambre": 400, "taux_roulement_pct": 20, "nb_relocations_logements": None, "nb_relocations_chambres": None}
    d["depenses"] = {
        "frais_fixes": [{"categorie": "abonnements", "libelle": "Logiciels", "montant": 500, "periode": "mois"},
                        {"categorie": "informatique", "libelle": "TI", "montant": 2_400, "periode": "an"}],
        "charges_sociales_pct": 14,
        "salaires": [{"poste": "Comptabilité", "salaire_annuel": 50_000}, {"poste": "Gestionnaire immobilier", "salaire_annuel": 60_000}],
        "associes": [{"nom": "Philippe", "salaire_annuel": 40_000, "dividendes_annuels": 30_000},
                     {"nom": "Steven", "salaire_annuel": 0, "dividendes_annuels": 0},
                     {"nom": "Michael", "salaire_annuel": 0, "dividendes_annuels": 0}],
    }
    return d


def test_moteur_chaque_source_et_depense():
    r = svc.calculer(_scenario_test())
    rev = {s["key"]: s for s in r["revenus"]}
    assert rev["fonds"]["van"] == 8_000_000 and rev["fonds"]["revenu"] == 120_000
    # Développement : A (4,5 M → palier 3–6 M = 4,5 %) + C (12 M → 3,5 %) ; B n'est pas une acquisition.
    assert rev["developpement"]["revenu"] == 202_500 + 420_000
    assert [(l["immeuble"], l["pct"]) for l in rev["developpement"]["lignes"]] == [("A", 4.5), ("C (gestion externe)", 3.5)]
    # Prospection : seulement A (prospecté par nous).
    assert rev["prospection"]["revenu"] == 90_000 and [l["immeuble"] for l in rev["prospection"]["lignes"]] == ["A"]
    # Cost-plus = marge nette seulement.
    assert rev["refacturation"]["revenu"] == 12_000
    # Construction : stabilisation 500 k × 10 % ; stabilisé = (10 + 30) logements × 10 % × 15 000 × 10 % = 6 000.
    assert rev["construction"]["revenu_stabilisation"] == 50_000 and rev["construction"]["revenu_renovations"] == 6_000
    assert rev["construction"]["revenu"] == 56_000
    # Maintenance : 1 000 h × (75 − 50) + 50 000 × 10 %.
    assert rev["maintenance"]["revenu"] == 30_000 and rev["maintenance"]["volume_facture"] == 75_000 + 55_000
    # Gestion : A + B gérés (25 000 + 12 000) × 12 × 10 % ; C exclu et nommé.
    assert rev["gestion"]["revenu"] == 44_400 and rev["gestion"]["non_geres"] == ["C (gestion externe)"]
    assert rev["gestion_projection"]["revenu"] == 120_000 and rev["gestion_projection"]["inclus"] is False
    # Location : logements gérés 30 × 20 % = 6 × 600 ; chambres 4 × 20 % = 0,8 → 1 × 400.
    assert rev["location"]["relocations_logements"] == 6 and rev["location"]["relocations_chambres"] == 1
    assert rev["location"]["revenu"] == 3_600 + 400
    t = r["totaux"]
    assert t["revenus"] == 120_000 + 622_500 + 90_000 + 12_000 + 56_000 + 30_000 + 44_400 + 4_000
    assert t["revenus_avec_projection"] == t["revenus"] + 120_000
    # Dépenses : 6 000 + 2 400 fixes ; salaires 110 000 × 1,14 ; associé 40 000 × 1,14 ; dividendes à part.
    dep = r["depenses"]
    assert dep["total_frais_fixes"] == 8_400 and dep["total_masse_salariale"] == 125_400 + 45_600
    assert dep["total_dividendes"] == 30_000 and dep["total_charges_sociales"] == 15_400 + 5_600
    assert t["depenses"] == 8_400 + 171_000 and t["benefice"] == t["revenus"] - t["depenses"]
    assert t["benefice_retenu"] == t["benefice"] - 30_000 and r["point_mort"]["couvert"] is True
    assert r["point_mort"]["van_necessaire"] == 0 and r["point_mort"]["loyers_mensuels_sous_gestion_necessaires"] == 0
    assert r["avertissements"] == []


def test_moteur_point_mort_relocations_saisies_et_garde_fous():
    d = svc.scenario_defaut()
    d["fonds"] = {"valeur_parc": 5_000_000, "cash": 0, "dettes": 3_000_000, "taux_pct": 1.5}
    d["depenses"]["salaires"] = [{"poste": "Comptabilité", "salaire_annuel": 100_000}]
    d["depenses"]["charges_sociales_pct"] = 10
    d["depenses"]["associes"] = [{"nom": "Philippe", "salaire_annuel": 0, "dividendes_annuels": 50_000}]
    d["location"] = {"frais_logement": 600, "frais_chambre": 400, "taux_roulement_pct": 20, "nb_relocations_logements": 7, "nb_relocations_chambres": 0}
    d["maintenance"]["taux_facture"] = 40  # plus bas que le coût horaire
    d["maintenance"]["heures_par_an"] = 100
    r = svc.calculer(d)
    rev = {s["key"]: s for s in r["revenus"]}
    assert rev["fonds"]["revenu"] == 30_000 and rev["location"]["revenu"] == 4_200 and rev["maintenance"]["marge_heures"] == 0
    t = r["totaux"]
    assert t["depenses"] == 110_000 and t["revenus"] == 34_200 and t["benefice"] == -75_800
    pm = r["point_mort"]
    # Il manque 110 000 − 4 200 = 105 800 hors fonds → VAN nécessaire = 105 800 / 1,5 %.
    assert pm["couvert"] is False and pm["van_necessaire"] == round(105_800 / 0.015, 2)
    # Loyers sous gestion nécessaires : il manque 110 000 − 34 200 = 75 800 → / 10 % / 12.
    assert pm["loyers_mensuels_sous_gestion_necessaires"] == round(75_800 / 0.10 / 12, 2)
    assert any("taux facturé" in a for a in r["avertissements"]) and any("dividendes" in a for a in r["avertissements"])
    # Paliers : bornes incluses, dernier palier « et plus », taux sur le prix entier.
    pal = svc.PALIERS_DEV_DEFAUT
    assert svc.taux_developpement(3_000_000, pal) == 5.0 and svc.taux_developpement(3_000_001, pal) == 4.5
    assert svc.taux_developpement(15_000_000, pal) == 3.5 and svc.taux_developpement(50_000_000, pal) == 3.0
    # Normalisation : JSON abîmé → scénario propre.
    n = svc.normaliser({"immeubles": [{"nom": "X", "nb_logements": "12", "phase": "bidon"}, "pas un dict"], "fonds": {"taux_pct": "abc"}})
    assert n["immeubles"][0]["nb_logements"] == 12 and n["immeubles"][0]["phase"] == "stabilise" and len(n["immeubles"]) == 1
    assert n["fonds"]["taux_pct"] == 1.5 and n["developpement"]["paliers"][-1]["jusqua"] is None


def test_api_scenarios_admins_seulement(client, auth_headers, employee_headers):
    assert client.get(f"{RD}/scenarios", headers=employee_headers).status_code == 403
    r = client.get(f"{RD}/scenarios", headers=auth_headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["is_default"] is True and items[0]["nom"] == "Scénario de base"
    sid = items[0]["id"]
    d = client.get(f"{RD}/scenarios/{sid}", headers=auth_headers).json()
    assert d["resultats"]["totaux"]["revenus"] == 0 and d["referentiel"]["categories_frais_fixes"][0]["key"] == "abonnements"
    assert [p["poste"] for p in d["data"]["depenses"]["salaires"]] == svc.POSTES_DEFAUT
    assert [a["nom"] for a in d["data"]["depenses"]["associes"]] == ["Philippe", "Steven", "Michael"]
    # Enregistrer des hypothèses → recalcul + résumé.
    r = client.put(f"{RD}/scenarios/{sid}", headers=auth_headers, json={"nom": "Base 2027", "data": _scenario_test()})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["nom"] == "Base 2027" and d["resultats"]["totaux"]["revenus"] == 978_900 and d["resume"]["benefice"] == 978_900 - 179_400
    assert client.put(f"{RD}/scenarios/{sid}", headers=auth_headers, json={"nom": "   "}).status_code == 422
    # Copie, calcul sans enregistrer, suppression.
    r = client.post(f"{RD}/scenarios", headers=auth_headers, json={"source_id": sid})
    assert r.status_code == 201 and r.json()["nom"] == "Base 2027 (copie)" and r.json()["resultats"]["totaux"]["revenus"] == 978_900
    cid = r.json()["id"]
    assert client.get(f"{RD}/scenarios", headers=auth_headers).json()["total"] == 2
    r = client.post(f"{RD}/calculer", headers=auth_headers, json={"data": {"fonds": {"valeur_parc": 1_000_000, "taux_pct": 2}}})
    assert r.status_code == 200 and r.json()["resultats"]["revenus"][0]["revenu"] == 20_000
    assert client.delete(f"{RD}/scenarios/{cid}", headers=auth_headers).status_code == 204
    assert client.get(f"{RD}/scenarios/{cid}", headers=auth_headers).status_code == 404
    assert client.post(f"{RD}/scenarios", headers=employee_headers, json={}).status_code == 403
