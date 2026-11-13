"""Smoke — Codes d'accès d'un immeuble (bug mvilliard 2026-10-17).

« Ajouter un endroit pour code de porte, code lock box et autre code
relié à l'immeuble » sur la fiche /immobilier/immeubles/{id} :
- une liste de codes par immeuble (libellé, code, note), ordonnée ;
- ajout / modification / retrait depuis la fiche ;
- visible par quiconque voit l'immeuble : manager+ toujours, employé
  seulement s'il est affecté à l'immeuble (403 sinon) ;
- cliquet IA + liste MCP « immeuble_codes ».
"""
from __future__ import annotations

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.immobilier import Immeuble
from app.models.user import User
from app.models.user_immeuble import UserImmeuble
from tests.smoke.conftest import TestSessionLocal

IMM = "/api/v1/immobilier/immeubles"


@pytest.fixture(scope="module")
def codes_seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="710 Legendre (codes)", address="710 rue Legendre",
                city="Montréal", is_active=True,
            )
            autre = Immeuble(
                name="9085 Millen (codes)", address="9085 rue Millen",
                city="Montréal", is_active=True,
            )
            # Employé du volet immobilier, affecté à UN seul immeuble.
            emp = User(
                email="smoke-codes-employe@example.com",
                hashed_password=get_password_hash("Sm0keCodes!42"),
                is_active=True, is_admin=False, role="employee",
                volets_json='["immobilier"]',
            )
            s.add_all([imm, autre, emp])
            await s.flush()
            s.add(UserImmeuble(user_id=emp.id, immeuble_id=imm.id))
            await s.commit()
            return {"imm": imm.id, "autre": autre.id, "emp": emp.id}

    return run(_seed())


@pytest.fixture(scope="module")
def emp_headers(codes_seed) -> dict:
    return {"Authorization": f"Bearer {create_access_token(subject=str(codes_seed['emp']))}"}


def test_crud_codes_immeuble(client, auth_headers, codes_seed):
    imm = codes_seed["imm"]
    assert client.get(f"{IMM}/{imm}/codes", headers=auth_headers).json() == []

    # Ajout : porte, lock box, garage — l'ordre d'ajout est conservé.
    r = client.post(f"{IMM}/{imm}/codes", headers=auth_headers,
                    json={"libelle": "Porte d'entrée", "code": "1234#"})
    assert r.status_code == 201, r.text
    porte = r.json()
    assert porte["immeuble_id"] == imm and porte["libelle"] == "Porte d'entrée"
    assert porte["code"] == "1234#" and porte["note"] is None
    assert porte["created_by_email"] == "smoke-admin@example.com"
    r = client.post(f"{IMM}/{imm}/codes", headers=auth_headers,
                    json={"libelle": "  Lock box ", "code": " 0710 ", "note": "  Boîte grise à gauche de la porte  "})
    assert r.status_code == 201, r.text
    lockbox = r.json()
    assert lockbox["libelle"] == "Lock box" and lockbox["code"] == "0710"
    assert lockbox["note"] == "Boîte grise à gauche de la porte"
    r = client.post(f"{IMM}/{imm}/codes", headers=auth_headers,
                    json={"libelle": "Garage", "code": "*55"})
    assert r.status_code == 201
    garage = r.json()
    assert porte["position"] < lockbox["position"] < garage["position"]

    # Libellé ou code vide → refus.
    assert client.post(f"{IMM}/{imm}/codes", headers=auth_headers,
                       json={"libelle": "   ", "code": "1"}).status_code == 422
    assert client.post(f"{IMM}/{imm}/codes", headers=auth_headers,
                       json={"libelle": "Alarme", "code": ""}).status_code == 422
    # Immeuble inconnu → 404.
    assert client.post(f"{IMM}/999999/codes", headers=auth_headers,
                       json={"libelle": "Alarme", "code": "1"}).status_code == 404

    r = client.get(f"{IMM}/{imm}/codes", headers=auth_headers)
    assert [x["libelle"] for x in r.json()] == ["Porte d'entrée", "Lock box", "Garage"]

    # Modification partielle : le code change, le reste reste.
    r = client.patch(f"{IMM}/{imm}/codes/{porte['id']}", headers=auth_headers,
                     json={"code": "4321#", "note": "Changé le 18 oct."})
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "4321#" and r.json()["libelle"] == "Porte d'entrée"
    assert r.json()["note"] == "Changé le 18 oct."
    # Vider la note → NULL.
    assert client.patch(f"{IMM}/{imm}/codes/{porte['id']}", headers=auth_headers,
                        json={"note": "  "}).json()["note"] is None
    # Réordonner : la porte passe en dernier.
    r = client.patch(f"{IMM}/{imm}/codes/{porte['id']}", headers=auth_headers,
                     json={"position": 99})
    assert r.status_code == 200
    assert [x["libelle"] for x in client.get(f"{IMM}/{imm}/codes", headers=auth_headers).json()] == ["Lock box", "Garage", "Porte d'entrée"]

    # Un code ne se modifie / retire pas via un AUTRE immeuble.
    autre = codes_seed["autre"]
    assert client.patch(f"{IMM}/{autre}/codes/{porte['id']}", headers=auth_headers,
                        json={"code": "x"}).status_code == 404
    assert client.delete(f"{IMM}/{autre}/codes/{porte['id']}", headers=auth_headers).status_code == 404
    assert client.get(f"{IMM}/{autre}/codes", headers=auth_headers).json() == []

    # Retrait.
    assert client.delete(f"{IMM}/{imm}/codes/{garage['id']}", headers=auth_headers).status_code == 204
    assert client.delete(f"{IMM}/{imm}/codes/{garage['id']}", headers=auth_headers).status_code == 404
    assert [x["libelle"] for x in client.get(f"{IMM}/{imm}/codes", headers=auth_headers).json()] == ["Lock box", "Porte d'entrée"]


def test_codes_visibles_par_qui_voit_l_immeuble(client, emp_headers, codes_seed):
    imm, autre = codes_seed["imm"], codes_seed["autre"]
    # Employé affecté au 710 Legendre : il voit et gère ses codes…
    r = client.get(f"{IMM}/{imm}/codes", headers=emp_headers)
    assert r.status_code == 200, r.text
    assert {x["libelle"] for x in r.json()} == {"Lock box", "Porte d'entrée"}
    r = client.post(f"{IMM}/{imm}/codes", headers=emp_headers,
                    json={"libelle": "Boîte aux lettres", "code": "7"})
    assert r.status_code == 201, r.text
    assert r.json()["created_by_email"] == "smoke-codes-employe@example.com"
    # … mais pas ceux du 9085 Millen, où il n'est pas affecté.
    assert client.get(f"{IMM}/{autre}/codes", headers=emp_headers).status_code == 403
    assert client.post(f"{IMM}/{autre}/codes", headers=emp_headers,
                       json={"libelle": "Porte", "code": "1"}).status_code == 403


def test_cliquet_et_mcp_codes(client, api_key_headers, codes_seed):
    from app.core.api_ia_couverture import TABLES_COUVERTES

    assert "imm_immeuble_codes" in TABLES_COUVERTES
    r = client.get("/api/v1/activity/entities/immeuble_codes", headers=api_key_headers)
    assert r.status_code == 200, r.text
    assert r.json()["pole"] == "immobilier" and r.json()["count"] >= 3
    item = next(x for x in r.json()["items"] if x["libelle"] == "Lock box")
    assert item["entity_type"] == "imm_immeuble_code" and item["code"] == "0710"
    assert item["immeuble_id"] == codes_seed["imm"]
    assert item["note"] == "Boîte grise à gauche de la porte"
    # Alias « codes_acces » et détail d'un code.
    r = client.get("/api/v1/activity/entities/codes_acces", headers=api_key_headers)
    assert r.status_code == 200 and r.json()["count"] >= 3
    r = client.get(f"/api/v1/activity/entities/immeuble_code/{item['id']}", headers=api_key_headers)
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "0710"
