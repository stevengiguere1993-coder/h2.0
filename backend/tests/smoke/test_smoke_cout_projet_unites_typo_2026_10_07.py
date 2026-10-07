"""Smoke — Phil 2026-10-07 (3e retour) :
- une unité SUIT le loyer projeté de sa typologie tant qu'aucun montant
  ne lui est saisi (changer le loyer projeté dans Infos la met à jour) ;
- « Coût du projet » : coût total = prix réel + tous les frais (prix de
  revente pour revenir à 0 $), cash total nécessaire = MDF nette + frais
  payés cash — cohérent pour les quatre stratégies, dans la trace et le PDF.
"""
from __future__ import annotations

import json

from app.models.lead_analysis import LeadAnalysis
from app.services.lead_analysis_finance import (
    FinanceInputs,
    compute_all,
    normaliser_unites,
)
from app.services.lead_analysis_trace import construire_trace

from tests.smoke.conftest import TestSessionLocal


def _inputs(**kw) -> FinanceInputs:
    base = dict(
        adresse="123 rue Test",
        prix_achat=1_000_000.0,
        nombre_logements=3,
        revenus_annuels=(950.0 + 1_100.0 + 1_200.0) * 12.0,
        taxes_municipales=10_000.0,
        taxes_scolaires=800.0,
        assurances=4_000.0,
        energie=0.0,
        depenses_autres=0.0,
        tga=0.04,
        taux_interet_achat=0.04,
        taux_interet_refi=0.04,
        typologie={"3.5": 1, "4.5": 1, "5.5": 1},
        typologie_prix={"3.5": 1_400.0, "4.5": 1_600.0, "5.5": 1_800.0},
        duree_projet_annees=2,
        chantier_actif=True,
        croissance_loyers=0.03,
        croissance_depenses=0.02,
        projection_horizon_annees=5,
    )
    base.update(kw)
    return FinanceInputs(**base)


def test_unite_suit_la_typologie_sauf_montant_saisi():
    prix = {"4.5": 1_450.0}
    u = normaliser_unites(
        [
            {"typo": "4.5", "loyer_actuel": 900, "loyer_optimise": None, "mode": "post_achat"},
            {"typo": "4.5", "loyer_actuel": 900, "loyer_optimise": "", "mode": "post_achat"},
            {"typo": "4.5", "loyer_actuel": 900, "loyer_optimise": 0, "mode": "post_achat"},
            {"typo": "4.5", "loyer_actuel": 900, "loyer_optimise": 1_500, "mode": "post_achat"},
            # Ancien format : la cible saisie fait foi.
            {"typo": "4.5", "loyer_actuel": 900, "loyer_cible": 1_300, "optimiser": True},
            # Typologie inconnue → repli sur la cible, sinon 0.
            {"typo": "6.5", "loyer_actuel": 900, "loyer_optimise": None, "loyer_cible": 1_700, "mode": "post_achat"},
        ],
        typologie_prix=prix,
    )
    assert [x["loyer_optimise"] for x in u] == [1_450.0, 1_450.0, 1_450.0, 1_500.0, 1_300.0, 1_700.0]
    assert [x["suit_typologie"] for x in u] == [True, True, True, False, False, False]

    # Dans le moteur : changer le loyer projeté change le refi des unités
    # qui suivent, pas celui de l'unité fixée.
    unites = [
        {"typo": "3.5", "loyer_actuel": 950, "loyer_optimise": None, "mode": "post_achat"},
        {"typo": "4.5", "loyer_actuel": 1_100, "loyer_optimise": 1_500, "mode": "post_achat"},
        {"typo": "5.5", "loyer_actuel": 1_200, "loyer_optimise": None, "mode": "pre_achat"},
    ]
    r1 = compute_all(_inputs(strategie="traditionnel", unites=unites), use_aph_select=False).to_dict()
    uc1 = r1["unites_calcul"]
    assert [x["loyer_optimise"] for x in uc1["unites"]] == [1_400.0, 1_500.0, 1_800.0]
    assert [x["suit_typologie"] for x in uc1["unites"]] == [True, False, True]
    r2 = compute_all(
        _inputs(strategie="traditionnel", unites=unites,
                typologie_prix={"3.5": 1_500.0, "4.5": 1_700.0, "5.5": 1_900.0}),
        use_aph_select=False,
    ).to_dict()
    uc2 = r2["unites_calcul"]
    assert [x["loyer_optimise"] for x in uc2["unites"]] == [1_500.0, 1_500.0, 1_900.0]
    # Trace : mention du loyer projeté de la typologie.
    lignes = [l for s in construire_trace(compute_all(_inputs(strategie="traditionnel", unites=unites), use_aph_select=False)) for l in s["lignes"]]
    assert any("loyer projeté de la typologie" in (l["formule"] or "") for l in lignes if l["label"].startswith("Unité "))


def _verifie_cout(d: dict, attendu_strat: str):
    c = d["cout_projet"]
    assert c["strategie"] == attendu_strat
    assert abs(c["verification"]) < 1.0, c
    assert abs(c["dette_totale"] + c["cash_total"] - c["cout_total"]) < 1.0
    assert abs(c["cout_total"] - (c["prix_reel"] + c["frais_total"] + c["prime_assurance"])) < 0.01
    assert abs(c["cash_total"] - (c["mdf_nette"] + c["frais_cash"])) < 0.01
    assert abs(c["frais_total"] - (c["frais_cash"] + c["frais_finances"])) < 0.01
    return c


def test_cout_projet_quatre_strategies():
    # Prêteur B : coût total = prix d'acquisition, cash = MDF prêteur B,
    # prêt = prêt B total (frais financés inclus).
    d = compute_all(_inputs(), use_aph_select=False).to_dict()
    c = _verifie_cout(d, "preteur_b")
    assert c["cout_total"] == round(d["prix_acquisition"], 2)
    assert c["cash_total"] == round(d["mdf_preteur_b"], 2)
    assert c["pret"] == round(d["pret_preteur_b"]["total"], 2)
    assert c["frais_finances_hors_pret"] == 0.0

    # Institution traditionnelle.
    d = compute_all(_inputs(strategie="traditionnel"), use_aph_select=False).to_dict()
    c = _verifie_cout(d, "traditionnel")
    t = d["traditionnel"]
    assert c["cout_total"] == t["total_depense"]
    assert c["cash_total"] == t["mdf_cash"]
    assert c["pret"] == t["pret_retenu"]

    # Assumation.
    d = compute_all(
        _inputs(strategie="assumation", assume_solde=600_000.0, assume_taux=0.03,
                assume_amort_depart_annees=25, assume_annees_ecoulees=3,
                assume_terme_restant_annees=2),
        use_aph_select=False,
    ).to_dict()
    c = _verifie_cout(d, "assumation")
    assert c["pret"] == d["traditionnel"]["pret_retenu"]

    # Résidentiel : la prime d'assurance financée (ratio > 80 %) entre dans
    # le coût total et le prêt affiché est le prêt total.
    d = compute_all(_inputs(strategie="residentiel", ltv_residentiel=0.95), use_aph_select=False).to_dict()
    c = _verifie_cout(d, "residentiel")
    res = d["residentiel"]
    assert c["prime_assurance"] == res["prime_assurance"] > 0
    assert c["pret"] == res["pret_total"]
    assert c["cash_total"] == res["mdf_cash"]
    assert c["cout_total"] == round(res["total_depense"] + res["prime_assurance"], 2)

    # Trace : section « Coût du projet » présente avec les deux totaux.
    trace = construire_trace(compute_all(_inputs(), use_aph_select=False))
    sec = next(s for s in trace if s["titre"].startswith("6b · Coût du projet"))
    labels = [l["label"] for l in sec["lignes"]]
    assert any(l.startswith("= Coût total du projet") for l in labels)
    assert any(l.startswith("+ Cash total nécessaire") for l in labels)


def _mk_fiche(run) -> int:
    async def _create():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="456 rue du Coût",
                city="Montréal",
                asking_price=1_000_000,
                nb_logements=3,
                typology_json=json.dumps({"3.5": 1, "4.5": 1, "5.5": 1}),
                revenus_bruts=(950 + 1_100 + 1_200) * 12,
                taxes_municipales=10_000,
                taxes_scolaires=800,
                assurances=4_000,
                energie=0,
                depenses_autres=0,
                loyers_projetes_json=json.dumps({"3.5": 1400, "4.5": 1600, "5.5": 1800}),
                taux_interet_refi_pct=4.0,
                tga_pct=4.0,
                duree_projet_annees=2,
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    return run(_create())


def test_api_unites_null_suivent_la_typologie_et_pdf(client, auth_headers, run):
    fid = _mk_fiche(run)
    base = f"/api/v1/lead-analyses/{fid}"
    unites = [
        {"typo": "3.5", "loyer_actuel": 950, "loyer_optimise": None, "loyer_cible": None, "mode": "post_achat"},
        {"typo": "4.5", "loyer_actuel": 1100, "loyer_optimise": 1500, "loyer_cible": 1500, "mode": "post_achat"},
        {"typo": "5.5", "loyer_actuel": 1200, "loyer_optimise": None, "loyer_cible": None, "mode": "aucune"},
    ]
    r = client.patch(base, headers=auth_headers, json={"strategie_acquisition": "traditionnel", "unites_json": json.dumps(unites)})
    assert r.status_code == 200, r.text
    r = client.post(f"{base}/run-financial-analysis", headers=auth_headers)
    assert r.status_code == 200, r.text
    res = r.json()["analysis_results"]
    assert [u["loyer_optimise"] for u in res["unites_calcul"]["unites"]] == [1400.0, 1500.0, 1800.0]
    assert res["cout_projet"]["strategie"] == "traditionnel"
    assert abs(res["cout_projet"]["verification"]) < 1.0
    # Loyer projeté changé dans Infos → l'unité qui suit bouge, pas l'autre.
    r = client.patch(base, headers=auth_headers, json={"loyers_projetes_json": json.dumps({"3.5": 1450, "4.5": 1700, "5.5": 1800})})
    assert r.status_code == 200, r.text
    r = client.post(f"{base}/run-financial-analysis", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert [u["loyer_optimise"] for u in r.json()["analysis_results"]["unites_calcul"]["unites"]] == [1450.0, 1500.0, 1800.0]
    for strat in ("preteur_b", "residentiel"):
        r = client.patch(base, headers=auth_headers, json={"strategie_acquisition": strat})
        assert r.status_code == 200, r.text
        r = client.post(f"{base}/run-financial-analysis", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["analysis_results"]["cout_projet"]["strategie"] == strat
    r = client.get(f"{base}/pdf", headers=auth_headers)
    assert r.status_code == 200, r.text
