"""Smoke — Unités & optimisation, un mode PAR UNITÉ (Phil 2026-10-07, GO) :
non optimisée / pré-achat / post-achat, colonnes « À l'achat » et « Au
refi », revenus à l'achat = somme « À l'achat », post-achat = loyer
optimisé atteint à l'an H ; ancien format converti ; trace, PDF et API."""
from __future__ import annotations

import json

from app.models.lead_analysis import LeadAnalysis
from app.services.lead_analysis_finance import (
    FinanceInputs,
    compute_all,
    loyer_unite_annee,
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


UNITES = [
    {"typo": "3.5", "loyer_actuel": 950, "loyer_optimise": 0, "mode": "aucune"},
    {"typo": "4.5", "loyer_actuel": 1_100, "loyer_optimise": 1_450, "mode": "pre_achat"},
    {"typo": "5.5", "loyer_actuel": 1_200, "loyer_optimise": 1_700, "mode": "post_achat"},
]


def test_regles_par_unite():
    u = normaliser_unites(UNITES)
    g, h = 0.03, 5
    # Non optimisée : actuel, puis × (1+g)^a.
    assert loyer_unite_annee(u[0], 0, h, g) == 950
    assert abs(loyer_unite_annee(u[0], 5, h, g) - 950 * 1.03 ** 5) < 1e-9
    # Pré-achat : optimisé dès l'achat, puis × (1+g)^a.
    assert loyer_unite_annee(u[1], 0, h, g) == 1_450
    assert abs(loyer_unite_annee(u[1], 5, h, g) - 1_450 * 1.03 ** 5) < 1e-9
    # Post-achat : actuel à l'achat, optimisé atteint exactement à l'an H,
    # croît avant (depuis l'an 1) et après.
    assert loyer_unite_annee(u[2], 0, h, g) == 1_200
    assert abs(loyer_unite_annee(u[2], 5, h, g) - 1_700) < 1e-9
    assert abs(loyer_unite_annee(u[2], 3, h, g) - 1_700 / 1.03 ** 2) < 1e-9
    assert abs(loyer_unite_annee(u[2], 7, h, g) - 1_700 * 1.03 ** 2) < 1e-9


def test_conversion_ancien_format():
    anciennes = [
        {"typo": "3.5", "loyer_actuel": 900, "loyer_cible": 1_300, "optimiser": True},
        {"typo": "3.5", "loyer_actuel": 900, "loyer_cible": 1_300, "optimiser": False},
    ]
    post = normaliser_unites(anciennes, optimisation_pre_achat=False)
    pre = normaliser_unites(anciennes, optimisation_pre_achat=True)
    assert [x["mode"] for x in post] == ["post_achat", "aucune"]
    assert [x["mode"] for x in pre] == ["pre_achat", "aucune"]
    assert post[0]["loyer_optimise"] == 1_300.0


def test_traditionnel_colonnes_achat_et_refi():
    r = compute_all(_inputs(strategie="traditionnel", unites=UNITES), use_aph_select=False)
    d = r.to_dict()
    uc = d["unites_calcul"]
    assert uc["h"] == 5 and uc["g"] == 0.03
    assert uc["modes"] == {"aucune": 1, "pre_achat": 1, "post_achat": 1}
    # Colonne « À l'achat » : 950 (actuel) + 1 450 (pré-achat) + 1 200 (actuel).
    assert uc["total_achat_mois"] == 3_600.0
    assert uc["revenus_achat"] == 3_600.0 * 12
    # Colonne « Au refi » (an 5) : 950 × 1,03^5 + 1 450 × 1,03^5 + 1 700.
    attendu_refi = 950 * 1.03 ** 5 + 1_450 * 1.03 ** 5 + 1_700
    assert abs(uc["total_refi_mois"] - attendu_refi) < 0.01
    t = d["traditionnel"]
    assert t["unites_modes"] == uc["modes"]
    # Les scénarios utilisent exactement ces totaux.
    assert abs(t["revenus_achat"] - 3_600.0 * 12) < 0.01
    assert abs(t["achat"]["conventionnel"]["revenus_totaux"] - 3_600.0 * 12) < 0.01
    assert abs(t["refi"]["conventionnel"]["revenus_totaux"] - attendu_refi * 12) < 0.01
    # Projection : an 0 = achat ; an 5 = refi ; an 3 = post-achat en route.
    assert abs(t["projection"][0]["revenus"] - 3_600.0 * 12) < 0.01
    assert abs(t["projection"][5]["revenus"] - attendu_refi * 12) < 0.01
    an3 = (950 * 1.03 ** 3 + 1_450 * 1.03 ** 3 + 1_700 / 1.03 ** 2) * 12
    assert abs(t["projection"][3]["revenus"] - an3) < 0.01
    # Écart avec les revenus de la fiche (3 250 $/mois) affiché, pas caché.
    assert uc["ecart_achat_vs_fiche"] == 350.0 * 12
    # Trace : la ligne des unités et les trois modes.
    lignes = [l for s in construire_trace(r) for l in s["lignes"]]
    assert any("1 non optimisée(s), 1 pré-achat, 1 post-achat" in str(l["valeur_txt"]) for l in lignes)
    assert sum(1 for l in lignes if l["label"].startswith("Unité #")) == 3


def test_preteur_b_refi_selon_le_mode():
    r = compute_all(_inputs(unites=UNITES), use_aph_select=False)
    # Refi après 2 ans de projet : 950 × 1,03² + 1 450 × 1,03² + 1 700.
    attendu = (950 * 1.03 ** 2 + 1_450 * 1.03 ** 2 + 1_700) * 12
    assert abs(r.refi_schl.revenus_totaux - attendu) < 0.01
    # Achat : colonne « À l'achat ».
    assert abs(r.achat.revenus_totaux - 3_600.0 * 12) < 0.01
    uc = r.to_dict()["unites_calcul"]
    assert uc["h"] == 2 and abs(uc["revenus_refi"] - attendu) < 0.01


def test_residentiel_actuel_optimise_achat():
    r = compute_all(
        _inputs(strategie="residentiel", unites=UNITES, ltv_residentiel=0.8),
        use_aph_select=False,
    )
    res = r.to_dict()["residentiel"]
    assert abs(res["revenus_actuels"] - (950 + 1_100 + 1_200) * 12) < 0.01
    assert abs(res["revenus_optimises"] - (950 + 1_450 + 1_700) * 12) < 0.01
    assert res["unites_modes"] == {"aucune": 1, "pre_achat": 1, "post_achat": 1}


def _mk_fiche(run) -> int:
    async def _create():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="321 rue des Modes",
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


def test_api_unites_v2_et_pdf(client, auth_headers, run):
    fid = _mk_fiche(run)
    base = f"/api/v1/lead-analyses/{fid}"
    r = client.patch(
        base, headers=auth_headers,
        json={
            "strategie_acquisition": "traditionnel",
            "projection_horizon_annees": 5,
            "unites_json": json.dumps(UNITES),
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(f"{base}/run-financial-analysis", headers=auth_headers)
    assert r.status_code == 200, r.text
    res = r.json()["analysis_results"]
    assert res["unites"]["total"] == 3 and res["unites"]["pre_achat"] == 1
    assert res["unites_calcul"]["total_achat_mois"] == 3_600.0
    assert abs(res["traditionnel"]["revenus_achat"] - 3_600.0 * 12) < 0.01
    # PDF = reflet de la fiche, pour les trois branches (trad / B / résid.).
    for strat in ("traditionnel", "preteur_b", "residentiel"):
        r = client.patch(base, headers=auth_headers, json={"strategie_acquisition": strat})
        assert r.status_code == 200, r.text
        r = client.post(f"{base}/run-financial-analysis", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["analysis_results"]["unites_calcul"]["modes"]["post_achat"] == 1
        r = client.get(f"{base}/pdf", headers=auth_headers)
        assert r.status_code == 200, (strat, r.text)
        assert r.headers["content-type"].startswith("application/pdf")
