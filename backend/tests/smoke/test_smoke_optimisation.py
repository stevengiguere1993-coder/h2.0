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
    noms = {n["nom_locataire"] for n in p["negos"]}
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

    # Négos : statut + entente + timeline (append).
    nid = p["negos"][0]["id"]
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
    assert tuile["budget_total"] == 25000.0
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
