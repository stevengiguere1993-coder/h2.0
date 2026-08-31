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
