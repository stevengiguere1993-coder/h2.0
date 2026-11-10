"""Smoke — Codes de porte d'un logement (Steven 2026-11-10).

« Ajouter un endroit dans les logements […] il faut mettre les codes des
portes quelque part pour avoir accès au besoin » :
- CRUD /immobilier/logements/{id}/codes (même table que les codes de
  l'immeuble, ``logement_id`` renseigné) ;
- la fiche de l'immeuble ne liste que SES codes, sauf
  ``?inclure_logements=true`` ;
- un code de logement ne se touche pas via un autre logement ;
- visibilité : celle de l'immeuble du logement (employé non affecté → 403) ;
- retirer le logement retire ses codes.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, get_password_hash
from app.models.immobilier import Immeuble, ImmeubleCode, Logement
from app.models.user import User
from tests.smoke.conftest import TestSessionLocal

IMM = "/api/v1/immobilier/immeubles"
LOG = "/api/v1/immobilier/logements"


@pytest.fixture(scope="module")
def seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Codes logement", address="12 rue Test",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg1 = Logement(immeuble_id=imm.id, numero="101")
            lg2 = Logement(immeuble_id=imm.id, numero="102")
            emp = User(
                email="smoke-codes-logement-emp@example.com",
                hashed_password=get_password_hash("Sm0keCodes!42"),
                is_active=True, is_admin=False, role="employee",
                volets_json='["immobilier"]',
            )
            s.add_all([lg1, lg2, emp])
            await s.commit()
            return {"imm": imm.id, "lg1": lg1.id, "lg2": lg2.id, "emp": emp.id}

    return run(_seed())


def test_codes_logement(client, auth_headers, seed, run):
    imm, lg1, lg2 = seed["imm"], seed["lg1"], seed["lg2"]
    assert client.get(f"{LOG}/{lg1}/codes", headers=auth_headers).json() == []

    r = client.post(f"{IMM}/{imm}/codes", headers=auth_headers,
                    json={"libelle": "Porte d'entrée", "code": "1111#"})
    assert r.status_code == 201 and r.json()["logement_id"] is None

    r = client.post(f"{LOG}/{lg1}/codes", headers=auth_headers,
                    json={"libelle": "Porte du logement", "code": " 4567 ",
                          "note": " Serrure numérique "})
    assert r.status_code == 201, r.text
    porte = r.json()
    assert porte["logement_id"] == lg1 and porte["immeuble_id"] == imm
    assert porte["code"] == "4567" and porte["note"] == "Serrure numérique"
    r = client.post(f"{LOG}/{lg1}/codes", headers=auth_headers,
                    json={"libelle": "Lock box", "code": "0101"})
    assert r.status_code == 201
    assert r.json()["position"] > porte["position"]

    assert [c["libelle"] for c in client.get(f"{LOG}/{lg1}/codes", headers=auth_headers).json()] == ["Porte du logement", "Lock box"]
    assert client.get(f"{LOG}/{lg2}/codes", headers=auth_headers).json() == []
    # Fiche immeuble : ses codes seulement, sauf inclure_logements.
    assert [c["libelle"] for c in client.get(f"{IMM}/{imm}/codes", headers=auth_headers).json()] == ["Porte d'entrée"]
    tous = client.get(f"{IMM}/{imm}/codes?inclure_logements=true", headers=auth_headers).json()
    assert len(tous) == 3

    r = client.patch(f"{LOG}/{lg1}/codes/{porte['id']}", headers=auth_headers,
                     json={"code": "7654"})
    assert r.status_code == 200 and r.json()["code"] == "7654"
    # Pas via un autre logement.
    assert client.patch(f"{LOG}/{lg2}/codes/{porte['id']}", headers=auth_headers,
                        json={"code": "x"}).status_code == 404
    assert client.delete(f"{LOG}/{lg2}/codes/{porte['id']}", headers=auth_headers).status_code == 404
    assert client.post(f"{LOG}/999999/codes", headers=auth_headers,
                       json={"libelle": "x", "code": "1"}).status_code == 404

    # Employé non affecté à l'immeuble → 403.
    emp = {"Authorization": f"Bearer {create_access_token(subject=str(seed['emp']))}"}
    assert client.get(f"{LOG}/{lg1}/codes", headers=emp).status_code == 403

    assert client.delete(f"{LOG}/{lg1}/codes/{porte['id']}", headers=auth_headers).status_code == 204
    assert [c["libelle"] for c in client.get(f"{LOG}/{lg1}/codes", headers=auth_headers).json()] == ["Lock box"]

    # Retirer le logement retire ses codes (pas ceux de l'immeuble).
    assert client.delete(f"{LOG}/{lg1}", headers=auth_headers).status_code == 204

    async def _restants():
        async with TestSessionLocal() as s:
            rows = (await s.execute(
                select(ImmeubleCode).where(ImmeubleCode.immeuble_id == imm)
            )).scalars().all()
            return [(c.libelle, c.logement_id) for c in rows]

    assert run(_restants()) == [("Porte d'entrée", None)]
