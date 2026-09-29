"""Smoke — Prospection (Phil 2026-09-29) :

1. Prêteur B : le frais de dossier (même %) se calcule sur TOUT le prêt du
   prêteur B — la bâtisse ((1 − MDF) × prix) ET la portion financée des
   frais finançables (travaux, frais connexes). Override de fiche gardé.
2. 4e stratégie « Assumation hypothécaire » : comme l'institution
   traditionnelle, sauf le prêt initial = solde repris (taux,
   amortissement restant → paiement ; terme restant = information) ;
   mise de fonds = prix − solde.
"""
from __future__ import annotations

import json

from app.models.lead_analysis import LeadAnalysis
from app.services.lead_analysis_finance import (
    FinanceInputs,
    compute_all,
    pmt_canadian,
    solde_pret_canadien,
)
from app.services.lead_analysis_trace import construire_trace

from tests.smoke.conftest import TestSessionLocal


def _inputs(**kw) -> FinanceInputs:
    base = dict(
        adresse="123 rue Test",
        prix_achat=1_000_000.0,
        nombre_logements=10,
        revenus_annuels=100_000.0,
        taxes_municipales=10_000.0,
        taxes_scolaires=800.0,
        assurances=4_000.0,
        energie=0.0,
        depenses_autres=0.0,
        tga=0.04,
        taux_interet_achat=0.04,
        taux_interet_refi=0.04,
        typologie={"3.5": 10},
        typologie_prix={"3.5": 1_200.0},
        duree_projet_annees=2,
    )
    base.update(kw)
    return FinanceInputs(**base)


# ───────────── 1. frais de dossier du prêteur B ─────────────

def test_frais_dossier_preteur_b_sur_le_pret_complet():
    # Sans frais finançable, MDF 25 % : 2 % × 75 % × prix (inchangé).
    r0 = compute_all(_inputs(mdf_preteur_b_pct=0.25), use_aph_select=False)
    assert round(r0.frais_demarrage.frais_dossier_preteur, 2) == 15_000.0

    # 200 000 $ de travaux finançables, MDF 20 % : prêt B = 800 000 $ sur
    # la bâtisse + 160 000 $ sur les travaux → frais = 2 % × 960 000 $.
    r = compute_all(
        _inputs(
            mdf_preteur_b_pct=0.20,
            frais_travaux=200_000.0,
            frais_demarrage_financables=["frais_travaux"],
        ),
        use_aph_select=False,
    )
    assert round(r.pret_preteur_b_total, 2) == 960_000.0
    assert round(r.frais_demarrage.frais_dossier_preteur, 2) == 19_200.0
    base = r.frais_dossier_preteur_base
    assert base["pret_batisse"] == 800_000.0 and base["frais_finances"] == 160_000.0

    # La trace montre la nouvelle formule.
    trace = construire_trace(r)
    lignes = [l for s in trace for l in s["lignes"] if l["label"] == "Frais de dossier du prêteur B"]
    assert lignes and "frais financés" in lignes[0]["formule"]

    # Un montant saisi sur la fiche garde le dernier mot.
    r2 = compute_all(
        _inputs(
            mdf_preteur_b_pct=0.20,
            frais_travaux=200_000.0,
            frais_demarrage_financables=["frais_travaux"],
            frais_demarrage_overrides={"frais_dossier_preteur": 1_234.0},
        ),
        use_aph_select=False,
    )
    assert r2.frais_demarrage.frais_dossier_preteur == 1_234.0
    assert r2.frais_dossier_preteur_base is None


# ───────────── 2. assumation hypothécaire ─────────────

def _assumation(**kw):
    return compute_all(
        _inputs(
            strategie="assumation",
            chantier_actif=True,
            projection_horizon_annees=5,
            croissance_loyers=0.03,
            croissance_depenses=0.03,
            assume_solde=600_000.0,
            assume_taux=0.03,
            assume_amort_restant_annees=20,
            assume_terme_restant_annees=3,
            **kw,
        ),
        use_aph_select=False,
    )


def test_assumation_hypothecaire_moteur():
    r = _assumation()
    t = r.to_dict()["traditionnel"]
    assert t["mode"] == "assumation"
    assert t["programme_retenu"] == "assumation"
    # Achat : une seule colonne, le prêt repris ; refinancement : les 4
    # programmes, comme en traditionnel.
    assert set(t["achat"]) == {"assumation"}
    assert set(t["refi"]) == {"conventionnel", "schl_std", "aph_50", "aph_100"}
    assert t["pret_retenu"] == 600_000.0
    assert t["achat"]["assumation"]["financement"] == 600_000.0

    # Paiement mensuel calculé sur le solde, le taux et l'amortissement
    # restant ; solde à l'an H au même taux.
    assert t["assumation"]["paiement_mensuel"] == round(
        pmt_canadian(0.03, 240, 600_000.0), 2
    )
    assert t["solde_retenu_an_h"] == round(
        solde_pret_canadien(600_000.0, 0.03, 20, 5), 2
    )
    assert t["projection"][0]["solde_pret"] == 600_000.0

    # Mise de fonds = prix − solde repris ; cash total = MDF nette + frais cash.
    d = t["detail_mdf_par_programme"]["assumation"]
    assert d["mdf_brute"] == 400_000.0
    assert t["mdf_cash"] == round(d["mdf_nette"] + d["frais_cash"], 2)

    # Frais : ceux du traditionnel (dossier fixe, courtier 1 sur le prêt
    # repris, pas de rapport d'efficacité).
    f = t["frais_demarrage"]
    assert f["frais_dossier_preteur"] == 5_000.0
    assert f["courtier_hypothecaire_1"] == 6_000.0
    assert f["rapport_efficacite"] == 0.0

    # Trace : section dédiée.
    titres = [s["titre"] for s in construire_trace(r)]
    assert any(ti.startswith("8 · Assumation hypothécaire") for ti in titres)


def test_assumation_balance_de_vente_et_refi():
    r = _assumation(balance_vente_montant=50_000.0, balance_vente_taux_pct=0.05)
    t = r.to_dict()["traditionnel"]
    d = t["detail_mdf_par_programme"]["assumation"]
    assert d["mdf_nette"] == 350_000.0  # 1 000 000 − 600 000 − 50 000
    # Dette à l'an H = solde du prêt repris + BV + frais roulés.
    assert t["dette_an_h"] == round(
        t["solde_retenu_an_h"] + 50_000.0 + t["frais_finances"], 2
    )
    assert t["best_refi"]["key"] in t["refi"]


def _mk_fiche(run) -> int:
    async def _create():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="789 rue Assumation",
                city="Montréal",
                asking_price=1_000_000,
                nb_logements=10,
                typology_json=json.dumps({"3.5": 10}),
                revenus_bruts=100_000,
                taxes_municipales=10_000,
                taxes_scolaires=800,
                assurances=4_000,
                energie=0,
                depenses_autres=0,
                loyers_projetes_json=json.dumps({"3.5": 1200}),
                taux_interet_refi_pct=4.0,
                tga_pct=4.0,
                duree_projet_annees=2,
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    return run(_create())


def test_parcours_api_assumation(client, auth_headers, run):
    fid = _mk_fiche(run)
    base = f"/api/v1/lead-analyses/{fid}"
    r = client.patch(
        base,
        headers=auth_headers,
        json={
            "strategie_acquisition": "assumation",
            "assume_solde": 600_000,
            "assume_taux_pct": 3.0,
            "assume_amort_restant_annees": 20,
            "assume_terme_restant_annees": 3,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["strategie_acquisition"] == "assumation"
    assert float(body["assume_solde"]) == 600_000.0
    assert float(body["assume_taux_pct"]) == 3.0

    r = client.post(f"{base}/run-financial-analysis", headers=auth_headers)
    assert r.status_code == 200, r.text
    t = r.json()["analysis_results"]["traditionnel"]
    assert t["mode"] == "assumation"
    assert t["pret_retenu"] == 600_000.0
    assert t["assumation"]["taux"] == 0.03

    r = client.get(f"{base}/pdf", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")

    # Valeur hors borne refusée.
    r = client.patch(base, headers=auth_headers, json={"assume_taux_pct": 45})
    assert r.status_code == 422
