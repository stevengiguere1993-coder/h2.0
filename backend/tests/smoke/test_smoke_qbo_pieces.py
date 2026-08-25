"""Smoke — factures PDF de QuickBooks dans la page Optimisation.

Demande Phil (2026-08-22) : « j'aimerais avoir les factures PDF reliées
à ces dépenses-là dans mon portail ». La page n'affichait que des TOTAUX
par enveloppe (rapport P&L) ; les pièces jointes vivent sur les
TRANSACTIONS. D'où deux nouveaux endpoints, testés ici avec un client
QuickBooks factice :

- le DÉTAIL d'une enveloppe : Bills + Purchases dont une ligne impute un
  des comptes mappés, la part imputée (pas le total aveugle), et leurs
  pièces jointes ;
- la PIÈCE servie en direct, sans stockage, avec un type MIME jamais
  avalé tel quel.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.models.entreprise import Entreprise
from app.models.immobilier import Immeuble
from app.models.optimisation import OptimisationBudgetLigne, OptimisationProjet

from .conftest import TestSessionLocal

PDF = b"%PDF-1.4 fake facture"


class _FakeQbo:
    ready = True

    async def query(self, sql: str):
        if "STARTPOSITION 1" not in sql:
            return []
        if "FROM Purchase" in sql:
            return [
                {
                    # Touche le compte mappé 64 ET un autre : seule la
                    # part du 64 doit compter.
                    "Id": "201",
                    "TxnDate": "2026-08-03",
                    "TotalAmt": 300.0,
                    "EntityRef": {"name": "Rona"},
                    "DocNumber": "R-77",
                    "PrivateNote": "Peinture corridors",
                    "Line": [
                        {
                            "Amount": 100.0,
                            "AccountBasedExpenseLineDetail": {
                                "AccountRef": {"value": "64"}
                            },
                        },
                        {
                            "Amount": 200.0,
                            "AccountBasedExpenseLineDetail": {
                                "AccountRef": {"value": "99"}
                            },
                        },
                    ],
                },
                {
                    # Aucun compte mappé : ne doit PAS apparaître.
                    "Id": "202",
                    "TxnDate": "2026-08-04",
                    "TotalAmt": 50.0,
                    "Line": [
                        {
                            "Amount": 50.0,
                            "AccountBasedExpenseLineDetail": {
                                "AccountRef": {"value": "99"}
                            },
                        }
                    ],
                },
            ]
        if "FROM Bill" in sql:
            return [
                {
                    "Id": "301",
                    "TxnDate": "2026-08-10",
                    "TotalAmt": 450.0,
                    "VendorRef": {"name": "Plomberie Roy"},
                    "Line": [
                        {
                            "Amount": 450.0,
                            "AccountBasedExpenseLineDetail": {
                                "AccountRef": {"value": "64"}
                            },
                        }
                    ],
                }
            ]
        return []

    async def list_attachables(self):
        return [
            {
                "Id": "att-9",
                "FileName": "facture-roy.pdf",
                "ContentType": "application/pdf",
                "AttachableRef": [
                    {"EntityRef": {"type": "Bill", "value": "301"}}
                ],
            }
        ]

    async def download_attachable(self, att_id: str):
        return PDF if att_id == "att-9" else None


@pytest.fixture()
def fake_qbo(monkeypatch) -> _FakeQbo:
    fake = _FakeQbo()
    # get_qbo est importé LOCALEMENT dans chaque fonction du service et
    # de l'endpoint : patcher la source suffit pour les deux.
    monkeypatch.setattr(
        "app.integrations.quickbooks.get_qbo", lambda scope: fake
    )
    return fake


@pytest.fixture()
def projet_ids(run) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            ent = Entreprise(name="Ent QBO Pieces")
            imm = Immeuble(
                name="Imm QBO Pieces", address="1 rue QBO",
                city="Montréal", is_active=True,
            )
            s.add_all([ent, imm])
            await s.flush()
            p = OptimisationProjet(
                name="Projet pièces",
                entreprise_id=ent.id,
                immeuble_id=imm.id,
                qbo_scope="locatif",
                date_debut=date(2026, 1, 1),
            )
            s.add(p)
            await s.flush()
            ligne = OptimisationBudgetLigne(
                projet_id=p.id,
                nom="Entretien",
                qbo_accounts_json='[{"id": "64", "name": "Entretien"}]',
            )
            vide = OptimisationBudgetLigne(
                projet_id=p.id, nom="Sans comptes",
            )
            s.add_all([ligne, vide])
            await s.flush()
            await s.commit()
            return {
                "projet_id": p.id,
                "ligne_id": ligne.id,
                "ligne_vide_id": vide.id,
            }

    return run(_seed())


def test_detail_d_une_enveloppe_avec_pieces(
    client, auth_headers, fake_qbo, projet_ids
):
    r = client.get(
        f"/api/v1/optimisation/projets/{projet_ids['projet_id']}"
        f"/qbo-lignes/{projet_ids['ligne_id']}/transactions",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    # La transaction 202 (aucun compte mappé) est exclue.
    assert {x["txn_id"] for x in rows} == {"201", "301"}

    par_id = {x["txn_id"]: x for x in rows}
    # Seule la PART imputée aux comptes de l'enveloppe compte — pas le
    # total aveugle de la transaction.
    assert par_id["201"]["montant_impute"] == 100.0
    assert par_id["201"]["montant_total"] == 300.0
    assert par_id["201"]["fournisseur"] == "Rona"
    assert par_id["201"]["pieces"] == []

    # Le Bill porte sa facture PDF.
    assert par_id["301"]["fournisseur"] == "Plomberie Roy"
    pieces = par_id["301"]["pieces"]
    assert len(pieces) == 1
    assert pieces[0]["att_id"] == "att-9"
    assert pieces[0]["file_name"] == "facture-roy.pdf"


def test_ligne_sans_comptes_retourne_vide(
    client, auth_headers, fake_qbo, projet_ids
):
    r = client.get(
        f"/api/v1/optimisation/projets/{projet_ids['projet_id']}"
        f"/qbo-lignes/{projet_ids['ligne_vide_id']}/transactions",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_piece_servie_en_direct_et_type_mime_encadre(
    client, auth_headers, fake_qbo, projet_ids
):
    base = (
        f"/api/v1/optimisation/projets/{projet_ids['projet_id']}"
        "/qbo-pieces/att-9"
    )
    r = client.get(
        f"{base}?ct=application/pdf&nom=facture-roy.pdf",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.content == PDF
    assert r.headers["content-type"].startswith("application/pdf")
    assert "facture-roy.pdf" in r.headers.get("content-disposition", "")

    # Un type farfelu fourni par le client ne passe JAMAIS tel quel.
    r2 = client.get(f"{base}?ct=text/html", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("application/octet-stream")

    # Pièce inconnue → 404 propre.
    r3 = client.get(
        f"/api/v1/optimisation/projets/{projet_ids['projet_id']}"
        "/qbo-pieces/att-inexistante",
        headers=auth_headers,
    )
    assert r3.status_code == 404, r3.text
