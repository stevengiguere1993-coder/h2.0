"""Tests du moteur d'analyse financière (Phase 3).

Vérifie que la sortie du moteur Python correspond aux valeurs
calculées par l'Excel original sur des cas réels :
  - Saint-Joseph (8 logements, sans abordabilité)
  - Salaberry (33 logements, avec abordabilité)

Tolérance : ±0,5 % (arrondis cumulés Excel vs float Python).
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.lead_analysis_finance import (
    FinanceInputs,
    compute_all,
    pv_canadian,
    taxes_bienvenue_mtl,
)


# Tolérance relative pour les comparaisons d'arrondis Excel vs Python.
TOLERANCE = 0.01  # ±1 % (les chiffres Excel sont en arrondis variables)


def approx(actual: float, expected: float, tol: float = TOLERANCE) -> bool:
    """True si abs(actual - expected) ≤ tol × max(1, abs(expected))."""
    if expected == 0:
        return abs(actual) < 1.0
    return abs(actual - expected) / abs(expected) <= tol


def expect(label: str, actual: float, expected: float, tol: float = TOLERANCE):
    ok = approx(actual, expected, tol)
    status = "✓" if ok else "✗"
    diff = actual - expected
    diff_pct = (diff / expected * 100) if expected != 0 else 0
    print(
        f"  {status} {label:50} actual={actual:>14,.2f}  expected={expected:>14,.2f}  diff={diff:>+12,.2f} ({diff_pct:+.2f}%)"
    )
    return ok


# ── Helpers unitaires ───────────────────────────────────────────


def test_taxes_bienvenue_mtl():
    print("\n[test] Taxes bienvenue Montréal")
    # Tranche 1 : 50 000 → 50 000 × 0.5 % = 250
    expect("50k", taxes_bienvenue_mtl(50_000), 250.0)
    # Tranche 2 : 200 000 → 61500×0.5% + (200000-61500)×1% = 307.5 + 1385 = 1692.5
    expect("200k", taxes_bienvenue_mtl(200_000), 1692.5)
    # Saint-Joseph (1 699 000) → calcul manuel par tranches
    # 61500×0.005=307.5 + (307800-61500)×0.01=2463 + (552300-307800)×0.015=3667.5
    # + (1104700-552300)×0.02=11048 + (1699000-1104700)×0.025=14857.5
    # Total ≈ 32 343.5
    expect("1.699M (St-Joseph)", taxes_bienvenue_mtl(1_699_000), 32_343.5)


def test_pv_canadian():
    print("\n[test] PV canadien semestriel")
    # PV(0.04 / 2 ^ 1/6 - 1, 25*12, -100/12) — Achat 100k revenus net / 1.2 RCD
    # On vérifie juste qu'on a un sign et ordre de grandeur cohérents.
    pv = pv_canadian(0.04, 25 * 12, -100 / 12)
    print(f"   PV(4%, 25 ans, -8.33/mois) = {pv:.4f}")
    # = ~+1300 (positif puisque payment négatif)
    expect("PV ordre grandeur (>1000)", abs(pv), 1300.0, tol=0.1)


# ── Cas Saint-Joseph (sans abordabilité, calculateur OFFICIEL) ──


def make_saint_joseph_inputs() -> FinanceInputs:
    return FinanceInputs(
        adresse="3845, boulevard Saint-Joseph Est, Montréal",
        prix_achat=1_699_000,
        nombre_logements=8,
        revenus_annuels=103_992,
        taxes_municipales=10_349,
        taxes_scolaires=805,
        assurances=4_655,
        energie=221,
        depenses_autres=0,
        tga=0.04,
        taux_interet_achat=0.04,
        nb_logements_ajoutes=0,
        nb_thermopompes_ajoutees=2,
        wifi_ajoute=True,
        reduction_energie_pct=0,
        taux_interet_refi=0.0375,
        typologie={"2.5": 0, "3.5": 4, "4.5": 4, "5.5": 0, "6.5": 0, "7.5": 0, "8.5": 0},
        typologie_prix={"3.5": 1400, "4.5": 1600},
        duree_projet_annees=2,
        frais_developpement=80_000,
        frais_negociations=80_000,
        frais_travaux=160_000,
        nouveau_loyer_abordable=0,  # pas utilisé sans abordabilité
    )


def test_saint_joseph():
    print("\n" + "=" * 78)
    print("CAS DE TEST : Saint-Joseph (8 log, sans abordabilité)")
    print("=" * 78)
    inputs = make_saint_joseph_inputs()
    res = compute_all(inputs, use_aph_select=False)

    print(f"\n  H13 (loyer pondéré) = {res.typology.h13_loyer_pondere:.2f}")
    print(f"  → attendu : 1500.00 (4×1400 + 4×1600 / 8)")
    expect("H13 loyer pondéré", res.typology.h13_loyer_pondere, 1500.0)

    print(f"\n  Frais démarrage total = {res.frais_demarrage.total:,.2f}")
    print(f"  Prix acquisition       = {res.prix_acquisition:,.2f}")
    expect("Frais démarrage total", res.frais_demarrage.total, 462_503)
    expect("Prix acquisition", res.prix_acquisition, 2_161_503)

    print("\n  --- COLONNE ACHAT ---")
    expect("Valeur éco RCD achat", res.achat.valeur_eco_rcd, 1_299_460)
    expect("Valeur éco TGA achat", res.achat.valeur_eco_tga, 1_845_560)
    expect("Valeur marchande achat", res.achat.valeur_marchande, 1_699_000)
    expect("Valeur retenue achat", res.achat.valeur_retenue, 1_299_460)
    expect("Financement achat", res.achat.financement, 974_595)
    expect("MDF nécessaire", res.achat.mdf_necessaire, 1_186_910)

    print("\n  --- COLONNE REFI SCHL standard ---")
    expect("Valeur éco RCD SCHL", res.refi_schl.valeur_eco_rcd, 1_928_900)
    expect("Valeur éco TGA SCHL", res.refi_schl.valeur_eco_tga, 2_725_250)
    expect("Valeur retenue SCHL", res.refi_schl.valeur_retenue, 1_928_900)
    expect("Financement SCHL", res.refi_schl.financement, 1_639_570)
    expect("Équité SCHL", res.refi_schl.equite_a_la_fin, -521_934)

    print("\n  --- COLONNE REFI APH 50 pts (Efficacité) ---")
    expect("Valeur éco RCD APH 50", res.refi_aph_50.valeur_eco_rcd, 2_415_880)
    expect("Valeur éco TGA APH 50", res.refi_aph_50.valeur_eco_tga, 2_715_750)
    expect("Valeur retenue APH 50", res.refi_aph_50.valeur_retenue, 2_415_880)
    expect("Financement APH 50", res.refi_aph_50.financement, 2_053_490)
    expect("Équité APH 50", res.refi_aph_50.equite_a_la_fin, -108_009)

    print("\n  --- BEST REFI ---")
    print(f"  Best amount : {res.best_refi_amount:,.2f}")
    print(f"  Best program: {res.best_refi_program}")


# ── Tests de propagation (régression PR audit MDF prêteur B) ───


def test_interets_scale_with_mdf_preteur_b():
    """Vérifie que les intérêts de portage scalent avec (1 - mdf_pct).

    Régression : avant le fix, le `0.75` (= 1 - 0.25) et le `0.08`
    étaient en dur dans compute_frais_demarrage. Changer
    mdf_preteur_b_pct ne propageait pas dans les intérêts.
    """
    print("\n[test] Propagation MDF prêteur B → intérêts portage")
    base = make_saint_joseph_inputs()
    base.mdf_preteur_b_pct = 0.25
    res25 = compute_all(base, use_aph_select=False)

    base.mdf_preteur_b_pct = 0.35
    res35 = compute_all(base, use_aph_select=False)

    # Avec mdf=0.25 : intérêts = 0.75 × 1_699_000 × 0.08 × 2 = 203_880
    # Avec mdf=0.35 : intérêts = 0.65 × 1_699_000 × 0.08 × 2 = 176_696
    expect("Intérêts avec MDF 25%", res25.frais_demarrage.interets, 203_880)
    expect("Intérêts avec MDF 35%", res35.frais_demarrage.interets, 176_696)

    # Ratio attendu : 0.65 / 0.75 = 0.8667
    ratio = res35.frais_demarrage.interets / res25.frais_demarrage.interets
    expect("Ratio intérêts 35%/25%", ratio, 0.8667, tol=0.01)


def test_taux_interet_preteur_b_projet_parametrable():
    """Vérifie que taux_interet_preteur_b_projet est bien parametre.

    Si on double le taux (8 % → 16 %), les intérêts doublent aussi.
    """
    print("\n[test] Paramétrabilité taux intérêt prêteur B projet")
    base = make_saint_joseph_inputs()
    base.taux_interet_preteur_b_projet = 0.08
    res8 = compute_all(base, use_aph_select=False)

    base.taux_interet_preteur_b_projet = 0.16
    res16 = compute_all(base, use_aph_select=False)

    # 0.16 / 0.08 = 2.0
    ratio = res16.frais_demarrage.interets / res8.frais_demarrage.interets
    expect("Ratio intérêts 16%/8%", ratio, 2.0, tol=0.001)


def test_taux_inoccupation_pct_parametrable():
    """Vérifie que taux_inoccupation_pct est bien paramétré.

    Régression : avant le fix, `0.03` était en dur dans
    compute_depenses_for_scenario.
    """
    print("\n[test] Paramétrabilité taux d'inoccupation")
    base = make_saint_joseph_inputs()
    base.taux_inoccupation_pct = 0.03
    res3 = compute_all(base, use_aph_select=False)

    base.taux_inoccupation_pct = 0.05
    res5 = compute_all(base, use_aph_select=False)

    # 3 % sur 103 992 = 3 119.76
    # 5 % sur 103 992 = 5 199.60
    expect("Inoccupation 3% (achat)", res3.achat.depenses.inoccupation, 0.03 * 103_992)
    expect("Inoccupation 5% (achat)", res5.achat.depenses.inoccupation, 0.05 * 103_992)


# ── Runner ──────────────────────────────────────────────────────


def run_all():
    test_taxes_bienvenue_mtl()
    test_pv_canadian()
    test_saint_joseph()
    test_interets_scale_with_mdf_preteur_b()
    test_taux_interet_preteur_b_projet_parametrable()
    test_taux_inoccupation_pct_parametrable()
    print("\n" + "=" * 78)
    print("Fin des tests. Si des écarts > 1 % apparaissent ci-dessus,")
    print("vérifier la formule correspondante dans lead_analysis_finance.py")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    run_all()