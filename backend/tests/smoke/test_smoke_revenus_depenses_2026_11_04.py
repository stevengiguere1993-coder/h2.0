"""Smoke — Gestion d'entreprise → Revenus et dépenses (simulation, 2026-11-04),
aligné sur « Le Fonds MGV d'investissements » (doc de travail, nov. 2026).

1. le moteur : valeur des immeubles selon le document (rénovation = coût +
   plus-value linéaire ; stabilisé = rapport ou revenus nets ÷ taux de cap),
   VAN = valeur + cash − dettes, immeubles hors fonds exclus de la VAN mais
   pas des frais de gestion, développement par TRANCHES (comme l'impôt),
   prospection si prospecté par nous, cost-plus en marge nette, gestion
   locative avec ou sans les sous-traités, location au roulement, part des
   gains (7 % / 3 % / 70-30) hors totaux, sous-traitant de gestion en dépense,
   point mort ;
2. l'API : admins seulement, scénario par défaut, enregistrement + recalcul,
   copie, suppression, calcul sans enregistrer, immeubles déjà dans Kratos.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.services import revenus_depenses as svc
from tests.smoke.conftest import TestSessionLocal

RD = "/api/v1/entreprises/revenus-depenses"


def _imm(**kw):
    return svc.immeuble_vide(**kw)


def _scenario_test() -> dict:
    d = svc.scenario_defaut()
    d["annee"] = 2027
    d["fonds"] = {"cash": 1_000_000, "taux_pct": 1.5}
    d["immeubles"] = [
        _imm(id="a", nom="A", nb_logements=20, loyers_bruts_mensuels=25_000, phase="stabilisation",
             acquisition_cette_annee=True, prix_acquisition=4_500_000, prospecte_par_nous=True,
             travaux_initiaux=500_000, frais_connexes=100_000, valeur_future=6_100_000, mois_prevus=24, mois_ecoules=6,
             dette=3_000_000),
        _imm(id="b", nom="B", nb_logements=10, nb_chambres=4, loyers_bruts_mensuels=12_000, phase="stabilise",
             valeur_rapport=3_000_000, annee_rapport=2025, taux_cap_pct=5, dette=2_000_000),
        _imm(id="c", nom="C (sous-traité)", gestion_interne=False, nb_logements=30, loyers_bruts_mensuels=40_000,
             phase="stabilise", valeur_rapport=5_000_000, taux_cap_pct=5, revenus_nets_annuels=300_000,
             acquisition_cette_annee=True, prix_acquisition=12_000_000, prospecte_par_nous=False, dette=4_000_000),
        _imm(id="d", nom="D (hors fonds)", dans_le_fonds=False, nb_logements=8, loyers_bruts_mensuels=9_000,
             phase="stabilise", valeur_rapport=2_000_000, dette=1_000_000),
    ]
    d["refacturation"] = {"marge_pct": 10, "lignes": [{"id": "r1", "libelle": "Avocat", "montant_annuel": 120_000}]}
    d["construction"] = {"marge_pct": 10, "pct_logements_renoves_par_an": 10, "cout_reno_logement": 15_000}
    d["maintenance"] = {"heures_par_an": 1_000, "cout_horaire": 50, "taux_facture": 75, "materiaux_annuels": 50_000, "marge_materiaux_pct": 10}
    d["gestion"] = {"taux_pct": 10, "facturer_sous_traites": True, "loyers_additionnels_mensuels": 100_000, "inclure_projection": False}
    d["location"] = {"frais_logement": 600, "frais_chambre": 400, "taux_roulement_pct": 20, "nb_relocations_logements": None, "nb_relocations_chambres": None}
    d["part_des_gains"] = {"rendement_pct": 15, "seuil_investisseurs_pct": 7, "tranche_nous_pct": 3, "part_nous_pct": 30}
    d["depenses"] = {
        "frais_fixes": [{"categorie": "abonnements", "libelle": "Logiciels", "montant": 500, "periode": "mois"},
                        {"categorie": "informatique", "libelle": "TI", "montant": 2_400, "periode": "an"}],
        "charges_sociales_pct": 14,
        "salaires": [{"poste": "Comptabilité", "salaire_annuel": 50_000}, {"poste": "Gestionnaire immobilier", "salaire_annuel": 60_000}],
        "associes": [{"nom": "Philippe", "salaire_annuel": 40_000, "dividendes_annuels": 30_000},
                     {"nom": "Steven", "salaire_annuel": 0, "dividendes_annuels": 0},
                     {"nom": "Michael", "salaire_annuel": 0, "dividendes_annuels": 0}],
        "sous_traitance_gestion_pct": 5,
    }
    return d


def test_moteur_valeur_du_fonds_et_chaque_source():
    r = svc.calculer(_scenario_test())
    parc = r["parc"]
    fiches = {f["nom"]: f for f in parc["immeubles"]}
    # A en rénovation : coût 5,1 M + (6,1 M − 5,1 M) × 6/24.
    assert fiches["A"]["cout_projet"] == 5_100_000 and fiches["A"]["valeur"] == 5_350_000 and fiches["A"]["equite"] == 2_350_000
    assert fiches["A"]["plus_value_prevue"] == 1_000_000 and fiches["A"]["valeur_a_terme"] == 6_100_000
    # B stabilisé : rapport ; C stabilisé : revenus nets ÷ taux de cap.
    assert fiches["B"]["valeur"] == 3_000_000 and fiches["C (sous-traité)"]["valeur"] == 6_000_000
    # D hors fonds : fiche présente, mais pas dans la VAN.
    assert fiches["D (hors fonds)"]["dans_le_fonds"] is False
    assert parc["valeur"] == 14_350_000 and parc["dettes"] == 9_000_000 and parc["equite"] == 5_350_000
    assert parc["van"] == 6_350_000 and parc["van_a_terme"] == 7_100_000
    assert parc["nb_dans_le_fonds"] == 3 and parc["nb_hors_fonds"] == 1 and parc["nb_en_renovation"] == 1

    rev = {s["key"]: s for s in r["revenus"]}
    assert rev["fonds"]["van"] == 6_350_000 and rev["fonds"]["revenu"] == 95_250
    # Développement par tranches : A 4,5 M → 150 000 + 1,5 M × 4,5 % ; C 12 M → 515 000 ; D hors fonds et B non acquis exclus.
    assert [(l["immeuble"], l["frais"]) for l in rev["developpement"]["lignes"]] == [("A", 217_500), ("C (sous-traité)", 515_000)]
    assert rev["developpement"]["revenu"] == 732_500 and rev["developpement"]["lignes"][0]["taux_effectif_pct"] == 4.83
    assert rev["prospection"]["revenu"] == 90_000 and [l["immeuble"] for l in rev["prospection"]["lignes"]] == ["A"]
    assert rev["refacturation"]["revenu"] == 12_000
    # Construction : 500 k × 10 % ; stabilisés (B 10 + C 30 + D 8 = 48) × 10 % × 15 000 × 10 %.
    assert rev["construction"]["revenu_stabilisation"] == 50_000 and rev["construction"]["revenu_renovations"] == 7_200
    assert rev["maintenance"]["revenu"] == 30_000
    # Gestion : internes (A, B, D) 552 000 + sous-traité C 480 000, facturés aussi → 1 032 000 × 10 %.
    assert rev["gestion"]["loyers_internes_annuels"] == 552_000 and rev["gestion"]["loyers_sous_traites_annuels"] == 480_000
    assert rev["gestion"]["revenu"] == 103_200 and rev["gestion"]["sous_traites"] == ["C (sous-traité)"]
    assert rev["gestion_projection"]["revenu"] == 120_000 and rev["gestion_projection"]["inclus"] is False
    # Location : portes internes 38 × 20 % = 7,6 → 8 × 600 ; chambres 4 × 20 % → 1 × 400.
    assert rev["location"]["relocations_logements"] == 8 and rev["location"]["relocations_chambres"] == 1 and rev["location"]["revenu"] == 5_200
    t = r["totaux"]
    assert t["revenus"] == 1_125_350 and t["revenus_avec_projection"] == 1_245_350
    # Dépenses : fixes 8 400 ; salaires 110 000 × 1,14 ; associé 40 000 × 1,14 ; sous-traitant 5 % × 480 000.
    dep = r["depenses"]
    assert dep["total_frais_fixes"] == 8_400 and dep["total_masse_salariale"] == 171_000 and dep["sous_traitance_gestion"] == 24_000
    assert t["depenses"] == 203_400 and t["benefice"] == 921_950 and t["benefice_retenu"] == 891_950
    # Part des gains (doc p. 7) : 7 % aux investisseurs, 3 % à nous, reste 70/30 — en parts, hors totaux.
    pg = r["part_des_gains"]
    assert pg["gain"] == 952_500 and pg["tranche_investisseurs"] == 444_500 and pg["tranche_nous"] == 190_500
    assert pg["part_nous"] == 285_750 and pg["part_investisseurs"] == 666_750 and pg["par_holding"] == 95_250 and pg["pct_du_gain_nous"] == 30.0
    assert r["point_mort"]["couvert"] is True and r["avertissements"] == []


def test_moteur_point_mort_tranches_et_garde_fous():
    d = svc.scenario_defaut()
    d["immeubles"] = [_imm(id="x", nom="X", phase="stabilise", valeur_rapport=5_000_000, dette=3_000_000, nb_logements=10, loyers_bruts_mensuels=10_000)]
    d["depenses"]["salaires"] = [{"poste": "Comptabilité", "salaire_annuel": 100_000}]
    d["depenses"]["charges_sociales_pct"] = 10
    d["depenses"]["associes"] = [{"nom": "Philippe", "salaire_annuel": 0, "dividendes_annuels": 50_000}]
    d["location"] = {"frais_logement": 600, "frais_chambre": 400, "taux_roulement_pct": 20, "nb_relocations_logements": 7, "nb_relocations_chambres": 0}
    d["maintenance"]["taux_facture"] = 40  # plus bas que le coût horaire
    d["maintenance"]["heures_par_an"] = 100
    d["gestion"]["taux_pct"] = 0  # pas de gestion locative dans ce scénario
    r = svc.calculer(d)
    rev = {s["key"]: s for s in r["revenus"]}
    assert r["parc"]["van"] == 2_000_000 and rev["fonds"]["revenu"] == 30_000
    assert rev["location"]["revenu"] == 4_200 and rev["maintenance"]["marge_heures"] == 0
    t = r["totaux"]
    assert t["depenses"] == 110_000 and t["revenus"] == 35_700 and t["benefice"] == -74_300  # 30 000 fonds + 4 200 location + 1 500 rénos au roulement
    pm = r["point_mort"]
    assert pm["couvert"] is False and pm["van_necessaire"] == round(104_300 / 0.015, 2) and pm["loyers_mensuels_sous_gestion_necessaires"] == 0
    assert any("taux facturé" in a for a in r["avertissements"]) and any("dividendes" in a for a in r["avertissements"])
    # Tranches du document (p. 21) : frais cumulés 150 k, 285 k, 445 k, 620 k, 770 k, 895 k.
    pal = svc.PALIERS_DEV_DEFAUT
    assert [svc.frais_developpement(p, pal)["total"] for p in (3e6, 6e6, 10e6, 15e6, 20e6, 25e6)] == [150_000, 285_000, 445_000, 620_000, 770_000, 895_000]
    assert svc.frais_developpement(0, pal) == {"total": 0.0, "tranches": [], "taux_effectif_pct": 0.0}
    # Valorisation : sans valeur future = coût ; mois écoulés plafonnés ; stabilisé avec revenus nets.
    v = svc.valeur_immeuble(_imm(phase="stabilisation", prix_acquisition=1_000_000, travaux_initiaux=380_000, frais_connexes=120_000))
    assert v["valeur"] == 1_500_000 and v["plus_value_prevue"] == 0
    v = svc.valeur_immeuble(_imm(phase="stabilisation", prix_acquisition=1_000_000, travaux_initiaux=380_000, frais_connexes=120_000,
                                 valeur_future=1_700_000, mois_prevus=24, mois_ecoules=36))
    assert v["valeur"] == 1_700_000 and v["plus_value_prevue"] == 200_000   # exemple du document (p. 12), à terme
    v = svc.valeur_immeuble(_imm(phase="stabilise", valeur_rapport=5_000_000, taux_cap_pct=5, revenus_nets_annuels=315_000))
    assert v["valeur"] == 6_300_000                                          # exemple du document (p. 14)
    # Normalisation : ancien format (gere_par_nous) et JSON abîmé.
    n = svc.normaliser({"immeubles": [{"nom": "X", "nb_logements": "12", "phase": "bidon", "gere_par_nous": False}, "pas un dict"], "fonds": {"taux_pct": "abc"}})
    assert n["immeubles"][0]["nb_logements"] == 12 and n["immeubles"][0]["phase"] == "stabilise" and n["immeubles"][0]["gestion_interne"] is False
    assert len(n["immeubles"]) == 1 and n["fonds"]["taux_pct"] == 1.5 and n["developpement"]["paliers"][-1]["jusqua"] is None
    # Sous-traités non facturés : la gestion ne compte que l'interne.
    d2 = _scenario_test()
    d2["gestion"]["facturer_sous_traites"] = False
    assert {s["key"]: s for s in svc.calculer(d2)["revenus"]}["gestion"]["revenu"] == 55_200


def test_moteur_prorata_date_acquisition():
    """Phil 2026-11-04 : « un immeuble le 3 avril, un autre le 30 juin » — les
    revenus récurrents (gestion, location, rénos au roulement, frais du fonds,
    sous-traitant) comptent au prorata des jours restants ; développement et
    prospection sont dus en entier à l'acquisition."""
    d = svc.scenario_defaut()
    d["annee"] = 2027
    d["fonds"] = {"cash": 0, "taux_pct": 1.5}
    d["gestion"]["taux_pct"] = 10
    d["location"] = {"frais_logement": 600, "frais_chambre": 400, "taux_roulement_pct": 20, "nb_relocations_logements": None, "nb_relocations_chambres": None}
    d["depenses"]["sous_traitance_gestion_pct"] = 5
    d["immeubles"] = [
        _imm(id="a", nom="A (3 avril)", phase="stabilise", acquisition_cette_annee=True, date_acquisition="2027-04-03",
             prix_acquisition=2_000_000, prospecte_par_nous=True, valeur_rapport=2_000_000, dette=1_200_000,
             nb_logements=10, loyers_bruts_mensuels=10_000),
        _imm(id="b", nom="B (30 juin, sous-traité)", gestion_interne=False, phase="stabilise", acquisition_cette_annee=True,
             date_acquisition="2027-06-30", prix_acquisition=1_000_000, prospecte_par_nous=False, valeur_rapport=1_000_000,
             dette=600_000, nb_logements=5, loyers_bruts_mensuels=5_000),
    ]
    r = svc.calculer(d)
    pa = 273 / 365   # du 3 avril au 31 décembre inclus
    pb = 185 / 365   # du 30 juin au 31 décembre inclus
    fiches = {f["nom"]: f for f in r["parc"]["immeubles"]}
    assert fiches["A (3 avril)"]["jours"] == 273 and fiches["A (3 avril)"]["part_annee"] == round(100 * pa, 2)
    assert fiches["B (30 juin, sous-traité)"]["jours"] == 185 and r["parc"]["nb_prorates"] == 2 and r["parc"]["annee"] == 2027
    rev = {s["key"]: s for s in r["revenus"]}
    # VAN de fin d'année entière ; frais du fonds sur l'équité pondérée par le temps.
    assert r["parc"]["van"] == 1_200_000
    assert rev["fonds"]["van_ponderee"] == round(800_000 * pa + 400_000 * pb, 2)
    assert rev["fonds"]["revenu"] == round((800_000 * pa + 400_000 * pb) * 0.015, 2)
    # Développement et prospection : en entier (A prospecté, B non).
    assert rev["developpement"]["revenu"] == 100_000 + 50_000 and rev["prospection"]["revenu"] == 40_000
    # Gestion : A (interne) et B (sous-traité, facturé) au prorata.
    assert rev["gestion"]["loyers_internes_annuels"] == round(120_000 * pa, 2)
    assert rev["gestion"]["loyers_sous_traites_annuels"] == round(60_000 * pb, 2)
    assert rev["gestion"]["revenu"] == round((120_000 * pa + 60_000 * pb) * 0.10, 2)
    # Location : 10 logements internes × 20 % × 273/365 = 1,5 → 1 (sans B, sous-traité).
    assert rev["location"]["relocations_logements_calculees"] == 1 and rev["location"]["revenu"] == 600
    # Rénos au roulement : (10 × pa + 5 × pb) × 10 % × 15 000 × 10 %.
    assert rev["construction"]["revenu_renovations"] == round((10 * pa + 5 * pb) * 0.10 * 15_000 * 0.10, 2)
    # Sous-traitant : 5 % des loyers prorata de B.
    assert r["depenses"]["sous_traitance_gestion"] == round(60_000 * pb * 0.05, 2)
    # Sans date = année entière ; date avant l'année = pas de frais d'acquisition ; après = rien cette année.
    d["immeubles"][0]["date_acquisition"] = None
    r2 = svc.calculer(d)
    assert {f["nom"]: f for f in r2["parc"]["immeubles"]}["A (3 avril)"]["part_annee"] == 100.0
    d["immeubles"][0]["date_acquisition"] = "2026-09-01"
    r3 = svc.calculer(d)
    assert {s["key"]: s for s in r3["revenus"]}["developpement"]["revenu"] == 50_000   # seulement B
    d["immeubles"][0]["date_acquisition"] = "2028-01-15"
    r4 = svc.calculer(d)
    assert {f["nom"]: f for f in r4["parc"]["immeubles"]}["A (3 avril)"]["part_annee"] == 0.0 and r4["parc"]["van"] == 400_000
    # Normalisation : date invalide ignorée, année bornée.
    n = svc.normaliser({"annee": "abc", "immeubles": [{"nom": "X", "date_acquisition": "pas une date", "notes_import": ["a", 5]}]})
    assert n["annee"] == svc.annee_defaut() and n["immeubles"][0]["date_acquisition"] is None and n["immeubles"][0]["notes_import"] == ["a", "5"]


def test_api_scenarios_admins_seulement(client, auth_headers, employee_headers):
    assert client.get(f"{RD}/scenarios", headers=employee_headers).status_code == 403
    r = client.get(f"{RD}/scenarios", headers=auth_headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["is_default"] is True and items[0]["nom"] == "Scénario de base"
    sid = items[0]["id"]
    d = client.get(f"{RD}/scenarios/{sid}", headers=auth_headers).json()
    assert d["resultats"]["totaux"]["revenus"] == 0 and d["resultats"]["parc"]["van"] == 0
    assert d["referentiel"]["categories_frais_fixes"][0]["key"] == "abonnements" and "VAN" in d["referentiel"]["valorisation_note"]
    assert [p["poste"] for p in d["data"]["depenses"]["salaires"]] == svc.POSTES_DEFAUT
    assert [a["nom"] for a in d["data"]["depenses"]["associes"]] == ["Philippe", "Steven", "Michael"]
    # Enregistrer des hypothèses → recalcul + résumé.
    r = client.put(f"{RD}/scenarios/{sid}", headers=auth_headers, json={"nom": "Base 2027", "data": _scenario_test()})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["nom"] == "Base 2027" and d["resultats"]["totaux"]["revenus"] == 1_125_350
    assert d["resume"]["benefice"] == 921_950 and d["resume"]["van"] == 6_350_000
    assert client.put(f"{RD}/scenarios/{sid}", headers=auth_headers, json={"nom": "   "}).status_code == 422
    # Copie, calcul sans enregistrer, suppression.
    r = client.post(f"{RD}/scenarios", headers=auth_headers, json={"source_id": sid})
    assert r.status_code == 201 and r.json()["nom"] == "Base 2027 (copie)" and r.json()["resultats"]["totaux"]["revenus"] == 1_125_350
    cid = r.json()["id"]
    assert client.get(f"{RD}/scenarios", headers=auth_headers).json()["total"] == 2
    r = client.post(f"{RD}/calculer", headers=auth_headers, json={"data": {"fonds": {"cash": 1_000_000, "taux_pct": 2}}})
    assert r.status_code == 200 and r.json()["resultats"]["revenus"][0]["revenu"] == 20_000
    assert client.delete(f"{RD}/scenarios/{cid}", headers=auth_headers).status_code == 204
    assert client.get(f"{RD}/scenarios/{cid}", headers=auth_headers).status_code == 404
    assert client.post(f"{RD}/scenarios", headers=employee_headers, json={}).status_code == 403


def test_api_immeubles_deja_dans_kratos(client, auth_headers, employee_headers, run):
    from app.models.immobilier import (
        Bail, BailStatus, Evaluation, Hypotheque, HypothequeStatus, Immeuble, Locataire, Logement, LogementStatus,
    )

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(name="Immeuble RD Kratos", address="77 rue du Fonds", city="Montréal", is_active=True, nb_logements=6, gestion_externe=False)
            s.add(imm)
            await s.flush()
            l1 = Logement(immeuble_id=imm.id, numero="1", status=LogementStatus.OCCUPE.value)
            l2 = Logement(immeuble_id=imm.id, numero="2", status=LogementStatus.OCCUPE.value, location_en_chambres=True, nb_chambres=3)
            loc = Locataire(full_name="Locataire RD")
            occ = Locataire(full_name="Occupant parallèle", categorie="parallele")
            s.add_all([l1, l2, loc, occ])
            await s.flush()
            s.add_all([
                Bail(logement_id=l1.id, locataire_id=loc.id, date_debut=date(2026, 1, 1), date_fin=date(2026, 12, 31), loyer_mensuel=1_000.0, status=BailStatus.ACTIF.value),
                Bail(logement_id=l2.id, locataire_id=loc.id, date_debut=date(2026, 1, 1), date_fin=date(2026, 12, 31), loyer_mensuel=1_200.0, status=BailStatus.ACTIF.value),
                Bail(logement_id=l1.id, locataire_id=loc.id, date_debut=date(2024, 1, 1), date_fin=date(2024, 12, 31), loyer_mensuel=900.0, status=BailStatus.TERMINE.value),
                Bail(logement_id=l2.id, locataire_id=occ.id, date_debut=date(2026, 1, 1), date_fin=date(2026, 12, 31), loyer_mensuel=3_000.0,
                     status=BailStatus.PARALLELE.value, categorie="parallele", parallele_type="sous_location"),
                Hypotheque(immeuble_id=imm.id, preteur="Banque RD", montant_initial=500_000.0, balance_actuelle=450_000.0, status=HypothequeStatus.ACTIVE.value),
                Hypotheque(immeuble_id=imm.id, preteur="Ancienne", montant_initial=300_000.0, balance_actuelle=0.0, status=HypothequeStatus.REMBOURSEE.value),
                Evaluation(immeuble_id=imm.id, kind="municipale", valeur=800_000.0, date_evaluation=date(2026, 1, 1), created_at=datetime.now(timezone.utc)),
                Evaluation(immeuble_id=imm.id, kind="appraisal", valeur=1_200_000.0, date_evaluation=date(2025, 6, 1), created_at=datetime.now(timezone.utc)),
            ])
            await s.commit()
            return imm.id

    imm_id = run(_seed())

    async def _seed_externe():
        async with TestSessionLocal() as s:
            ext = Immeuble(name="Immeuble RD Externe", address="9 rue Externe", city="Valcourt", is_active=True, gestion_externe=True)
            s.add(ext)
            await s.flush()
            # Gestion externe : pas de bail dans Kratos, le loyer est saisi sur le logement (occupé).
            s.add(Logement(immeuble_id=ext.id, numero="A", status=LogementStatus.OCCUPE.value, loyer_demande=1_500.0))
            s.add(Logement(immeuble_id=ext.id, numero="B", status=LogementStatus.VACANT.value, loyer_demande=1_400.0))
            await s.commit()
            return ext.id

    ext_id = run(_seed_externe())
    assert client.get(f"{RD}/immeubles-kratos", headers=employee_headers).status_code == 403
    r = client.get(f"{RD}/immeubles-kratos", headers=auth_headers)
    assert r.status_code == 200, r.text
    it = next(x for x in r.json()["items"] if x["kratos_immeuble_id"] == imm_id)
    assert it["nom"] == "Immeuble RD Kratos" and it["nb_logements"] == 2 and it["nb_chambres"] == 3
    assert it["loyers_bruts_mensuels"] == 2_200 and it["gestion_externe"] is False     # baux terminé et parallèle ignorés
    assert it["dette"] == 450_000                                                    # hypothèque active seulement
    assert it["valeur_rapport"] == 1_200_000 and it["annee_rapport"] == 2025 and it["source_rapport"] == "appraisal"
    assert it["notes_import"] == []
    # Gestion externe : même total que la liste des immeubles de Kratos (loyer saisi des unités louées), alertes claires.
    ex = next(x for x in r.json()["items"] if x["kratos_immeuble_id"] == ext_id)
    assert ex["gestion_externe"] is True and ex["loyers_bruts_mensuels"] == 1_500 and ex["nb_logements"] == 2
    assert any("rapport d'évaluation" in n for n in ex["notes_import"]) and any("hypothèque" in n for n in ex["notes_import"])
    assert not any("loyer" in n.lower() for n in ex["notes_import"])
