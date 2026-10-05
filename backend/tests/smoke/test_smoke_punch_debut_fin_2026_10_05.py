"""Smoke — punch manuel : le début doit précéder la fin (Steven, 2026-10-05).

Dans Gestion des punchs, un punch dont l'heure de début tombait après
l'heure de fin était créé sans erreur (heures vides, rangé à la date du
début). L'API le refuse maintenant, à la création comme à la modification
des heures ; approuver un ancien punch à l'envers reste possible.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.employe import Employe
from app.models.punch import Punch

from tests.smoke.conftest import TestSessionLocal

MESSAGE = "L'heure de début doit être avant l'heure de fin."


@pytest.fixture(scope="module")
def employe_id(run, db_setup) -> int:
    async def _seed():
        async with TestSessionLocal() as s:
            e = Employe(full_name="Punch Début Fin")
            s.add(e)
            await s.commit()
            return e.id

    return run(_seed())


def _creer(client, headers, employe_id, debut, fin):
    return client.post(
        "/api/v1/punch",
        json={"employe_id": employe_id, "started_at": debut, "ended_at": fin},
        headers=headers,
    )


def test_creation_debut_apres_fin_refusee(client, auth_headers, employe_id):
    r = _creer(
        client, auth_headers, employe_id, "2026-10-05T12:44:00Z", "2026-10-02T20:00:00Z"
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == MESSAGE


def test_creation_debut_egal_fin_refusee(client, auth_headers, employe_id):
    r = _creer(
        client, auth_headers, employe_id, "2026-10-02T12:00:00Z", "2026-10-02T12:00:00Z"
    )
    assert r.status_code == 422, r.text


def test_creation_valide_et_punch_ouvert(client, auth_headers, employe_id):
    r = _creer(
        client, auth_headers, employe_id, "2026-10-02T12:00:00Z", "2026-10-02T20:00:00Z"
    )
    assert r.status_code == 201, r.text
    assert float(r.json()["hours"]) == 8.0
    # Sans fin (punch en cours), rien à comparer.
    r = _creer(client, auth_headers, employe_id, "2026-10-03T12:00:00Z", None)
    assert r.status_code == 201, r.text


def test_modification_des_heures_a_l_envers_refusee(client, auth_headers, employe_id):
    r = _creer(
        client, auth_headers, employe_id, "2026-10-01T12:00:00Z", "2026-10-01T20:00:00Z"
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.patch(
        f"/api/v1/punch/{pid}",
        json={"ended_at": "2026-10-01T11:00:00Z"},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == MESSAGE
    r = client.patch(
        f"/api/v1/punch/{pid}",
        json={"started_at": "2026-10-01T13:00:00Z", "ended_at": "2026-10-01T21:00:00Z"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text


def test_approuver_un_ancien_punch_a_l_envers_reste_possible(
    run, client, auth_headers, employe_id
):
    async def _seed():
        async with TestSessionLocal() as s:
            p = Punch(
                employe_id=employe_id,
                started_at=datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc),
                ended_at=datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc),
            )
            s.add(p)
            await s.commit()
            return p.id

    pid = run(_seed())
    r = client.patch(
        f"/api/v1/punch/{pid}", json={"approved": True}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["approved"] is True
