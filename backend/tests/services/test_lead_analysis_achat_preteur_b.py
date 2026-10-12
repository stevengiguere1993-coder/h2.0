"""Achat prêteur B — cashflow de l'acquisition (Phil 2026-10-12).

L'exemple de Phil : prix 1 000 000 $, travaux 500 000 $, prêteur à 80 %
(MDF 20 %). Le prêteur s'engage sur 80 % des travaux mais en RETIENT
100 % (déboursés progressifs) → au notaire il n'avance pas 800 000 $
mais 800 000 − 20 % × 500 000 = 700 000 $ ; les frais d'acquisition se
paient cash au départ ; les travaux s'avancent avant d'être remboursés
(fonds de roulement). Vue par moment, aucun nouveau poste : la somme
des cash par moment redonne la mise de fonds prêteur B.
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
        nouveau_loyer_abordable=1_000.0,
        mdf_preteur_b_pct=0.20,
        frais_demarrage_financables=["frais_travaux"],
        retenue_travaux_pct=1.0,
        nb_deboursements_travaux=3,
    )
    base.update(kw)
    return FinanceInputs(**base)


def _cash_frais(res, moment: str) -> float:
    return sum(p["cash"] for p in res.achat_preteur_b["postes"][moment])


def test_exemple_de_phil_retenue_100_pct():
    res = compute_all(_inputs())
    a = res.achat_preteur_b
    assert a is not None
    # Le prêteur s'engage sur 80 % de 1 M + 80 % de 500 k = 1,2 M…
    assert a["pret_total"] == 1_200_000.0
    assert a["engagement_travaux"] == 400_000.0
    # … mais retient 100 % des travaux : 700 000 $ au notaire.
    assert a["retenue"] == 500_000.0
    assert a["avance_notaire"] == 700_000.0
    assert a["manque_travaux_notaire"] == 100_000.0
    # Mise de fonds au notaire = 20 % du prix + 20 % des travaux exigés
    # d'avance.
    assert a["mdf_notaire"] == 300_000.0
    # Les frais d'acquisition (courtier, notaire, avocat, inspection,
    # frais de dossier…) sont cash au notaire ; les travaux ne coûtent
    # plus rien pendant le projet (part déjà sortie au notaire).
    assert a["cash_notaire"] == 300_000.0 + _cash_frais(res, "notaire")
    assert a["travaux_cash_projet"] == 0.0
    assert a["cash_projet"] == _cash_frais(res, "projet")
    # Fonds de roulement = retenue ÷ nombre de déboursés.
    assert a["fonds_roulement"] == round(500_000.0 / 3, 2)
    assert a["fonds_roulement_saisi"] is False
    # La vue par moment redonne exactement la mise de fonds prêteur B.
    assert abs(a["ecart"]) < 0.05
    assert abs(a["cash_notaire"] + a["cash_projet"] + a["cash_refi"] - res.mdf_preteur_b) < 0.05
    assert a["besoin_max"] == round(a["cash_notaire"] + a["cash_projet"] + a["fonds_roulement"], 2)
    # Les postes du refi (courtier 2, évaluateur 2, notaire 2) sont au refi.
    cles_refi = {p["cle"] for p in a["postes"]["refi"]}
    assert cles_refi == {"courtier_hypothecaire_2", "evaluateur_2", "notaire_2"}
    cles_notaire = {p["cle"] for p in a["postes"]["notaire"]}
    assert {"courtier_hypothecaire_1", "notaire", "avocat", "inspection", "frais_dossier_preteur"} <= cles_notaire


def test_retenue_egale_a_la_part_financee_et_fonds_de_roulement_saisi():
    # Retenue 80 % = exactement la part financée : rien à combler au
    # notaire (avance 800 000 $), les 20 % des travaux se paient pendant
    # les travaux ; fonds de roulement saisi sur la fiche.
    res = compute_all(_inputs(retenue_travaux_pct=0.80, fonds_roulement_travaux=200_000.0))
    a = res.achat_preteur_b
    assert a["avance_notaire"] == 800_000.0
    assert a["manque_travaux_notaire"] == 0.0
    assert a["mdf_notaire"] == 200_000.0
    assert a["travaux_cash_projet"] == 100_000.0
    assert a["fonds_roulement"] == 200_000.0 and a["fonds_roulement_saisi"] is True
    assert abs(a["ecart"]) < 0.05


def test_travaux_non_finances():
    # Travaux pas finançables : pas de retenue, avance = 80 % du prix,
    # travaux 100 % cash pendant les travaux, pas de fonds de roulement.
    res = compute_all(_inputs(frais_demarrage_financables=[]))
    a = res.achat_preteur_b
    assert a["travaux_financables"] is False
    assert a["retenue"] == 0.0
    assert a["avance_notaire"] == 800_000.0
    assert a["mdf_notaire"] == 200_000.0
    assert a["travaux_cash_projet"] == 500_000.0
    assert a["fonds_roulement"] == 0.0
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
