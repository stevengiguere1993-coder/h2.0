"""Smoke — Performance du fonds : projection année par année (v2 2026-11-06, v3 2026-11-09).

Phil : « il faut que tout ça soit annualisé… en ayant seulement l'année actuelle,
on ne peut pas voir la performance du fonds » ; « un fonds c'est toujours sur le
capital du fonds… il faut que ça reflète [le document] » ; puis : « de l'argent
qui dort… le voir comme si on l'avait remboursé », « deux prêts financés le même
jour n'auront pas le même taux », « prendre ceux du dernier rapport ou du dernier
financement… avec un plus ou moins ».
"""
from __future__ import annotations

from app.services import performance_fonds as pf
from app.services import revenus_depenses as svc
from app.services.lead_analysis_finance import solde_pret_canadien

REGLES = {"seuil_investisseurs_pct": 7.0, "tranche_nous_pct": 3.0, "part_nous_pct": 30.0}
REF = {"taux_pct": 5.0, "amortissement_mois": 300, "nb_prets": 1, "source": "test"}


def test_partage_en_parts_reproduit_la_page_8_du_document():
    """10 M$, 1 000 000 parts à 10 $, année à 15 % → p. 8 : 11,5 / 13,2 / 15,2 / 17,5 / 20,1 M$
    et nos 3 holdings ensemble 3,9 / 7,7 / 11,3 / 14,8 / 18,1 % du fonds ; an 1 : part à 11,05 $,
    40 724 nouvelles parts pour nous."""
    van, parts, nous = 10_000_000.0, 1_000_000.0, 0.0
    attendu = [(11.5, 3.9), (13.2, 7.7), (15.2, 11.3), (17.5, 14.8), (20.1, 18.1)]
    for n, (van_m, pct) in enumerate(attendu, 1):
        gain = van * 0.15
        p = pf.partager_annee(van, 0.0, gain, parts, nous, REGLES)
        van += gain
        parts, nous = p["parts_total"], p["parts_nous"]
        assert round(van / 1e6, 1) == van_m and round(p["pct_nous"], 1) == pct, (n, van, p["pct_nous"])
        assert abs(p["prix_part"] * p["parts_total"] - van) < 1.0
        if n == 1:
            assert round(p["prix_part"], 2) == 11.05 and round(p["nouvelles_parts_nous"]) == 40_724
            assert p["part_investisseurs"] == 1_050_000 and p["part_nous"] == 450_000 and round(p["rendement_part_pct"], 1) == 10.5
    # Une perte est portée par toutes les parts, rien de nouveau pour nous.
    p = pf.partager_annee(10_000_000, 0.0, -500_000, 1_000_000, 0.0, REGLES)
    assert p["part_nous"] == 0 and p["nouvelles_parts_nous"] == 0 and round(p["prix_part"], 2) == 9.5
    # Capital entré dans l'année : des parts au prix de départ, personne n'est dilué (p. 16).
    p = pf.partager_annee(10_000_000, 500_000, 0.0, 800_000, 0.0, REGLES)
    assert p["parts_entrees"] == 40_000 and round(p["prix_part"], 2) == 12.5
    # Cash remis aux investisseurs : sort de la VAN, revient par part, compte dans le rendement de la part.
    p = pf.partager_annee(10_000_000, 0.0, 1_500_000, 1_000_000, 0.0, REGLES, distributions=500_000)
    assert round(p["distribution_par_part"], 2) == 0.5 and round(p["prix_part"], 2) == 10.55 and round(p["rendement_part_pct"], 1) == 10.5
    assert abs(p["prix_part"] * p["parts_total"] - (10_000_000 + 1_500_000 - 500_000)) < 1.0


def test_prets_detention_simple_et_conditions_de_reference():
    # Prêt amorti : même solde que la formule canadienne de Prospection, service = 12 paiements.
    s = pf.simuler_pret({"solde": 500_000, "taux_pct": 5.0, "mois_restants": 300, "paiement_mensuel": 0, "composition": "semi"}, 3, REF)
    assert round(s[0]["solde"]) == round(solde_pret_canadien(500_000, 0.05, 25, 1))
    assert round(s[2]["solde"]) == round(solde_pret_canadien(500_000, 0.05, 25, 3))
    assert abs(s[0]["service"] - (s[0]["capital"] + s[0]["interets"])) < 0.01 and s[1]["capital"] > s[0]["capital"]
    # Intérêts seulement, converti à l'an 3 : solde plat puis amorti aux conditions de référence (pas son propre taux).
    io = pf.simuler_pret({"solde": 800_000, "taux_pct": 8.0, "mois_restants": 0, "paiement_mensuel": 0, "composition": "mensuelle",
                          "interet_seulement": True, "conversion_annee": 3}, 4, REF)
    assert io[0]["capital"] == 0 and io[1]["solde"] == 800_000 and round(io[0]["service"]) == 64_000 and io[1]["evenement"] is None
    assert io[2]["evenement"]["type"] == "conversion" and io[2]["evenement"]["taux_pct"] == 5.0
    assert io[2]["capital"] > 0 and round(io[2]["service"]) == round(12 * pf._pmt(800_000, 5.0, 300, "semi"))
    # Échéance du terme à la fin de l'an 1 : le prêt garde SON taux (dernier financement), amortissement restant ; ± incertitude.
    r = pf.simuler_pret({"solde": 500_000, "taux_pct": 3.0, "mois_restants": 300, "paiement_mensuel": 2_000, "composition": "semi",
                         "fin_terme_annee": 1}, 2, REF)
    assert r[1]["evenement"]["type"] == "renouvellement" and r[1]["evenement"]["taux_pct"] == 3.0 and r[1]["evenement"]["cash_sorti"] == 0
    assert round(r[1]["service"]) == round(12 * pf._pmt(r[0]["solde"], 3.0, 288, "semi"))
    r_prudent = pf.simuler_pret({"solde": 500_000, "taux_pct": 3.0, "mois_restants": 300, "paiement_mensuel": 2_000, "composition": "semi",
                                 "fin_terme_annee": 1}, 2, REF, variation=0.5)
    assert r_prudent[1]["evenement"]["taux_pct"] == 3.5 and r_prudent[1]["service"] > r[1]["service"]
    # Conditions de référence = moyenne pondérée des hypothèques conventionnelles ; sans aucune → repli dit clairement.
    ref = pf.conditions_moyennes({1: [{"solde": 1_000_000, "taux_pct": 4.0, "amortissement_mois": 300},
                                      {"solde": 1_000_000, "taux_pct": 6.0, "amortissement_mois": 360},
                                      {"solde": 500_000, "taux_pct": 8.0, "amortissement_mois": 0, "interet_seulement": True}]})
    assert ref["taux_pct"] == 5.0 and ref["amortissement_mois"] == 330 and ref["nb_prets"] == 2 and "moyenne pondérée" in ref["source"]
    assert pf.conditions_moyennes({})["taux_pct"] == pf.REPLI_PRET["taux_pct"] and "hypothèse" in pf.conditions_moyennes({})["source"]
    # Prêt déjà remboursé : rien.
    assert all(a["solde"] == 0 and a["service"] == 0 for a in pf.simuler_pret({"solde": 0, "taux_pct": 5.0, "mois_restants": 300}, 2, REF))


def test_refinancement_a_l_echeance_du_terme():
    """Terme échu à la fin de l'an 1, immeuble à 1 M$ : nouveau prêt à 75 % = 750 000 $, frais 1 %,
    cash sorti = 750 000 − 7 500 − solde ; le solde ne remonte jamais au-delà de 75 % de la valeur."""
    valeurs = [1_000_000.0] * 4
    refi = {"actif": True, "ltv_pct": 75.0, "frais_pct": 1.0, "cadence_ans": 5, "cash_remis": True}
    s = pf.simuler_pret({"solde": 500_000, "taux_pct": 4.0, "mois_restants": 300, "paiement_mensuel": 0, "composition": "semi",
                         "fin_terme_annee": 1}, 4, REF, valeurs=valeurs, refi=refi, cadence=5)
    ev = s[1]["evenement"]
    assert ev["type"] == "refinancement" and ev["nouveau_pret"] == 750_000 and ev["frais"] == 7_500
    assert round(ev["cash_sorti"], 2) == round(750_000 - 7_500 - s[0]["solde"], 2) and ev["taux_pct"] == 4.0
    assert s[1]["solde"] < 750_000 and s[1]["service"] > s[0]["service"] and s[2]["evenement"] is None
    # Pas de refi si l'immeuble n'est pas stabilisé, ni si le nouveau prêt ne dépasse pas le solde.
    s2 = pf.simuler_pret({"solde": 500_000, "taux_pct": 4.0, "mois_restants": 300, "fin_terme_annee": 1}, 2, REF, valeurs=valeurs, refi=refi,
                         stabilise=lambda n: False, cadence=5)
    assert s2[1]["evenement"]["type"] == "renouvellement" and s2[1]["evenement"]["cash_sorti"] == 0
    s3 = pf.simuler_pret({"solde": 900_000, "taux_pct": 4.0, "mois_restants": 300, "fin_terme_annee": 1}, 2, REF, valeurs=valeurs, refi=refi, cadence=5)
    assert s3[1]["evenement"]["type"] == "renouvellement" and s3[1]["solde"] < 900_000
    # Prêt sans terme connu : refi à la cadence (an 6), pas avant.
    s4 = pf.simuler_pret({"solde": 500_000, "taux_pct": 4.0, "mois_restants": 300}, 7, REF, valeurs=[1_000_000.0] * 7, refi=refi, cadence=5)
    assert all(a["evenement"] is None for a in s4[:5]) and s4[5]["evenement"]["type"] == "refinancement"


def _scenario():
    d = svc.scenario_defaut()
    d["annee"] = 2027
    d["fonds"]["cash"] = 50_000
    d["projection"]["horizon_annees"] = 5
    d["immeubles"] = [
        svc.immeuble_vide(nom="Stab", nb_logements=6, loyers_bruts_mensuels=6_000, valeur_rapport=800_000, taux_cap_pct=5.0, dette=500_000,
                          taxes_municipales=5_000, assurances=2_000, taux_dette_pct=4.0, amortissement_ans=25),
        # Acquisition le 1er avril 2027, en rénovation 24 mois, prêteur intérêts seulement (doc p. 12 : coût 1,5 M$, prêt 800 k$, mise 700 k$).
        svc.immeuble_vide(nom="Reno", phase="stabilisation", acquisition_cette_annee=True, date_acquisition="2027-04-01", prix_acquisition=1_000_000,
                          travaux_initiaux=380_000, frais_connexes=120_000, valeur_future=1_700_000, dette=800_000, mois_prevus=24,
                          loyers_bruts_mensuels=4_000, taux_cap_pct=5.0, interet_seulement=True),
        svc.immeuble_vide(nom="Hors fonds", dans_le_fonds=False, nb_logements=2, loyers_bruts_mensuels=2_000, valeur_rapport=300_000, taux_cap_pct=5.0),
    ]
    return d


def test_projection_du_fonds_detention_simple():
    d = _scenario()
    d["projection"]["refinancement"]["actif"] = False
    d["projection"]["refinancement"]["cash_remis"] = False
    d["projection"]["incertitude_points"] = 0
    out = pf.calculer_performance(d)
    assert out["annee_depart"] == 2027 and out["horizon"] == 5 and [a["annee"] for a in out["fonds"]["annees"]] == [2027, 2028, 2029, 2030, 2031]
    assert out["fonds"]["fourchette"] is None and out["fonds"]["sans_refi"] is None and "hypothèse" in out["reference_prets"]["source"]   # aucun prêt Kratos → repli dit
    stab, reno, hors = out["projets"]
    a1 = stab["annees"][0]
    assert stab["depart"]["equite"] == round(stab["depart"]["valeur"] - 500_000, 2) and a1["revenus_bruts"] == 72_000
    assert a1["valeur"] == round(a1["revenus_nets"] / 0.05, 2) and a1["cash_flow"] == round(a1["revenus_nets"] - a1["service_dette"], 2)
    assert any("conditions de la fiche, 4 % sur 25 ans" in n for n in stab["notes"])
    assert stab["annees"][1]["revenus_bruts"] == round(72_000 * 1.03, 2) and a1["solde"] < 500_000 and stab["sommaire"]["tri_pct"] > 0
    r1, r2, r3 = reno["annees"][:3]
    assert reno["acquise_cette_annee"] is True and reno["depart"]["equite"] == 700_000 and reno["annee_stabilisation"] == 2028
    assert r1["en_renovation"] is True and 75 < r1["prorata"] < 76 and r1["valeur"] == 1_600_000 and r1["capital_rembourse"] == 0
    assert r2["en_renovation"] is False and r2["valeur"] == 1_700_000 and r2["revenus_nets"] == 85_000 and r2["solde"] == 800_000
    assert r3["evenements"][0]["type"] == "conversion" and r3["capital_rembourse"] > 0 and r3["solde"] < 800_000 and r3["valeur"] == round(1_700_000 * 1.03, 2)
    assert hors["dans_le_fonds"] is False and hors["sommaire"]["tri_pct"] is not None
    f = out["fonds"]
    s = f["sommaire"]
    assert s["nb_immeubles"] == 2 and s["nb_hors_fonds"] == 1 and s["nb_acquisitions_an1"] == 1 and s["nb_refinancements"] == 0
    assert s["van_depart"] == round(stab["depart"]["equite"] + 50_000, 2) and s["capital_entre"] == 700_000 and s["distributions_total"] == 0
    assert s["valeur_depart"] == stab["depart"]["valeur"] and s["dettes_depart"] == 500_000 and s["dettes_horizon"] == f["annees"][-1]["dettes"]
    y1 = f["annees"][0]
    assert y1["capital_entre"] == 700_000 and y1["van_debut"] == s["van_depart"] and y1["distributions"] == 0
    assert abs(y1["van"] - (y1["valeur"] + y1["cash"] - y1["dettes"])) < 0.02
    assert abs(y1["gain"] - (y1["van"] - y1["van_debut"] - 700_000)) < 0.02
    src = y1["sources"]
    assert abs(src["plus_value"] + src["capital_rembourse"] + src["cash"] - y1["gain"]) < 0.05
    assert y1["frais_fonds"] == round((s["van_depart"] + 700_000) * 0.015, 2) and y1["cash"] == round(50_000 + y1["cash_flow"] - y1["frais_fonds"], 2)
    assert y1["rendement_pct"] == round(100 * y1["gain"] / (s["van_depart"] + 700_000), 2)
    for a in f["annees"]:
        assert abs(a["prix_part"] * a["parts_total"] - a["van"]) <= 0.005 * a["parts_total"] + 1
    pcts = [a["pct_nous"] for a in f["annees"]]
    assert pcts == sorted(pcts) and pcts[0] > 0 and s["pct_nous_horizon"] == pcts[-1]
    assert s["van_horizon"] == f["annees"][-1]["van"] and s["tri_pct"] is not None and s["rendement_moyen_pct"] is not None
    assert abs(s["gain_total"] - sum(a["gain"] for a in f["annees"])) < 0.1


def test_projection_avec_refinancements_cash_remis_et_fourchette():
    d = _scenario()
    # Le prêt du stabilisé a un terme qui finit à la fin de l'an 2 → refi à l'an 3 à 75 % de la valeur.
    d["projection"]["refinancement"] = {"actif": True, "ltv_pct": 75.0, "frais_pct": 1.0, "cadence_ans": 5, "cash_remis": True}
    d["projection"]["incertitude_points"] = 0.5
    out = pf.calculer_performance(d)
    stab, reno = out["projets"][:2]
    # Stabilisé sans terme connu (dette de la fiche) : refi à la cadence (an 6) seulement → aucun sur 5 ans.
    assert stab["sommaire"]["nb_refinancements"] == 0
    # Rénovation : à la stabilisation (an 3), le prêt intérêts seulement est refinancé à 75 % de la valeur de fin d'an 2.
    ev = reno["annees"][2]["evenements"][0]
    assert ev["type"] == "refinancement" and ev["valeur"] == reno["annees"][1]["valeur"] and ev["nouveau_pret"] == round(0.75 * ev["valeur"], 2)
    assert ev["cash_sorti"] == round(ev["nouveau_pret"] - ev["frais"] - 800_000, 2) and reno["annees"][2]["cash_refi"] == ev["cash_sorti"]
    assert reno["sommaire"]["nb_refinancements"] == 1 and reno["sommaire"]["cash_refi_cumule"] == ev["cash_sorti"]
    f = out["fonds"]
    s = f["sommaire"]
    y3 = f["annees"][2]
    # Cash remis : le cash de l'année et le cash du refi sont distribués ; la réserve de départ reste ; gain compte la distribution.
    assert y3["distributions"] == round(y3["cash_refi"] + max(y3["cash_net"], 0), 2) and y3["cash_refi"] == ev["cash_sorti"]
    assert all(a["cash"] == 50_000 for a in f["annees"] if a["cash_net"] >= 0)
    assert abs(y3["gain"] - (y3["van"] - y3["van_debut"] + y3["distributions"])) < 0.02
    assert abs(y3["prix_part"] * y3["parts_total"] - y3["van"]) <= 0.005 * y3["parts_total"] + 1
    assert y3["distribution_par_part"] > 0 and s["distributions_total"] == round(sum(a["distributions"] for a in f["annees"]), 2)
    assert s["nb_refinancements"] == 1 and s["cash_remis"] is True and s["distributions_par_part"] > 0
    # Rendement d'une part = TRI des flux de l'investisseur (prix de départ, cash remis par part, prix à l'horizon).
    assert s["valeur_totale_par_part"] == round(s["prix_part_horizon"] + s["distributions_par_part"], 2)
    flux_part = [-10.0] + [a["distribution_par_part"] for a in f["annees"]]
    flux_part[-1] += s["prix_part_horizon"]
    assert s["rendement_part_annualise_pct"] == pf._irr(flux_part) and s["rendement_part_annualise_pct"] > 0
    # Comparaison sans refinancement : moins de dette à l'horizon, VAN plus haute, rien de sorti aux refis.
    sr = f["sans_refi"]
    assert sr["nb_refinancements"] == 0 and sr["dettes_horizon"] < s["dettes_horizon"] and sr["van_horizon"] > s["van_horizon"]
    assert sr["distributions_total"] < s["distributions_total"]
    # Fourchette : prudent (cap et taux + 0,5 pt) < central < favorable.
    fo = f["fourchette"]
    assert fo["points"] == 0.5 and fo["prudent"]["van_horizon"] < s["van_horizon"] < fo["favorable"]["van_horizon"]
    assert fo["prudent"]["tri_pct"] < s["tri_pct"] < fo["favorable"]["tri_pct"]
    # Cash gardé : rien de distribué, le cash s'accumule, même VAN d'horizon à l'écart des distributions.
    d["projection"]["refinancement"]["cash_remis"] = False
    out2 = pf.calculer_performance(d)
    s2 = out2["fonds"]["sommaire"]
    assert s2["distributions_total"] == 0 and s2["cash_horizon"] > 50_000
    assert abs(s2["van_horizon"] - (s["van_horizon"] + s["distributions_total"])) < 0.1 * s["distributions_total"]   # écart = frais du fonds sur le cash gardé


def test_normalisation_de_la_section_projection():
    d = svc.normaliser({"projection": {"horizon_annees": 0, "croissance_loyers_pct": "2.5", "part_nos_holdings_depart_pct": 250,
                                       "incertitude_points": 50, "refinancement": {"ltv_pct": 120, "cadence_ans": -2, "cash_remis": False}}})
    p = d["projection"]
    assert p["horizon_annees"] == 10 and p["croissance_loyers_pct"] == 2.5 and p["part_nos_holdings_depart_pct"] == 100
    assert p["incertitude_points"] == 10 and p["refinancement"] == {"actif": True, "ltv_pct": 95.0, "frais_pct": 1.0, "cadence_ans": 0, "cash_remis": False}
    assert "taux_dette_defaut_pct" not in p and "taux_renouvellement_pct" not in p and "taux_cap_sortie_pct" not in p
    assert svc.normaliser({})["projection"] == svc.PROJECTION_DEFAUT
    assert svc.normaliser({"projection": {"horizon_annees": 99}})["projection"]["horizon_annees"] == 30
    i = svc.normaliser({"immeubles": [{"nom": "x", "loyers_stabilises_mensuels": 5000, "taux_dette_pct": 4.5, "amortissement_ans": 30, "interet_seulement": True}]})["immeubles"][0]
    assert i["loyers_stabilises_mensuels"] == 5000 and i["taux_dette_pct"] == 4.5 and i["amortissement_ans"] == 30 and i["interet_seulement"] is True
    assert "refinancement" in svc.referentiel()["projection_note"].lower() or "Refinancement" in svc.referentiel()["projection_note"]
