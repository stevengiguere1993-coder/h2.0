"""Smoke — Performance du fonds v2 : projection année par année (2026-11-06).

Phil : « il faut que tout ça soit annualisé… en ayant seulement l'année actuelle,
on ne peut pas voir la performance du fonds » ; « un fonds c'est toujours sur le
capital du fonds… il faut que ça reflète [le document] » ; « détention simple
pour commencer ».
"""
from __future__ import annotations

from app.services import performance_fonds as pf
from app.services import revenus_depenses as svc
from app.services.lead_analysis_finance import solde_pret_canadien

REGLES = {"seuil_investisseurs_pct": 7.0, "tranche_nous_pct": 3.0, "part_nous_pct": 30.0}


def test_partage_en_parts_reproduit_la_page_8_du_document():
    """10 M$, 1 000 000 parts à 10 $, année à 15 % → p. 8 : 11,5 / 13,2 / 15,2 / 17,5 / 20,1 M$
    et nos 3 holdings ensemble 3,9 / 7,7 / 11,3 / 14,8 / 18,1 % du fonds ; an 1 : part à 11,05 $,
    40 724 nouvelles parts pour nous (13 575 par holding)."""
    van, parts, nous = 10_000_000.0, 1_000_000.0, 0.0
    attendu = [(11.5, 3.9), (13.2, 7.7), (15.2, 11.3), (17.5, 14.8), (20.1, 18.1)]
    for n, (van_m, pct) in enumerate(attendu, 1):
        gain = van * 0.15
        p = pf.partager_annee(van, 0.0, gain, parts, nous, REGLES)
        van += gain
        parts, nous = p["parts_total"], p["parts_nous"]
        assert round(van / 1e6, 1) == van_m and round(p["pct_nous"], 1) == pct, (n, van, p["pct_nous"])
        assert abs(p["prix_part"] * p["parts_total"] - van) < 1.0          # VAN fin = prix × parts, exactement
        if n == 1:
            assert round(p["prix_part"], 2) == 11.05 and round(p["nouvelles_parts_nous"]) == 40_724
            assert p["part_investisseurs"] == 1_050_000 and p["part_nous"] == 450_000 and round(p["rendement_part_pct"], 1) == 10.5
    # Une perte est portée par toutes les parts, rien de nouveau pour nous.
    p = pf.partager_annee(10_000_000, 0.0, -500_000, 1_000_000, 0.0, REGLES)
    assert p["part_nous"] == 0 and p["nouvelles_parts_nous"] == 0 and round(p["prix_part"], 2) == 9.5
    # Capital entré dans l'année : des parts au prix de départ, personne n'est dilué (p. 16).
    p = pf.partager_annee(10_000_000, 500_000, 0.0, 800_000, 0.0, REGLES)
    assert p["parts_entrees"] == 40_000 and round(p["prix_part"], 2) == 12.5


def test_simulation_des_prets_detention_simple():
    hyp = dict(svc.PROJECTION_DEFAUT)
    # Prêt amorti : même solde que la formule canadienne de Prospection, service = 12 paiements.
    s = pf.simuler_pret({"solde": 500_000, "taux_pct": 5.0, "mois_restants": 300, "paiement_mensuel": 0, "composition": "semi"}, 3, hyp)
    assert round(s[0]["solde"]) == round(solde_pret_canadien(500_000, 0.05, 25, 1))
    assert round(s[2]["solde"]) == round(solde_pret_canadien(500_000, 0.05, 25, 3))
    assert abs(s[0]["service"] - (s[0]["capital"] + s[0]["interets"])) < 0.01 and s[1]["capital"] > s[0]["capital"]
    # Intérêts seulement, converti à l'an 3 : solde plat puis amorti aux conditions par défaut.
    io = pf.simuler_pret({"solde": 800_000, "taux_pct": 8.0, "mois_restants": 0, "paiement_mensuel": 0, "composition": "mensuelle",
                          "interet_seulement": True, "conversion_annee": 3}, 4, hyp)
    assert io[0]["capital"] == 0 and io[1]["solde"] == 800_000 and round(io[0]["service"]) == 64_000
    assert io[2]["capital"] > 0 and io[2]["solde"] < 800_000 and round(io[2]["service"]) == round(12 * pf._pmt(800_000, 5.0, 300, "semi"))
    # Renouvellement du terme à l'an 2 avec un taux de renouvellement : le paiement change.
    r = pf.simuler_pret({"solde": 500_000, "taux_pct": 3.0, "mois_restants": 300, "paiement_mensuel": 2_000, "composition": "semi",
                         "fin_terme_annee": 1}, 2, {**hyp, "taux_renouvellement_pct": 6.0})
    assert round(r[0]["service"]) == 24_000 and r[1]["service"] > 30_000
    # Prêt déjà remboursé : rien.
    assert pf.simuler_pret({"solde": 0, "taux_pct": 5.0, "mois_restants": 300}, 2, hyp) == [{"service": 0.0, "capital": 0.0, "interets": 0.0, "solde": 0.0}] * 2


def test_projection_du_fonds_deux_immeubles():
    d = svc.scenario_defaut()
    d["annee"] = 2027
    d["fonds"]["cash"] = 50_000
    d["projection"]["horizon_annees"] = 5
    d["immeubles"] = [
        svc.immeuble_vide(nom="Stab", nb_logements=6, loyers_bruts_mensuels=6_000, valeur_rapport=800_000, taux_cap_pct=5.0, dette=500_000,
                          taxes_municipales=5_000, assurances=2_000),
        # Acquisition le 1er avril 2027, en rénovation 24 mois, prêteur intérêts seulement (doc p. 12 : coût 1,5 M$, prêt 800 k$, mise 700 k$).
        svc.immeuble_vide(nom="Reno", phase="stabilisation", acquisition_cette_annee=True, date_acquisition="2027-04-01", prix_acquisition=1_000_000,
                          travaux_initiaux=380_000, frais_connexes=120_000, valeur_future=1_700_000, dette=800_000, mois_prevus=24,
                          loyers_bruts_mensuels=4_000, taux_cap_pct=5.0, interet_seulement=True),
        svc.immeuble_vide(nom="Hors fonds", dans_le_fonds=False, nb_logements=2, loyers_bruts_mensuels=2_000, valeur_rapport=300_000, taux_cap_pct=5.0),
    ]
    out = pf.calculer_performance(d)
    assert out["annee_depart"] == 2027 and out["horizon"] == 5 and [a["annee"] for a in out["fonds"]["annees"]] == [2027, 2028, 2029, 2030, 2031]
    stab, reno, hors = out["projets"]
    # Stabilisé : valeur = revenus nets ÷ cap chaque année, dette amortie aux défauts, cash-flow = revenus nets − service.
    a1 = stab["annees"][0]
    assert stab["depart"]["equite"] == round(stab["depart"]["valeur"] - 500_000, 2) and a1["revenus_bruts"] == 72_000
    assert a1["valeur"] == round(a1["revenus_nets"] / 0.05, 2) and a1["cash_flow"] == round(a1["revenus_nets"] - a1["service_dette"], 2)
    assert stab["annees"][1]["revenus_bruts"] == round(72_000 * 1.03, 2) and a1["solde"] < 500_000 and stab["sommaire"]["tri_pct"] > 0
    # Rénovation : an 1 au prorata (275 jours), coût + plus-value linéaire ; stabilisé à l'an 2 (24 mois), revenus nets = valeur future × cap ;
    # intérêts seulement jusqu'à la stabilisation puis amorti.
    r1, r2, r3 = reno["annees"][:3]
    assert reno["acquise_cette_annee"] is True and reno["depart"]["equite"] == 700_000 and reno["annee_stabilisation"] == 2028
    assert r1["en_renovation"] is True and 75 < r1["prorata"] < 76 and r1["valeur"] == 1_600_000 and r1["capital_rembourse"] == 0
    assert r2["en_renovation"] is False and r2["valeur"] == 1_700_000 and r2["revenus_nets"] == 85_000 and r2["solde"] == 800_000
    assert r3["capital_rembourse"] > 0 and r3["solde"] < 800_000 and r3["valeur"] == round(1_700_000 * 1.03, 2)
    assert any("valeur future × taux de cap" in n for n in reno["notes"]) and any("intérêts seulement" in n.lower() for n in reno["notes"])
    # Hors fonds : projeté mais exclu des totaux du fonds.
    assert hors["dans_le_fonds"] is False and hors["sommaire"]["tri_pct"] is not None
    f = out["fonds"]
    s = f["sommaire"]
    assert s["nb_immeubles"] == 2 and s["nb_hors_fonds"] == 1 and s["nb_acquisitions_an1"] == 1
    # VAN de départ = équité des immeubles déjà détenus + cash ; l'acquisition entre comme capital, pas comme gain.
    assert s["van_depart"] == round(stab["depart"]["equite"] + 50_000, 2) and s["capital_entre"] == 700_000
    y1 = f["annees"][0]
    assert y1["capital_entre"] == 700_000 and y1["van_debut"] == s["van_depart"]
    assert abs(y1["van"] - (y1["valeur"] + y1["cash"] - y1["dettes"])) < 0.02
    assert abs(y1["gain"] - (y1["van"] - y1["van_debut"] - 700_000)) < 0.02
    # Les trois sources du gain (doc p. 14) redonnent le gain ; frais du fonds 1,5 % de la VAN de départ + capital entré.
    src = y1["sources"]
    assert abs(src["plus_value"] + src["capital_rembourse"] + src["cash"] - y1["gain"]) < 0.05
    assert y1["frais_fonds"] == round((s["van_depart"] + 700_000) * 0.015, 2) and y1["cash"] == round(50_000 + y1["cash_flow"] - y1["frais_fonds"], 2)
    # Rendement du fonds = gain ÷ (VAN de départ + capital entré) ; parts : prix × parts = VAN ; notre % monte chaque année.
    assert y1["rendement_pct"] == round(100 * y1["gain"] / (s["van_depart"] + 700_000), 2)
    for a in f["annees"]:
        assert abs(a["prix_part"] * a["parts_total"] - a["van"]) <= 0.005 * a["parts_total"] + 1   # prix arrondi au cent
    pcts = [a["pct_nous"] for a in f["annees"]]
    assert pcts == sorted(pcts) and pcts[0] > 0 and s["pct_nous_horizon"] == pcts[-1]
    assert s["van_horizon"] == f["annees"][-1]["van"] and s["tri_pct"] is not None and s["rendement_moyen_pct"] is not None
    assert s["prix_part_depart"] == 10 and s["prix_part_horizon"] == f["annees"][-1]["prix_part"] and s["rendement_part_annualise_pct"] > 0
    assert abs(s["gain_total"] - sum(a["gain"] for a in f["annees"])) < 0.1
    # Hypothèses visibles : taux de cap de sortie et taux de renouvellement s'appliquent partout.
    d["projection"]["taux_cap_sortie_pct"] = 6.0
    d["projection"]["taux_renouvellement_pct"] = 7.0
    out2 = pf.calculer_performance(d)
    s2 = out2["projets"][0]
    assert s2["annees"][0]["valeur"] == round(s2["annees"][0]["revenus_nets"] / 0.06, 2) and any("Taux de cap de sortie" in n for n in s2["notes"])
    assert out2["projets"][1]["annees"][2]["service_dette"] > reno["annees"][2]["service_dette"]   # IO converti au taux de renouvellement 7 %


def test_normalisation_de_la_section_projection():
    d = svc.normaliser({"projection": {"horizon_annees": 0, "croissance_loyers_pct": "2.5", "part_nos_holdings_depart_pct": 250, "amortissement_defaut_ans": -3}})
    p = d["projection"]
    assert p["horizon_annees"] == 10 and p["croissance_loyers_pct"] == 2.5 and p["part_nos_holdings_depart_pct"] == 100 and p["amortissement_defaut_ans"] == 25
    assert p["taux_cap_sortie_pct"] == 0 and p["taux_renouvellement_pct"] == 0 and p["prix_part_depart"] == 10
    assert svc.normaliser({"projection": {"horizon_annees": 99}})["projection"]["horizon_annees"] == 30
    i = svc.normaliser({"immeubles": [{"nom": "x", "loyers_stabilises_mensuels": 5000, "taux_dette_pct": 4.5, "amortissement_ans": 30, "interet_seulement": True}]})["immeubles"][0]
    assert i["loyers_stabilises_mensuels"] == 5000 and i["taux_dette_pct"] == 4.5 and i["amortissement_ans"] == 30 and i["interet_seulement"] is True
    assert "projection_note" in svc.referentiel()
