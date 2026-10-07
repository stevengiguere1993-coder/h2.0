"""Smoke — le JSON des résultats d'analyse est stocké ENTIER et toujours
valide (Phil 2026-10-07, fiche 35-Plateau : « après avoir cliqué sur
Lancer l'analyse, rien ne se produit »).

Cause : ``json.dumps(results)[:80_000]`` — avec 35 unités détaillées, le
coût du projet et la trace, le JSON dépassait 80 000 caractères, était
amputé, donc invalide : la fiche ne lisait plus rien (tuiles à « — »,
bouton sans effet). Vérifie aussi que NaN / Infinity deviennent null.
"""
from __future__ import annotations

import json
import math

from app.api.v1.endpoints import lead_analyses as ep
from app.models.lead_analysis import LeadAnalysis

from tests.smoke.conftest import TestSessionLocal


def test_nettoyage_non_finis():
    trouves: list = []
    propre = ep._nettoyer_json(
        {"a": float("nan"), "b": [1.0, float("inf"), {"c": float("-inf")}], "d": 2.5, "e": "x"},
        trouves=trouves,
    )
    assert propre == {"a": None, "b": [1.0, None, {"c": None}], "d": 2.5, "e": "x"}
    assert trouves == ["a", "b[1]", "b[2].c"]
    texte = ep._serialiser_resultats({"x": float("nan"), "y": 1})
    assert json.loads(texte) == {"x": None, "y": 1}


def _unites(n: int) -> list:
    typos = ["4.5", "3.5", "2.5", "8.5", "1.5", "", "5.5"]
    out = []
    for i in range(n):
        out.append({
            "typo": typos[i % len(typos)],
            "numero": f"App. {i + 1}",
            "loyer_actuel": 850 + 17 * (i % 23),
            "loyer_optimise": None if i % 5 else 1_600,
            "loyer_cible": None if i % 5 else 1_600,
            "mode": "pre_achat" if i % 7 == 0 else "aucune",
            "optimiser": i % 7 == 0,
        })
    return out


def test_grosse_fiche_resultats_entiers_et_valides(client, auth_headers, run):
    async def _create():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="35-Plateau (test)", city="Montréal", asking_price=7_100_000, nb_logements=60,
                typology_json=json.dumps({"2.5": 6, "3.5": 25, "4.5": 24, "5.5": 4, "8.5": 1}),
                revenus_bruts=800_000, taxes_municipales=31_796, taxes_scolaires=3_564, assurances=33_000, energie=7_900,
                loyers_projetes_json=json.dumps({"2.5": 1350, "3.5": 1650, "4.5": 1946, "5.5": 2300, "8.5": 3000}),
                loyers_max_abordabilite_json=json.dumps({"abordable": 1090}),
                travaux_estimes=500_000, frais_developpement=500_000, ajout_wifi=True,
                taux_interet_refi_pct=4.4, taux_interet_achat_pct=4.4, tga_pct=4.0, duree_projet_annees=2,
                unites_json=json.dumps(_unites(60)),
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    fid = run(_create())
    base = f"/api/v1/lead-analyses/{fid}"
    r = client.patch(base, headers=auth_headers, json={
        "strategie_acquisition": "traditionnel", "programme_achat": "aph_50", "projection_horizon_annees": 5,
        "tri_croissance_loyers": 0.03, "tri_croissance_depenses": 0.03,
        "balance_vente_montant": 2_000_000, "balance_vente_taux_pct": 4.0,
    })
    assert r.status_code == 200, r.text
    r = client.post(f"{base}/run-financial-analysis", headers=auth_headers)
    assert r.status_code == 200, r.text
    d = client.get(base, headers=auth_headers).json()
    stocke = d["analysis_results_json"]
    # Plus gros que l'ancienne limite de 80 000 caractères, et pourtant lisible.
    assert len(stocke) > 80_000, len(stocke)
    res = json.loads(stocke)
    t = res["traditionnel"]
    ref = t["refi"][t["best_refi"]["key"]]
    assert math.isfinite(ref["financement"]) and math.isfinite(t["mdf_cash"])
    assert len(res["unites_calcul"]["unites"]) == 60
    assert res["cout_projet"]["cout_total"] > 0
    # Le tableau de bord lit ces champs : tous présents.
    assert d["best_refi_amount"] is not None and d["best_refi_program"]
