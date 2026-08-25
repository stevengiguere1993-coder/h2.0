"""Smoke — pôle Investisseurs : drill-down QuickBooks du tableau
« Revenus et dépenses réels » + capital restant par actionnaire.

Demande Phil (2026-08-25) : même principe que la page Optimisation —
cliquer un compte de dépense d'un mois → transactions de CE compte pour
CE mois, chacune avec sa facture jointe ouvrable. Les routes existent en
deux saveurs (console admin et portail investisseur), toutes deux
branchées sur le projet d'optimisation de la compagnie. Le portail
expose aussi le capital ENCORE investi de chaque actionnaire et
l'indicateur « la sync a déjà tourné » (pour afficher « Remboursé
complètement ! » au lieu d'un tiret).
"""
from __future__ import annotations

from datetime import date

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.entreprise import Entreprise, EntreprisePartner
from app.models.immobilier import Immeuble
from app.models.invest_portal import InvestFlux, InvestParticipation
from app.models.optimisation import OptimisationProjet
from app.models.user import User

from .conftest import TestSessionLocal

PDF = b"%PDF-1.4 facture invest"


class _FakeQbo:
    ready = True

    async def query(self, sql: str):
        if "FROM Account" in sql:
            # Plan comptable — l'auto-détection des avances cherche
            # « actionnaire » dans le nom qualifié.
            return [
                {
                    "Id": "900",
                    "Name": "Avances actionnaire — Investisseur Drill",
                    "FullyQualifiedName": (
                        "Avances actionnaire — Investisseur Drill"
                    ),
                    "AccountType": "Other Current Liability",
                    "Classification": "Liability",
                },
                {
                    "Id": "901",
                    "Name": "Avances actionnaire — Mystere Corp",
                    "FullyQualifiedName": (
                        "Avances actionnaire — Mystere Corp"
                    ),
                    "AccountType": "Other Current Liability",
                    "Classification": "Liability",
                },
            ]
        if "STARTPOSITION 1" not in sql:
            return []
        if "FROM Purchase" in sql:
            return [
                {
                    "Id": "501",
                    "TxnDate": "2026-07-08",
                    "TotalAmt": 250.0,
                    "EntityRef": {"name": "Hydro-Québec"},
                    "Line": [
                        {
                            "Amount": 250.0,
                            "AccountBasedExpenseLineDetail": {
                                "AccountRef": {"value": "77"}
                            },
                        }
                    ],
                }
            ]
        if "FROM Bill" in sql:
            return [
                {
                    "Id": "601",
                    "TxnDate": "2026-07-15",
                    "TotalAmt": 900.0,
                    "VendorRef": {"name": "Toiture Pro"},
                    "Line": [
                        {
                            "Amount": 600.0,
                            "AccountBasedExpenseLineDetail": {
                                "AccountRef": {"value": "77"}
                            },
                        },
                        {
                            "Amount": 300.0,
                            "AccountBasedExpenseLineDetail": {
                                "AccountRef": {"value": "88"}
                            },
                        },
                    ],
                }
            ]
        return []

    async def report(self, name: str, **params):
        if name == "ProfitAndLoss":
            # Une colonne de totaux : le compte 77 a dépensé 850 $.
            return {
                "Rows": {
                    "Row": [
                        {
                            "type": "Data",
                            "ColData": [
                                {
                                    "value": "Travaux et entretien",
                                    "id": "77",
                                },
                                {"value": "850.00"},
                            ],
                        }
                    ]
                }
            }
        # BalanceSheet mensuel minimal : colonne de référence + juillet.
        assert name == "BalanceSheet"
        return {
            "Columns": {
                "Column": [
                    {"ColTitle": ""},
                    {"ColTitle": "Dec 2025"},
                    {"ColTitle": "Jul 2026"},
                ]
            },
            "Rows": {
                "Row": [
                    {
                        "type": "Data",
                        "ColData": [
                            {
                                "value": (
                                    "Avances actionnaire — "
                                    "Investisseur Drill"
                                ),
                                "id": "900",
                            },
                            {"value": "0.00"},
                            {"value": "12500.00"},
                        ],
                    },
                    {
                        "type": "Data",
                        "ColData": [
                            {
                                "value": (
                                    "Avances actionnaire — Mystere Corp"
                                ),
                                "id": "901",
                            },
                            {"value": "0.00"},
                            {"value": "8000.00"},
                        ],
                    },
                ]
            },
        }

    async def list_attachables(self):
        return [
            {
                "Id": "att-51",
                "FileName": "toiture.pdf",
                "ContentType": "application/pdf",
                "AttachableRef": [
                    {"EntityRef": {"type": "Bill", "value": "601"}}
                ],
            }
        ]

    async def download_attachable(self, att_id: str):
        return PDF if att_id == "att-51" else None


@pytest.fixture()
def fake_qbo(monkeypatch) -> _FakeQbo:
    fake = _FakeQbo()
    # get_qbo est importé localement partout : patcher la source suffit.
    monkeypatch.setattr(
        "app.integrations.quickbooks.get_qbo", lambda scope: fake
    )
    return fake


@pytest.fixture(scope="module")
def invest_ids(run) -> dict:
    """Compagnie + projet d'optimisation connecté QBO + investisseur
    (volet investisseur) avec participation et flux soldés à zéro."""

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            ent = Entreprise(name="INC Invest Drill")
            imm = Immeuble(
                name="Imm Invest Drill", address="9 rue Drill",
                city="Montréal", is_active=True,
            )
            s.add_all([ent, imm])
            await s.flush()
            s.add(
                OptimisationProjet(
                    name="Projet invest drill",
                    entreprise_id=ent.id,
                    immeuble_id=imm.id,
                    qbo_scope="locatif",
                    date_debut=date(2026, 1, 1),
                )
            )
            inv = User(
                email="investisseur.drill@smoke.test",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=False,
                role="employee",
                volets_json='["investisseur"]',
            )
            s.add(inv)
            await s.flush()
            part = InvestParticipation(
                user_id=inv.id, entreprise_id=ent.id, parts_pct=25.0
            )
            s.add(part)
            s.add(
                EntreprisePartner(
                    entreprise_id=ent.id,
                    user_id=inv.id,
                    partner_name="Investisseur Drill",
                    ownership_pct=25.0,
                )
            )
            await s.flush()
            # Apport 5 000 $ puis remboursé au complet → capital 0.
            s.add_all(
                [
                    InvestFlux(
                        participation_id=part.id,
                        type="apport",
                        montant=5000,
                        date_flux=date(2026, 2, 1),
                        source="qbo",
                    ),
                    InvestFlux(
                        participation_id=part.id,
                        type="remboursement",
                        montant=5000,
                        date_flux=date(2026, 6, 1),
                        source="qbo",
                    ),
                ]
            )
            await s.commit()
            return {"entreprise_id": ent.id, "user_id": inv.id}

    return run(_seed())


@pytest.fixture(scope="module")
def invest_headers(invest_ids) -> dict:
    token = create_access_token(subject=str(invest_ids["user_id"]))
    return {"Authorization": f"Bearer {token}"}


def test_admin_transactions_d_un_compte(
    client, auth_headers, fake_qbo, invest_ids
):
    eid = invest_ids["entreprise_id"]
    r = client.get(
        f"/api/v1/invest/admin/projets/{eid}/qbo-comptes/77/transactions"
        "?debut=2026-07-01&fin=2026-07-31",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert {x["txn_id"] for x in rows} == {"501", "601"}
    par_id = {x["txn_id"]: x for x in rows}
    # Part du compte, pas le total aveugle de la facture.
    assert par_id["601"]["montant_impute"] == 600.0
    assert par_id["601"]["montant_total"] == 900.0
    assert par_id["601"]["pieces"][0]["att_id"] == "att-51"

    # Dates libres refusées (elles partent dans la requête QuickBooks).
    r2 = client.get(
        f"/api/v1/invest/admin/projets/{eid}/qbo-comptes/77/transactions"
        "?debut=n-importe-quoi&fin=2026-07-31",
        headers=auth_headers,
    )
    assert r2.status_code == 422, r2.text


def test_investisseur_transactions_et_piece(
    client, invest_headers, fake_qbo, invest_ids
):
    eid = invest_ids["entreprise_id"]
    r = client.get(
        f"/api/v1/invest/me/projets/{eid}/qbo-comptes/77/transactions"
        "?debut=2026-07-01&fin=2026-07-31",
        headers=invest_headers,
    )
    assert r.status_code == 200, r.text
    assert {x["txn_id"] for x in r.json()} == {"501", "601"}

    r2 = client.get(
        f"/api/v1/invest/me/projets/{eid}/qbo-pieces/att-51"
        "?ct=application/pdf&nom=toiture.pdf",
        headers=invest_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.content == PDF
    assert r2.headers["content-type"].startswith("application/pdf")

    # Compagnie où il n'a AUCUNE participation → porte fermée.
    r3 = client.get(
        f"/api/v1/invest/me/projets/{eid + 999}/qbo-comptes/77/"
        "transactions?debut=2026-07-01&fin=2026-07-31",
        headers=invest_headers,
    )
    assert r3.status_code == 404, r3.text


def test_portail_expose_l_etat_de_sync(
    client, invest_headers, invest_ids
):
    eid = invest_ids["entreprise_id"]
    r = client.get(
        f"/api/v1/invest/me/projets/{eid}", headers=invest_headers
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # Pas de profil (donc pas de qbo_sync_at) → False.
    assert data["apports_synchronises"] is False
    assert data["capital_actuel"] == 0.0


def test_avances_par_actionnaire_soldes_quickbooks(
    client, invest_headers, auth_headers, fake_qbo, invest_ids
):
    """La liste « Capital encore investi par actionnaire » = SOLDES des
    comptes d'avances lus dans QuickBooks (retour Phil 2026-08-25 :
    « c'est pas ça qui est dans quickbooks »), appariés par nom ; un
    compte actif sans actionnaire reconnu reste visible à part."""
    eid = invest_ids["entreprise_id"]
    r = client.get(
        f"/api/v1/invest/me/projets/{eid}/avances",
        headers=invest_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["statut"] == "connecte", data
    par_nom = {a["name"]: a for a in data["actionnaires"]}
    # Le compte « Avances actionnaire — Investisseur Drill » est
    # rattaché à l'actionnaire de la fiche, solde du bilan.
    assert par_nom["Investisseur Drill"]["solde"] == 12500.0
    assert par_nom["Investisseur Drill"]["comptes"] == [
        "Avances actionnaire — Investisseur Drill"
    ]
    # Le compte de Mystere Corp ne matche personne → listé à part,
    # jamais avalé en silence.
    assert data["autres_comptes"] == [
        {"nom": "Avances actionnaire — Mystere Corp", "solde": 8000.0}
    ]
    assert data["total"] == 20500.0

    # Même liste côté console admin.
    r2 = client.get(
        f"/api/v1/invest/admin/projets/{eid}/avances",
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["statut"] == "connecte"


def test_avances_jamais_saisies_a_la_main(
    client, auth_headers, invest_ids
):
    """Retour Phil 2026-08-25 : « Enlève la saisie manuelle » — le champ
    n'existe plus dans le PATCH du profil ; la valeur reste celle de la
    synchronisation QuickBooks."""
    eid = invest_ids["entreprise_id"]
    r = client.patch(
        f"/api/v1/invest/admin/projets/{eid}/profil",
        json={"avances_actionnaires": 123456, "show_budget": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    r2 = client.get(
        f"/api/v1/invest/admin/projets/{eid}", headers=auth_headers
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["profil"]["avances_actionnaires"] is None


def test_budget_du_projet_pour_l_investisseur(
    client, invest_headers, fake_qbo, invest_ids, run
):
    """Le portail montre les enveloppes du budget d'optimisation avec
    le dépensé réel QuickBooks, et chaque enveloppe s'ouvre sur ses
    transactions + factures (retour Phil 2026-08-25 : « je veux que mes
    investisseurs puissent voir où est-ce que leur argent a été
    dépensé »)."""
    eid = invest_ids["entreprise_id"]

    async def _lignes() -> dict:
        from sqlalchemy import select as _select

        from app.models.optimisation import (
            OptimisationBudgetLigne,
            OptimisationProjet,
        )

        async with TestSessionLocal() as s:
            pid = (
                await s.execute(
                    _select(OptimisationProjet.id).where(
                        OptimisationProjet.entreprise_id == eid
                    )
                )
            ).scalar_one()
            l1 = OptimisationBudgetLigne(
                projet_id=pid,
                nom="Travaux",
                budget_montant=10000,
                qbo_accounts_json='[{"id": "77", "name": "Travaux"}]',
            )
            l2 = OptimisationBudgetLigne(
                projet_id=pid, nom="Divers", budget_montant=5000,
            )
            s.add_all([l1, l2])
            await s.flush()
            ids = {"l1": l1.id, "l2": l2.id}
            await s.commit()
            return ids

    ids = run(_lignes())

    r = client.get(
        f"/api/v1/invest/me/projets/{eid}/budget",
        headers=invest_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["statut"] == "connecte", data
    par_nom = {l["nom"]: l for l in data["lignes"]}
    # Dépensé réel du P&L QuickBooks (850 $ sur le compte 77).
    assert par_nom["Travaux"]["depense"] == 850.0
    assert par_nom["Travaux"]["reste"] == 9150.0
    assert par_nom["Divers"]["depense"] == 0.0
    assert data["total"]["budget"] == 15000.0

    # L'enveloppe s'ouvre sur SES transactions, factures comprises.
    r2 = client.get(
        f"/api/v1/invest/me/projets/{eid}"
        f"/qbo-lignes/{ids['l1']}/transactions",
        headers=invest_headers,
    )
    assert r2.status_code == 200, r2.text
    rows = r2.json()
    assert {x["txn_id"] for x in rows} == {"501", "601"}
    par_id = {x["txn_id"]: x for x in rows}
    assert par_id["601"]["montant_impute"] == 600.0
    assert par_id["601"]["pieces"][0]["att_id"] == "att-51"

    # Enveloppe inexistante (ou d'un autre projet) → 404 propre.
    r3 = client.get(
        f"/api/v1/invest/me/projets/{eid}"
        "/qbo-lignes/999999/transactions",
        headers=invest_headers,
    )
    assert r3.status_code == 404, r3.text
