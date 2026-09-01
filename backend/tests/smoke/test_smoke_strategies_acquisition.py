"""Smoke — chantier « stratégies d'acquisition » (phase 1, 2026-08-31).

Vérifie que les nouveaux intrants du moteur (stratégie, balance de
vente) sont rétrocompatibles au centime quand ils sont absents, et que
la balance de vente déplace correctement le prêt B et les intérêts de
portage (le cash à l'achat, lui, ne bouge pas).
"""
from __future__ import annotations

from app.services.lead_analysis_finance import FinanceInputs, compute_all


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


def test_defaut_retrocompatible():
    """Sans stratégie ni balance de vente : mêmes intérêts qu'avant
    ((1-MDF%) × prix × taux B × durée), bloc prêt B exposé."""
    r = compute_all(_inputs(), use_aph_select=False)
    assert r.frais_demarrage.interets == 0.75 * 1_000_000 * 0.08 * 2

    d = r.to_dict()
    assert d["strategie"] == "preteur_b"
    assert d["balance_vente"]["montant"] == 0.0
    # Prêt B sur le prix = (1 - 25 %) × prix ; aucun frais finançable
    # dans ce jeu d'intrants → total = sur_prix.
    assert d["pret_preteur_b"]["sur_prix"] == 750_000.0
    assert d["pret_preteur_b"]["total"] == 750_000.0


def test_balance_vente_deplace_le_pret_et_les_interets():
    """BV 200 k$ @ 6 % : le prêt B sur le prix descend à 550 k$, les
    intérêts de portage = 550k×8%×2 + 200k×6%×2, et le cash (MDF)
    reste identique au scénario sans BV."""
    sans_bv = compute_all(_inputs(), use_aph_select=False)
    avec_bv = compute_all(
        _inputs(balance_vente_montant=200_000.0, balance_vente_taux_pct=0.06),
        use_aph_select=False,
    )

    assert avec_bv.pret_preteur_b_sur_prix == 550_000.0
    assert avec_bv.balance_vente_retenue == 200_000.0
    attendu = 550_000 * 0.08 * 2 + 200_000 * 0.06 * 2
    assert abs(avec_bv.frais_demarrage.interets - attendu) < 0.01

    # Le cash à l'achat = MDF % × prix + frais cash : la BV réduit les
    # intérêts (donc les frais totaux), jamais le X % × prix.
    delta_interets = (
        sans_bv.frais_demarrage.interets - avec_bv.frais_demarrage.interets
    )
    assert delta_interets > 0
    assert abs(
        (sans_bv.mdf_preteur_b - avec_bv.mdf_preteur_b) - delta_interets
    ) < 0.01


def test_balance_vente_plafonnee_au_pret():
    """Une BV plus grosse que le prêt possible est plafonnée — jamais
    de prêt B négatif."""
    r = compute_all(
        _inputs(balance_vente_montant=2_000_000.0, balance_vente_taux_pct=0.05),
        use_aph_select=False,
    )
    assert r.pret_preteur_b_sur_prix == 0.0
    assert r.balance_vente_retenue == 750_000.0


def test_strategie_echo():
    r = compute_all(_inputs(strategie="conventionnel"), use_aph_select=False)
    assert r.to_dict()["strategie"] == "conventionnel"


def test_achat_direct_absent_en_mode_preteur_b():
    r = compute_all(_inputs(), use_aph_select=False)
    assert r.to_dict()["achat_direct"] is None


def test_achat_direct_conventionnel():
    """Phase 2 : achat direct conventionnel — financement à l'achat
    sur les loyers actuels, frais sans la phase chantier/refi,
    projection composée et verdict refi an N cohérents."""
    r = compute_all(
        _inputs(
            strategie="conventionnel",
            projection_horizon_annees=5,
            croissance_loyers=0.03,
            croissance_depenses=0.03,
        ),
        use_aph_select=False,
    )
    d = r.to_dict()["achat_direct"]
    assert d is not None
    assert d["label"] == "Conventionnel"
    # Prêt plafonné : jamais plus que LTV × prix demandé.
    assert d["pret_accorde"] <= 0.75 * 1_000_000 + 0.01

    # Frais : pas de 2e courtier/évaluateur/notaire, pas d'intérêts de
    # portage ni de revenus pendant projet, pas de rapport
    # d'efficacité en conventionnel.
    f = d["frais_demarrage"]
    for k in (
        "courtier_hypothecaire_2", "evaluateur_2", "notaire_2",
        "interets", "revenus_nets_pendant_projet", "rapport_efficacite",
    ):
        assert f[k] == 0.0, k
    # Mais les frais d'achat de base restent.
    assert f["taxes_bienvenue"] > 0
    assert f["notaire"] > 0

    # MDF cash = prix − prêt + frais (aucune balance de vente ici).
    attendu_mdf = 1_000_000 - d["pret_accorde"] + d["frais_demarrage_total"]
    assert abs(d["mdf_cash"] - attendu_mdf) < 0.01

    # Projection : croissance composée à 3 %.
    p0 = d["projection"][0]
    p1 = d["projection"][1]
    assert p0["revenus"] == 100_000.0
    assert abs(p1["revenus"] - 103_000.0) < 0.01
    # Le solde du prêt descend avec les années.
    p5 = d["projection"][5]
    assert p5["solde_pret"] < p0["solde_pret"]

    # Verdict refi an 5 : argent dispo = prêt max − solde, et le best
    # est bien le max des 3 programmes.
    refis = d["refi_an_h"]
    for v in refis.values():
        assert abs(
            (v["pret_max"] - d["solde_pret_an_h"]) - v["argent_dispo"]
        ) < 0.01
    best = d["best_refi"]
    assert best["argent_dispo"] == max(
        v["argent_dispo"] for v in refis.values()
    )
    assert best["refi_possible"] == (
        best["argent_dispo"] >= d["mdf_cash"] - 0.005
    )


def test_achat_direct_aph_garde_rapport_efficacite():
    r = compute_all(_inputs(strategie="aph_50"), use_aph_select=False)
    d = r.to_dict()["achat_direct"]
    assert d is not None
    # Le rapport d'efficacité est requis pour les programmes APH.
    assert d["frais_demarrage"]["rapport_efficacite"] > 0
    # APH 50 : LTV 0,85 / amort 40 ans.
    assert d["ltv"] == 0.85
    assert d["amort_annees"] == 40
