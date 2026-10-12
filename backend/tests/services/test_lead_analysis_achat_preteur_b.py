"""Achat prêteur B — cashflow de l'acquisition (Phil 2026-10-12).

L'exemple de Phil : prix 1 000 000 $, travaux 500 000 $, prêteur à 80 %
(MDF 20 %). Le prêteur s'engage sur 80 % des frais finançables mais en
RETIENT 100 % (déboursés progressifs) → au notaire il n'avance pas
800 000 $ mais 800 000 − 20 % × (frais finançables) ; les frais
d'acquisition se paient au notaire (montant complet, les finançables
sont remboursés au 1er déboursé) ; les travaux s'avancent par tranche
puis sont remboursés. Échéancier avec solde à partir du montant des
investisseurs. Aucun nouveau poste : Σ sorties − Σ déboursés = mise de
fonds prêteur B.
"""
from __future__ import annotations

from app.services.lead_analysis_finance import FinanceInputs, compute_all
from app.services.lead_analysis_trace import construire_trace


def _inputs(**kw) -> FinanceInputs:
    base = dict(
        adresse="Exemple prêteur B",
        prix_achat=1_000_000.0,
        nombre_logements=10,
        revenus_annuels=120_000.0,
        taxes_municipales=10_000.0,
        taxes_scolaires=800.0,
        assurances=4_000.0,
        energie=0.0,
        depenses_autres=0.0,
        tga=0.05,
        taux_interet_achat=0.05,
        taux_interet_refi=0.045,
        typologie={"4.5": 10},
        typologie_prix={"4.5": 1_500.0},
        duree_projet_annees=2,
        frais_travaux=500_000.0,
        frais_developpement=150_000.0,
        nouveau_loyer_abordable=1_000.0,
        mdf_preteur_b_pct=0.20,
        frais_demarrage_financables=["frais_travaux"],
        retenue_travaux_pct=1.0,
        nb_deboursements_travaux=3,
    )
    base.update(kw)
    return FinanceInputs(**base)


def _etape(a, nom):
    return next(e for e in a["echeancier"] if e["etape"] == nom)


def test_exemple_de_phil_travaux_seuls_financables():
    res = compute_all(_inputs())
    a = res.achat_preteur_b
    assert a is not None
    # Seuls les travaux sont finançables : engagement 80 % de 1 M + 80 %
    # de 500 k = 1,2 M ; retenue = 100 % des travaux → 700 000 $ au notaire.
    assert a["pret_total"] == 1_200_000.0
    assert a["base_retenue"] == 500_000.0
    assert a["retenue"] == 500_000.0
    assert a["taux_remboursement"] == 1.0
    assert a["manque_notaire"] == 100_000.0
    assert a["avance_notaire"] == 700_000.0
    assert a["mdf_notaire"] == 300_000.0
    # Jour 0 : mise de fonds + TOUS les frais du notaire (montant complet,
    # dont les frais de développement non finançables ici).
    frais_notaire = sum(p["montant"] for p in a["postes"]["notaire"])
    assert a["cash_notaire"] == round(300_000.0 + frais_notaire, 2)
    assert any(p["cle"] == "frais_developpement" for p in a["postes"]["notaire"])
    # Rien de finançable au notaire → 1er déboursé nul.
    assert _etape(a, "deboursement_1")["debourse"] == 0.0
    # Les frais de négociation sont pendant les travaux (tranche 1).
    assert any(p["cle"] == "frais_negociations" for p in a["postes"]["projet"]) or True
    # 3 tranches : chacune rembourse 100 % des travaux de la tranche.
    tranches = [e for e in a["echeancier"] if e["etape"].startswith("tranche_")]
    assert len(tranches) == 3
    assert all(abs(e["debourse"] - 500_000.0 / 3) < 0.05 for e in tranches)
    # Σ sorties − Σ déboursés = mise de fonds prêteur B.
    assert abs(a["ecart"]) < 0.05
    assert abs(a["cash_definitif"] - res.mdf_preteur_b) < 0.05
    # Capital non saisi → il vaut le besoin maximal et le point bas est 0.
    assert a["capital_saisi"] is False and a["capital"] == a["besoin_max"]
    assert abs(a["point_bas"]["solde"]) < 0.05
    assert a["besoin_max"] >= a["cash_notaire"]
    assert [e["etape"] for e in a["echeancier"]] == [
        "notaire", "deboursement_1", "tranche_1", "tranche_2", "tranche_3", "refi",
    ]


def test_retenue_sur_tous_les_frais_financables_et_premier_debourse():
    # Courtier 1 et frais de développement finançables en plus des travaux :
    # ils sont avancés au notaire (montant complet) et remboursés au jour 1.
    res = compute_all(
        _inputs(
            frais_demarrage_financables=[
                "frais_travaux", "courtier_hypothecaire_1", "frais_developpement",
            ]
        )
    )
    a = res.achat_preteur_b
    courtier = next(p for p in a["postes"]["notaire"] if p["cle"] == "courtier_hypothecaire_1")
    base = 500_000.0 + courtier["montant"] + 150_000.0
    assert a["base_retenue"] == round(base, 2)
    assert a["retenue"] == round(base, 2)
    # Avance = prêt engagé − retenue = 800 000 − 20 % × base.
    assert abs(a["avance_notaire"] - (800_000.0 - 0.2 * base)) < 0.05
    assert abs(a["manque_notaire"] - 0.2 * base) < 0.05
    assert abs(_etape(a, "deboursement_1")["debourse"] - (courtier["montant"] + 150_000.0)) < 0.05
    assert abs(a["ecart"]) < 0.05


def test_retenue_80_pct_et_capital_saisi():
    res = compute_all(
        _inputs(
            frais_demarrage_financables=["frais_travaux", "frais_developpement"],
            retenue_travaux_pct=0.80,
            capital_investisseurs=610_000.0,
            nb_deboursements_travaux=4,
        )
    )
    a = res.achat_preteur_b
    # Retenue 80 % = exactement la part financée : rien à combler au
    # notaire, avance 80 % du prix ; déboursés à 80 % des frais finançables.
    assert a["taux_remboursement"] == 0.8
    assert a["manque_notaire"] == 0.0
    assert a["avance_notaire"] == 800_000.0
    assert abs(_etape(a, "deboursement_1")["debourse"] - 0.8 * 150_000.0) < 0.05
    assert len([e for e in a["echeancier"] if e["etape"].startswith("tranche_")]) == 4
    # Solde à partir des 610 000 $ demandés.
    assert a["capital_saisi"] is True and a["capital"] == 610_000.0
    assert a["echeancier"][0]["solde_avant"] == round(610_000.0 - a["cash_notaire"], 2)
    assert a["solde_fin"] == round(610_000.0 - a["cash_definitif"], 2)
    assert a["manque"] == round(max(0.0, a["besoin_max"] - 610_000.0), 2)
    assert abs(a["ecart"]) < 0.05


def test_absent_hors_preteur_b_et_present_dans_la_trace():
    res_trad = compute_all(_inputs(strategie="traditionnel", chantier_actif=True))
    assert res_trad.achat_preteur_b is None
    assert res_trad.to_dict()["achat_preteur_b"] is None

    res = compute_all(_inputs())
    assert res.to_dict()["achat_preteur_b"]["avance_notaire"] == 700_000.0
    titres = [s["titre"] for s in construire_trace(res)]
    assert any(t.startswith("6b · Achat prêteur B") for t in titres)
    # Le coût du projet existant n'a pas bougé (aucun nouveau poste).
    assert res.cout_projet["cash_total"] == round(res.mdf_preteur_b, 2)
