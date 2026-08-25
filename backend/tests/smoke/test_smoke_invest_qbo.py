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


def test_portail_expose_restants_et_etat_de_sync(
    client, invest_headers, invest_ids
):
    """La fiche projet porte le capital ENCORE investi par actionnaire
    (ici remboursé au complet → 0) et l'indicateur de première sync."""
    eid = invest_ids["entreprise_id"]
    r = client.get(
        f"/api/v1/invest/me/projets/{eid}", headers=invest_headers
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "apports_synchronises" in data
    # Pas de profil (donc pas de qbo_sync_at) → False.
    assert data["apports_synchronises"] is False
    assert data["capital_actuel"] == 0.0
    moi = [a for a in data["actionnaires"] if a["is_me"]]
    assert len(moi) == 1
    assert moi[0]["capital_actuel"] == 0.0
