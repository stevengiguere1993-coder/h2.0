"""Smoke — prêteur B : la référence de refinancement choisie à la main
(refi_retenu) pilote le verdict même sans stratégie explicite (fiche
« classique », chantier inactif) et même si elle est moins avantageuse
(Phil 2026-10-07 : « je veux pouvoir choisir le SCHL 50 pts »)."""
from __future__ import annotations

import json

from app.models.lead_analysis import LeadAnalysis
from app.services.lead_analysis_finance import FinanceInputs, compute_all

from tests.smoke.conftest import TestSessionLocal


def _inputs(**kw) -> FinanceInputs:
    base = dict(
        adresse="123 rue Test",
        prix_achat=1_000_000.0,
        nombre_logements=8,
        revenus_annuels=96_000.0,
        taxes_municipales=10_000.0,
        taxes_scolaires=800.0,
        assurances=4_000.0,
        energie=0.0,
        depenses_autres=0.0,
        tga=0.04,
        taux_interet_achat=0.04,
        taux_interet_refi=0.04,
        typologie={"4.5": 8},
        typologie_prix={"4.5": 1_400.0},
        duree_projet_annees=2,
    )
    base.update(kw)
    return FinanceInputs(**base)


def test_refi_retenu_pilote_le_verdict_sans_chantier():
    auto = compute_all(_inputs(), use_aph_select=False)
    d_auto = auto.to_dict()
    assert d_auto["projection_preteur_b"] is None  # pas de stratégie explicite
    # Chaque référence est respectée, même si elle n'est pas la meilleure.
    for cle, label in (
        ("refi_schl", "SCHL standard"),
        ("refi_aph_50", "SCHL Efficacité"),
    ):
        r = compute_all(_inputs(refi_retenu=cle), use_aph_select=False)
        assert label in r.best_refi_program, (cle, r.best_refi_program)
        scen = r.refi_schl if cle == "refi_schl" else r.refi_aph_50
        assert r.best_refi_amount == (scen.equite_a_la_fin or 0.0)
    # Une référence différente du meilleur automatique change bien le verdict.
    forcee = compute_all(_inputs(refi_retenu="refi_schl"), use_aph_select=False)
    assert forcee.best_refi_program != auto.best_refi_program or forcee.best_refi_amount == auto.best_refi_amount


def test_api_refi_retenu_sans_strategie(client, auth_headers, run):
    async def _create():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="12 rue du Refi", city="Montréal", asking_price=1_000_000, nb_logements=8,
                typology_json=json.dumps({"4.5": 8}), revenus_bruts=96_000, taxes_municipales=10_000,
                taxes_scolaires=800, assurances=4_000, energie=0, depenses_autres=0,
                loyers_projetes_json=json.dumps({"4.5": 1400}), taux_interet_refi_pct=4.0, tga_pct=4.0,
                duree_projet_annees=2,
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    fid = run(_create())
    base = f"/api/v1/lead-analyses/{fid}"
    r = client.post(f"{base}/run-financial-analysis", headers=auth_headers)
    assert r.status_code == 200, r.text
    res = r.json()["analysis_results"]
    assert res["projection_preteur_b"] is None and res["scenarios"]["refi_schl"]
    # Choix manuel → recalcul automatique → verdict sur SCHL standard.
    r = client.patch(base, headers=auth_headers, json={"refi_retenu": "refi_schl"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["refi_retenu"] == "refi_schl" and not d.get("recalc_error")
    assert "SCHL standard" in (d["best_refi_program"] or "")
    # Retour à l'automatique.
    r = client.patch(base, headers=auth_headers, json={"refi_retenu": None})
    assert r.status_code == 200, r.text
