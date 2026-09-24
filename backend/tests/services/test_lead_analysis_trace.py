"""Trace lisible des calculs (« Détails des calculs ») — Phil 2026-09-24 :
« chaque petit calcul qui se fait dans le backend va venir dans la
section des détails de calculs. Je veux tout tout tout voir. »

Cas de base = le 7444-7448 Des Ormeaux (24 logements, autres dépenses
déclarées 40 346 $)."""
from __future__ import annotations

import json

from app.services.lead_analysis_finance import FinanceInputs, compute_all
from app.services.lead_analysis_trace import _m, _p, construire_trace


def _inputs(**kw) -> FinanceInputs:
    base = dict(
        adresse="7444-7448 avenue Des Ormeaux",
        prix_achat=4_750_000.0,
        nombre_logements=24,
        revenus_annuels=301_476.0,
        taxes_municipales=22_556.0,
        taxes_scolaires=2_347.0,
        assurances=12_163.0,
        energie=762.0,
        depenses_autres=40_346.0,
        tga=0.04,
        taux_interet_achat=0.044,
        taux_interet_refi=0.044,
        typologie={"4.5": 24},
        typologie_prix={"4.5": 1_500.0},
        duree_projet_annees=2,
        frais_travaux=240_000.0,
        nouveau_loyer_abordable=1_000.0,
        mdf_preteur_b_pct=0.20,
        frais_demarrage_financables=["frais_travaux", "rapport_efficacite"],
    )
    base.update(kw)
    return FinanceInputs(**base)


def _ligne(sections, titre_prefixe, label):
    sec = next(s for s in sections if s["titre"].startswith(titre_prefixe))
    return next(l for l in sec["lignes"] if l["label"] == label)


def test_formatage_francais():
    assert _m(8_760) == "8 760 $"
    assert _m(5.95) == "5,95 $"
    assert _m(-1_234.4) == "-1 234 $"
    assert _m(4_750_000) == "4 750 000 $"
    assert _p(0.0425) == "4,25 %"
    assert _p(0.05) == "5 %"
    assert _p(0.2) == "20 %"


def test_trace_preteur_b_complete():
    res = compute_all(_inputs())
    d = res.to_dict()
    trace = d["details_calculs"]
    assert trace, "la trace fait partie du JSON persisté"
    json.dumps(trace)  # sérialisable tel quel
    titres = [s["titre"] for s in trace]
    for attendu in (
        "1 · Données de la fiche",
        "2 · Paramètres du modèle",
        "3 · Typologie et loyers cibles",
        "4a · Scénario Achat conventionnel",
        "4b · Scénario SCHL standard",
        "4c · Scénario SCHL Efficacité énergétique (50 pts)",
        "4d · Scénario SCHL Abordabilité + Efficacité (100 pts)",
        "5 · Frais de démarrage",
        "6 · Mise de fonds et prêt du prêteur B",
        "7 · Refinancement et verdict",
    ):
        assert any(t.startswith(attendu) for t in titres), attendu
    assert not any("Institution traditionnelle" in t or "Résidentiel" in t for t in titres)

    # Toutes les lignes ont la même forme.
    for s in trace:
        for l in s["lignes"]:
            assert set(l) == {"label", "formule", "valeur", "valeur_txt", "source", "gras", "note"}
            assert l["source"] in ("fiche", "paramètre", "calcul")

    # 1. Le « Autres dépenses » vient de la FICHE, tel quel, avec l'avertissement.
    autres = _ligne(trace, "1 ·", "Autres dépenses")
    assert autres["valeur"] == 40_346.0 and autres["source"] == "fiche"
    assert "deux fois" in autres["note"]

    # 4a. Barème SCHL écrit avec les vrais nombres (24 log. ≥ 12 → grand immeuble).
    conc = _ligne(trace, "4a ·", "Concierge (barème)")
    assert conc["formule"] == "24 log. × 365 $" and conc["valeur"] == 24 * 365
    gest = _ligne(trace, "4a ·", "Gestion (barème)")
    assert gest["formule"] == "5 % × 301 476 $"
    assert gest["valeur"] == round(0.05 * 301_476, 2)
    ent = _ligne(trace, "4a ·", "Entretien (barème)")
    assert ent["formule"] == "24 log. × 610 $" and ent["valeur"] == 24 * 610
    autres_n = _ligne(trace, "4a ·", "Autres normalisations (barème)")
    assert autres_n["formule"] == "1 % × 301 476 $"
    total = _ligne(trace, "4a ·", "Total des dépenses")
    assert total["valeur"] == round(res.achat.depenses.total, 2) and total["gras"]
    # La somme des postes affichés = le total affiché (rien de caché).
    sec4a = next(s for s in trace if s["titre"].startswith("4a ·"))
    postes = [
        l["valeur"] for l in sec4a["lignes"]
        if l["label"] in (
            "Inoccupation", "Taxes municipales", "Taxes scolaires", "Assurances",
            "Énergie", "Concierge (barème)", "Entretien (barème)", "Gestion (barème)",
            "Autres normalisations (barème)", "Autres dépenses (fiche)",
        )
    ]
    assert abs(sum(postes) - total["valeur"]) < 0.05
    rno = _ligne(trace, "4a ·", "Revenus nets d'opération (RNO)")
    assert rno["valeur"] == round(res.achat.revenus_net, 2)
    fin = _ligne(trace, "4a ·", "Financement (prêt accordé)")
    assert fin["valeur"] == round(res.achat.financement, 2)
    assert "× 75 %" in fin["formule"]
    vr = _ligne(trace, "4a ·", "Valeur retenue")
    assert vr["formule"].startswith("min(4 750 000 $ ;")
    mdf = _ligne(trace, "4a ·", "Mise de fonds nécessaire (prix d'acquisition − prêt)")
    assert mdf["valeur"] == round(res.achat.mdf_necessaire, 2)

    # 4b. Refi : WiFi et thermopompes expliqués, équité à la fin.
    wifi = _ligne(trace, "4b ·", "WiFi (barème)")
    assert wifi["formule"] == "5 $ × 24 log. × 12 + 120 $ × 12"
    th = _ligne(trace, "4b ·", "Thermopompes (barème, APH seulement)")
    assert th["formule"] == "scénario non APH → 0" and th["valeur"] == 0
    eq = _ligne(trace, "4b ·", "Équité à la fin (prêt refi − prix d'acquisition)")
    assert eq["valeur"] == round(res.refi_schl.equite_a_la_fin, 2)

    # 5. Frais : total = somme, finançables ventilés cash / prêt.
    tot_frais = _ligne(trace, "5 ·", "Total des frais de démarrage")
    assert tot_frais["valeur"] == round(res.frais_demarrage.total, 2)
    cash = _ligne(trace, "5 ·", "dont payés en cash")
    pret = _ligne(trace, "5 ·", "dont ajoutés au prêt du prêteur B")
    assert abs(cash["valeur"] + pret["valeur"] - tot_frais["valeur"]) < 0.05
    travaux = _ligne(trace, "5 ·", "Travaux estimés")
    assert travaux["source"] == "fiche" and "finançable" in travaux["note"]
    interets = _ligne(trace, "5 ·", "Intérêts de portage pendant le projet")
    assert interets["formule"].startswith("(1 − 20 %) × (4 750 000 $ + frais finançables")
    taxes = _ligne(trace, "5 ·", "Taxes de bienvenue")
    assert taxes["formule"].startswith("paliers Montréal : 61 500 $ × 0,5 %")

    # 6. MDF = assise + frais cash ; prêt B ; prix d'acquisition.
    mdf_b = _ligne(trace, "6 ·", "= Mise de fonds prêteur B (cash à sortir)")
    assert mdf_b["valeur"] == round(res.mdf_preteur_b, 2)
    pa = _ligne(trace, "6 ·", "Prix d'acquisition (total dépensé)")
    assert pa["valeur"] == round(res.prix_acquisition, 2)

    # 7. Verdict = le meilleur scénario.
    verdict = _ligne(trace, "7 ·", "Argent dégagé au refinancement")
    assert verdict["valeur"] == round(res.best_refi_amount, 2)
    retenu = _ligne(trace, "7 ·", "Scénario retenu pour le verdict")
    assert retenu["valeur_txt"] == res.best_refi_program


def test_trace_indexation_chantier_et_override():
    """Chantier actif : dépenses réelles indexées (facteur écrit dans la
    formule) ; un frais saisi sur la fiche est marqué comme tel."""
    res = compute_all(
        _inputs(
            chantier_actif=True,
            croissance_depenses=0.03,
            frais_demarrage_overrides={"inspection": 2_500.0},
        )
    )
    trace = construire_trace(res)
    tm = _ligne(trace, "4b ·", "Taxes municipales")
    assert tm["formule"] == "fiche 22 556 $ × 1,0609"
    assert tm["valeur"] == round(22_556 * 1.03 ** 2, 2)
    sec = next(s for s in trace if s["titre"].startswith("4b ·"))
    assert "facteur 1,0609" in (sec["note"] or "")
    insp = _ligne(trace, "5 ·", "Inspection")
    assert insp["formule"] == "saisi manuellement sur la fiche"
    assert insp["source"] == "fiche" and insp["valeur"] == 2_500.0


def test_trace_traditionnel_et_residentiel():
    res_t = compute_all(_inputs(strategie="traditionnel", chantier_actif=True))
    titres_t = [s["titre"] for s in construire_trace(res_t)]
    assert any(t.startswith("8 · Institution traditionnelle") for t in titres_t)
    trace_t = construire_trace(res_t)
    prog = _ligne(trace_t, "8 ·", "Programme d'achat retenu")
    assert prog["valeur_txt"] in res_t.traditionnel["labels"].values()

    res_r = compute_all(
        _inputs(strategie="residentiel", chantier_actif=True, nombre_logements=6,
                typologie={"4.5": 6}, revenus_annuels=90_000.0)
    )
    trace_r = construire_trace(res_r)
    assert any(s["titre"].startswith("8 · Résidentiel") for s in trace_r)
    pret = _ligne(trace_r, "8 · Résidentiel", "Prêt total")
    assert pret["valeur"] == res_r.residentiel["pret_total"]


def test_trace_ne_casse_jamais_le_calcul(monkeypatch):
    import app.services.lead_analysis_trace as tr

    def _boom(res):
        raise RuntimeError("cassé exprès")

    monkeypatch.setattr(tr, "construire_trace", _boom)
    d = compute_all(_inputs()).to_dict()
    assert d["details_calculs"] is None
    assert d["scenarios"]["achat"]["financement"] > 0


def test_instantane_des_calculs_verrouille():
    """GARDE-FOU (Phil 2026-09-24 : « les dépenses normalisées c'est sacré,
    on ne peut pas rajouter des trucs dans l'analyse sans que je sois au
    courant »). L'instantané ``trace_snapshot_des_ormeaux.json`` fige
    CHAQUE poste, sa formule et sa valeur pour un cas de référence.
    Tout ajout, retrait ou changement de formule ou de défaut le casse :
    on ne le régénère qu'avec l'accord explicite de Phil, en le citant
    (date) dans le commit."""
    import os

    chemin = os.path.join(os.path.dirname(__file__), "trace_snapshot_des_ormeaux.json")
    with open(chemin, encoding="utf-8") as f:
        attendu = json.load(f)
    trace = construire_trace(compute_all(_inputs()))
    obtenu = [
        {"section": s["titre"], "label": l["label"], "formule": l["formule"],
         "valeur": l["valeur_txt"], "source": l["source"]}
        for s in trace for l in s["lignes"]
    ]
    assert obtenu == attendu, (
        "Le calcul a changé (poste, formule, défaut ou valeur). Si c'est voulu "
        "ET validé par Phil, régénère tests/services/trace_snapshot_des_ormeaux.json "
        "et cite sa validation dans le commit."
    )
