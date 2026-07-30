"""Smoke — Projets - Optimisation (2026-07-29).

CRUD projet/budget/négos + réels locatifs (baux actifs, dépenses
courantes) + seed des locataires. QuickBooks n'est pas appelé ici (pas
de connexion en test) — on vérifie le parsing PUR du rapport P&L et le
message d'erreur propre quand rien n'est connecté.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from app.services.qbo_optimisation import _walk_rows


def test_walk_rows_pnl():
    """Parse un extrait réaliste de rapport ProfitAndLoss QBO."""
    report_rows = [
        {
            "Header": {"ColData": [{"value": "Dépenses"}]},
            "Rows": {
                "Row": [
                    {
                        "ColData": [
                            {"value": "Frais professionnels", "id": "77"},
                            {"value": "12,345.67"},
                        ],
                        "type": "Data",
                    },
                    {
                        "Header": {
                            "ColData": [{"value": "Travaux", "id": "80"}]
                        },
                        "Rows": {
                            "Row": [
                                {
                                    "ColData": [
                                        {"value": "Plomberie", "id": "81"},
                                        {"value": "1000.00"},
                                    ],
                                    "type": "Data",
                                }
                            ]
                        },
                        "Summary": {
                            "ColData": [
                                {"value": "Total Travaux"},
                                {"value": "1000.00"},
                            ]
                        },
                    },
                ]
            },
        }
    ]
    totals: dict[str, float] = {}
    _walk_rows(report_rows, totals)
    assert totals["77"] == 12345.67
    assert totals["81"] == 1000.0


def test_resume_pnl_rentabilite():
    """Les totaux de section d'un ProfitAndLoss donnent la rentabilité :
    revenus, dépenses et résultat net (négatif = perte)."""
    from app.services.qbo_optimisation import _groupes_pnl

    rapport = [
        {
            "group": "Income",
            "Summary": {
                "ColData": [{"value": "Total Income"}, {"value": "40,000.00"}]
            },
        },
        {
            "group": "Expenses",
            "Summary": {
                "ColData": [
                    {"value": "Total Expenses"},
                    {"value": "50,000.00"},
                ]
            },
        },
        {
            "group": "NetIncome",
            "Summary": {
                "ColData": [{"value": "Net Income"}, {"value": "-10,000.00"}]
            },
        },
    ]
    out: dict[str, float] = {}
    _groupes_pnl(rapport, out)
    assert out["Income"] == 40000.0
    assert out["Expenses"] == 50000.0
    assert out["NetIncome"] == -10000.0


def test_cashflow_mensuel_assemblage():
    """Le P&L ventilé par mois devient un cashflow lisible : une ligne
    par mois (revenus / dépenses / écart + détail par compte) et un
    total dont le déficit nourrit l'enveloppe Budget de détention."""
    from app.services.qbo_optimisation import (
        _assembler_cashflow,
        _comptes_par_colonne,
        _groupes_pnl_colonnes,
    )

    rapport = [
        {
            "group": "Income",
            "Rows": {
                "Row": [
                    {
                        "type": "Data",
                        "ColData": [
                            {"value": "Revenus de loyers", "id": "4"},
                            {"value": "1,000.00"},
                            {"value": "2,000.00"},
                            {"value": "3,000.00"},
                        ],
                    }
                ]
            },
            "Summary": {
                "ColData": [
                    {"value": "Total Income"},
                    {"value": "1,000.00"},
                    {"value": "2,000.00"},
                    {"value": "3,000.00"},
                ]
            },
        },
        {
            "group": "Expenses",
            "Rows": {
                "Row": [
                    {
                        "type": "Data",
                        "ColData": [
                            {"value": "Intérêts hypothécaires", "id": "61"},
                            {"value": "4,000.00"},
                            {"value": "1,500.00"},
                            {"value": "5,500.00"},
                        ],
                    }
                ]
            },
            "Summary": {
                "ColData": [
                    {"value": "Total Expenses"},
                    {"value": "4,000.00"},
                    {"value": "1,500.00"},
                    {"value": "5,500.00"},
                ]
            },
        },
        {
            "group": "NetIncome",
            "Summary": {
                "ColData": [
                    {"value": "Net Income"},
                    {"value": "-3,000.00"},
                    {"value": "500.00"},
                    {"value": "-2,500.00"},
                ]
            },
        },
    ]
    groupes: dict[str, list[float]] = {}
    _groupes_pnl_colonnes(rapport, groupes)
    comptes: list[dict] = []
    _comptes_par_colonne(rapport, comptes)
    cf = _assembler_cashflow(
        ["Jul 2024", "Aug 2024", "Total"], groupes, comptes
    )

    assert len(cf["mois"]) == 2
    assert cf["mois"][0]["revenus"] == 1000.0
    assert cf["mois"][0]["depenses"] == 4000.0
    assert cf["mois"][0]["ecart"] == -3000.0
    assert cf["mois"][1]["ecart"] == 500.0
    assert cf["total"] == {
        "revenus": 3000.0,
        "depenses": 5500.0,
        "hypotheque": 0.0,
        "ecart": -2500.0,
        "details": cf["total"]["details"],
    }
    # Détail par compte : le loyer (revenu) puis l'intérêt (dépense) —
    # exactement ce que Phil veut voir en dépliant un mois.
    d0 = cf["mois"][0]["details"]
    assert d0[0] == {
        "nom": "Revenus de loyers", "type": "revenu", "montant": 1000.0
    }
    assert d0[1] == {
        "nom": "Intérêts hypothécaires",
        "type": "depense",
        "montant": 4000.0,
    }
    assert cf["total"]["details"][1]["montant"] == 5500.0
    # Détention v13 : dépensé = −écart total, SIGNÉ (un surplus
    # redonnerait du budget).
    assert -cf["total"]["ecart"] == 2500.0

    # v13 : colonne Hypothèque (capital remboursé, lu du bilan) —
    # l'écart devient revenus − dépenses − hypothèque.
    cf2 = _assembler_cashflow(
        ["Jul 2024", "Aug 2024", "Total"],
        groupes,
        comptes,
        [500.0, 500.0, 1000.0],
    )
    assert cf2["mois"][0]["hypotheque"] == 500.0
    assert cf2["mois"][0]["ecart"] == -3500.0  # -3000 - 500
    assert cf2["mois"][1]["ecart"] == 0.0  # 500 - 500
    assert cf2["total"]["hypotheque"] == 1000.0
    assert cf2["total"]["ecart"] == -3500.0
    assert -cf2["total"]["ecart"] == 3500.0  # Détention


def test_bilan_mensuel_et_avances():
    """Le BILAN ventilé par mois donne, par compte, la série des soldes
    de fin de mois. Les avances des actionnaires en tirent le solde et
    le flux mensuel ; l'hypothèque du cashflow, le capital remboursé.
    La 1re colonne est un mois de RÉFÉRENCE (demandé un mois avant le
    début du projet) : elle rend la variation du 1er mois calculable."""
    from app.services.qbo_optimisation import (
        _assembler_avances,
        _soldes_par_compte_colonnes,
    )

    bilan = [
        {
            "group": "Liabilities",
            "Rows": {
                "Row": [
                    {
                        "type": "Data",
                        "ColData": [
                            {
                                "value": "Avances des actionnaires — Steven",
                                "id": "70",
                            },
                            {"value": "1,000.00"},
                            {"value": "6,000.00"},
                            {"value": "6,000.00"},
                        ],
                    },
                    {
                        "type": "Data",
                        "ColData": [
                            {"value": "Hypothèque 8900", "id": "88"},
                            {"value": "300,000.00"},
                            {"value": "299,500.00"},
                            {"value": "299,000.00"},
                        ],
                    },
                ]
            },
        }
    ]
    series: dict[str, dict] = {}
    _soldes_par_compte_colonnes(bilan, series)
    assert series["70"]["vals"] == [1000.0, 6000.0, 6000.0]
    assert series["88"]["nom"] == "Hypothèque 8900"

    # Avances : titres[0] = mois de référence, jeté des lignes.
    av = _assembler_avances(
        ["Dec 2025", "Jan 2026", "Feb 2026"],
        series,
        [{"id": "70", "name": "Avances des actionnaires — Steven"}],
    )
    assert len(av["comptes"]) == 1
    c = av["comptes"][0]
    assert c["solde"] == 6000.0
    assert c["mois"] == [
        {"mois": "Jan 2026", "variation": 5000.0, "solde": 6000.0},
        {"mois": "Feb 2026", "variation": 0.0, "solde": 6000.0},
    ]
    assert av["total"] == 6000.0

    # Hypothèque : la BAISSE du passif = le capital remboursé du mois.
    vals = series["88"]["vals"]
    variations = [vals[i - 1] - vals[i] for i in range(1, len(vals))]
    assert variations == [500.0, 500.0]

    # Compte inconnu de la sélection manuelle → solde 0, aucun mois.
    vide = _assembler_avances(
        ["Dec 2025", "Jan 2026"], series, [{"id": "999", "name": "X"}]
    )
    assert vide["comptes"][0]["solde"] == 0.0
    assert vide["comptes"][0]["mois"] == []


def test_qbo_scope_inc(client, auth_headers):
    """Les scopes dynamiques « inc:{entreprise_id} » sont acceptés par le
    flux de connexion QBO (un fichier QuickBooks par INC)."""
    r = client.get(
        "/api/v1/qbo/status?scope=inc:12", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["connected"] is False  # rien de connecté en test

    bad = client.get(
        "/api/v1/qbo/status?scope=nimporte", headers=auth_headers
    )
    assert bad.status_code == 422
    bad2 = client.get(
        "/api/v1/qbo/status?scope=inc:abc", headers=auth_headers
    )
    assert bad2.status_code == 422


def _seed_immeuble(run):
    from app.models.immobilier import (
        Bail,
        BailStatus,
        DepenseImmeuble,
        Immeuble,
        Locataire,
        Logement,
        LogementStatus,
    )

    from .conftest import TestSessionLocal

    async def _s():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Optimisation Smoke", address="1 rue Opti",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg1 = Logement(
                immeuble_id=imm.id, numero="101",
                status=LogementStatus.OCCUPE.value,
            )
            lg2 = Logement(
                immeuble_id=imm.id, numero="102",
                status=LogementStatus.OCCUPE.value,
            )
            loc1 = Locataire(full_name="Alice Opti")
            loc2 = Locataire(full_name="Bob Opti")
            s.add_all([lg1, lg2, loc1, loc2])
            await s.flush()
            s.add_all(
                [
                    Bail(
                        logement_id=lg1.id, locataire_id=loc1.id,
                        date_debut=date.today() - timedelta(days=200),
                        date_fin=date.today() + timedelta(days=165),
                        loyer_mensuel=800.0,
                        status=BailStatus.ACTIF.value,
                    ),
                    Bail(
                        logement_id=lg2.id, locataire_id=loc2.id,
                        date_debut=date.today() - timedelta(days=100),
                        date_fin=date.today() + timedelta(days=265),
                        loyer_mensuel=700.0,
                        status=BailStatus.ACTIF.value,
                    ),
                    DepenseImmeuble(
                        immeuble_id=imm.id, categorie="energie",
                        libelle="Hydro", montant=120.0, frequence="mensuel",
                    ),
                    DepenseImmeuble(
                        immeuble_id=imm.id, categorie="taxes_municipales",
                        libelle="Taxes", montant=6000.0, frequence="annuel",
                    ),
                ]
            )
            await s.commit()
            return imm.id

    return run(_s())


def test_projet_complet(client, auth_headers, run):
    from app.models.entreprise import Entreprise

    from .conftest import TestSessionLocal

    async def _ent():
        async with TestSessionLocal() as s:
            e = Entreprise(name="INC Opti Smoke")
            s.add(e)
            await s.commit()
            return e.id

    ent_id = run(_ent())
    imm_id = _seed_immeuble(run)

    # Création + seed des locataires à baux actifs.
    r = client.post(
        "/api/v1/optimisation/projets",
        headers=auth_headers,
        json={
            "name": "Opti 1 rue Opti",
            "entreprise_id": ent_id,
            "immeuble_id": imm_id,
            "date_debut": "2026-01-01",
        },
    )
    assert r.status_code == 201, r.text
    p = r.json()
    pid = p["id"]
    assert p["entreprise_nom"] == "INC Opti Smoke"
    # Réels locatifs : 800 + 700 de loyers ; 120 + 6000/12 = 620 de dépenses.
    assert p["revenus_actuels_mensuels"] == 1500.0
    assert p["depenses_actuelles_mensuelles"] == 620.0
    # v5 : plus d'import automatique des locataires à la création.
    assert p["negos"] == []
    imp0 = client.post(
        f"/api/v1/optimisation/projets/{pid}/importer-locataires",
        headers=auth_headers,
    )
    assert imp0.status_code == 200
    assert imp0.json()["created"] == 2
    noms = {
        n["nom_locataire"]
        for n in client.get(
            f"/api/v1/optimisation/projets/{pid}", headers=auth_headers
        ).json()["negos"]
    }
    assert noms == {"Alice Opti", "Bob Opti"}

    # Budget : enveloppe + édition + mapping QBO stocké tel quel.
    b = client.post(
        f"/api/v1/optimisation/projets/{pid}/budget-lignes",
        headers=auth_headers,
        json={"nom": "Frais professionnels", "budget_montant": 25000},
    )
    assert b.status_code == 201, b.text
    lid = b.json()["id"]
    u = client.patch(
        f"/api/v1/optimisation/budget-lignes/{lid}",
        headers=auth_headers,
        json={
            "qbo_accounts_json": json.dumps(
                [{"id": "77", "name": "Frais professionnels"}]
            )
        },
    )
    assert u.status_code == 200, u.text

    # Dépenses QBO : rien de connecté en test → erreur PROPRE, pas de 500.
    q = client.get(
        f"/api/v1/optimisation/projets/{pid}/qbo-depenses",
        headers=auth_headers,
    )
    assert q.status_code == 200, q.text
    assert q.json()["erreur"]  # scope absent → message explicite

    client.patch(
        f"/api/v1/optimisation/projets/{pid}",
        headers=auth_headers,
        json={"qbo_scope": "immobilier"},
    )
    q2 = client.get(
        f"/api/v1/optimisation/projets/{pid}/qbo-depenses",
        headers=auth_headers,
    )
    assert q2.status_code == 200
    assert "connecté" in (q2.json()["erreur"] or "")

    # Objectifs : PATCH revenus + « il manque » côté front (données OK).
    o = client.patch(
        f"/api/v1/optimisation/projets/{pid}",
        headers=auth_headers,
        json={"objectif_revenus_mensuels": 2000},
    )
    assert o.status_code == 200
    assert float(o.json()["objectif_revenus_mensuels"]) == 2000.0

    # v2 : historique mensuel des revenus (reconstitué des baux) +
    # compteur de logements.
    d0 = client.get(
        f"/api/v1/optimisation/projets/{pid}", headers=auth_headers
    ).json()
    assert d0["nb_logements"] == 2
    histo = d0["revenus_historique"]
    assert histo, "historique vide"
    assert histo[-1]["montant"] == 1500.0  # mois courant : les 2 baux
    assert all("mois" in h and "montant" in h for h in histo)

    # v2 : import sélectif — liste des disponibles puis choix.
    dispo = client.get(
        f"/api/v1/optimisation/projets/{pid}/locataires-disponibles",
        headers=auth_headers,
    )
    assert dispo.status_code == 200, dispo.text
    assert all(x["deja_suivi"] for x in dispo.json())  # seed les a pris

    # v5 : financement + comptant par enveloppe, objectifs annuels,
    # compte bancaire du projet, recherche locataire.
    v5 = client.patch(
        f"/api/v1/optimisation/budget-lignes/{lid}",
        headers=auth_headers,
        json={
            "comptant_disponible": 20000,
            "qbo_financement_accounts_json": json.dumps(
                [{"id": "90", "name": "Marge de crédit"}]
            ),
        },
    )
    assert v5.status_code == 200, v5.text
    assert float(v5.json()["comptant_disponible"]) == 20000.0
    assert "Marge" in (v5.json()["qbo_financement_accounts_json"] or "")

    o5 = client.patch(
        f"/api/v1/optimisation/projets/{pid}",
        headers=auth_headers,
        json={
            "objectif_revenus_annuels": 24000,
            "qbo_bank_account_id": "35",
            "qbo_bank_account_name": "Compte projet",
        },
    )
    assert o5.status_code == 200, o5.text
    assert float(o5.json()["objectif_revenus_annuels"]) == 24000.0
    assert o5.json()["qbo_bank_account_name"] == "Compte projet"

    # v13 : compte d'hypothèque + comptes d'avances (roundtrip).
    v13 = client.patch(
        f"/api/v1/optimisation/projets/{pid}",
        headers=auth_headers,
        json={
            "qbo_hypotheque_account_id": "88",
            "qbo_hypotheque_account_name": "Hypothèque 8900",
            "avances_accounts_json": json.dumps(
                [{"id": "70", "name": "Avances des actionnaires"}]
            ),
        },
    )
    assert v13.status_code == 200, v13.text
    assert v13.json()["qbo_hypotheque_account_name"] == "Hypothèque 8900"
    assert "70" in (v13.json()["avances_accounts_json"] or "")

    # Avances sans connexion QBO → erreur PROPRE, pas de 500.
    av = client.get(
        f"/api/v1/optimisation/projets/{pid}/qbo-avances",
        headers=auth_headers,
    )
    assert av.status_code == 200, av.text
    assert av.json()["erreur"]

    # La réponse QBO expose les 3 blocs même sans connexion (erreur propre).
    q5 = client.get(
        f"/api/v1/optimisation/projets/{pid}/qbo-depenses",
        headers=auth_headers,
    ).json()
    assert "financement_par_ligne" in q5 and "solde_bancaire" in q5
    assert "cashflow" in q5  # v11 — présent même sans connexion QBO
    assert "hypotheque_configuree" in q5  # v13

    # v10 : enveloppe Budget de détention (dépensé = déficit
    # d'opération). CRUD + validation du mode.
    det = client.post(
        f"/api/v1/optimisation/projets/{pid}/budget-lignes",
        headers=auth_headers,
        json={
            "nom": "Détention",
            "budget_montant": 50000,
            "mode": "deficit_operation",
        },
    )
    assert det.status_code == 201, det.text
    assert det.json()["mode"] == "deficit_operation"
    assert (
        client.post(
            f"/api/v1/optimisation/projets/{pid}/budget-lignes",
            headers=auth_headers,
            json={"nom": "X", "mode": "nimporte"},
        ).status_code
        == 422
    )

    # Les comptes se listent par famille (validation du paramètre kind).
    for kind in (
        "depense", "financement", "banque", "hypotheque", "avances"
    ):
        assert (
            client.get(
                f"/api/v1/optimisation/qbo-comptes?scope=immobilier&kind={kind}",
                headers=auth_headers,
            ).status_code
            == 200
        )
    assert (
        client.get(
            "/api/v1/optimisation/qbo-comptes?scope=immobilier&kind=nimporte",
            headers=auth_headers,
        ).status_code
        == 422
    )

    # Négos : statut + entente + timeline (append).
    nid = client.get(
        f"/api/v1/optimisation/projets/{pid}", headers=auth_headers
    ).json()["negos"][0]["id"]
    n = client.patch(
        f"/api/v1/optimisation/negos/{nid}",
        headers=auth_headers,
        json={
            "statut": "en_discussion",
            "add_event": "Premier appel — ouvert à discuter.",
        },
    )
    assert n.status_code == 200, n.text
    d = n.json()
    assert d["statut"] == "en_discussion"
    assert "Premier appel" in (d["events_json"] or "")
    # v2 : type d'entente valide / invalide.
    te = client.patch(
        f"/api/v1/optimisation/negos/{nid}",
        headers=auth_headers,
        json={"type_entente": "cash_for_keys"},
    )
    assert te.status_code == 200, te.text
    assert te.json()["type_entente"] == "cash_for_keys"
    # v5 : préparation de la négo (recherche sur le locataire).
    rc = client.patch(
        f"/api/v1/optimisation/negos/{nid}",
        headers=auth_headers,
        json={
            "recherche_json": json.dumps(
                {"emploi": "électricien", "employeur": "Hydro"}
            )
        },
    )
    assert rc.status_code == 200, rc.text
    # json.dumps échappe les accents (é) — on relit la structure.
    assert json.loads(rc.json()["recherche_json"])["emploi"] == "électricien"
    assert (
        client.patch(
            f"/api/v1/optimisation/negos/{nid}",
            headers=auth_headers,
            json={"type_entente": "nimporte"},
        ).status_code
        == 422
    )
    # v2 : depart_prevu retiré des statuts valides.
    assert (
        client.patch(
            f"/api/v1/optimisation/negos/{nid}",
            headers=auth_headers,
            json={"statut": "depart_prevu"},
        ).status_code
        == 422
    )
    bad = client.patch(
        f"/api/v1/optimisation/negos/{nid}",
        headers=auth_headers,
        json={"statut": "nimporte"},
    )
    assert bad.status_code == 422

    # Ré-import : aucun doublon.
    imp = client.post(
        f"/api/v1/optimisation/projets/{pid}/importer-locataires",
        headers=auth_headers,
    )
    assert imp.status_code == 200
    assert imp.json()["created"] == 0

    # Liste : tuile avec budget total + nb négos.
    lst = client.get("/api/v1/optimisation/projets", headers=auth_headers)
    assert lst.status_code == 200
    tuile = next(x for x in lst.json() if x["id"] == pid)
    # 25 000 (Frais professionnels) + 50 000 (Détention, v10).
    assert tuile["budget_total"] == 75000.0
    assert tuile["nb_negos"] == 2

    # Suppression en cascade.
    dl = client.delete(
        f"/api/v1/optimisation/projets/{pid}", headers=auth_headers
    )
    assert dl.status_code == 204
    assert (
        client.get(
            f"/api/v1/optimisation/projets/{pid}", headers=auth_headers
        ).status_code
        == 404
    )
