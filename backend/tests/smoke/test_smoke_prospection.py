"""Smoke — Prospection : deals du Pipeline, tâches de deal, lead analysis.

La création d'une LeadAnalysis passe normalement par /lead-analyses/extract
(Gemini — réseau) : ici on seed la fiche DIRECTEMENT en DB (avec la colonne
JSONB ``validation_warnings``) puis on vérifie la lecture/écriture via l'API.
"""

import pytest


def test_create_deal_and_get(client, auth_headers):
    created = client.post(
        "/api/v1/prospection/deals",
        headers=auth_headers,
        json={"address": "123 rue Smoke, Montréal", "priority": "moyenne"},
    )
    assert created.status_code == 201, created.text
    deal = created.json()
    assert deal["id"] > 0
    assert deal["address"] == "123 rue Smoke, Montréal"
    assert deal["priority"] == "moyenne"

    got = client.get(
        f"/api/v1/prospection/deals/{deal['id']}", headers=auth_headers
    )
    assert got.status_code == 200, got.text
    assert got.json()["id"] == deal["id"]

    listed = client.get("/api/v1/prospection/deals", headers=auth_headers)
    assert listed.status_code == 200
    assert any(d["id"] == deal["id"] for d in listed.json())


def test_deal_task_post_patch(client, auth_headers):
    deal = client.post(
        "/api/v1/prospection/deals",
        headers=auth_headers,
        json={"address": "456 av. des Tests"},
    ).json()

    # ICE fournis → pas d'autoscore IA en arrière-plan.
    created = client.post(
        f"/api/v1/prospection/deals/{deal['id']}/tasks",
        headers=auth_headers,
        json={
            "name": "Appeler le courtier",
            "impact": 6,
            "confidence": 7,
            "effort": 2,
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["deal_id"] == deal["id"]
    assert task["name"] == "Appeler le courtier"
    assert task["status"] == "a_faire"
    assert task["score"] is not None

    patched = client.patch(
        f"/api/v1/prospection/deals/{deal['id']}/tasks/{task['id']}",
        headers=auth_headers,
        json={"name": "Appeler le courtier (fait)", "status": "done"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["name"] == "Appeler le courtier (fait)"
    assert body["status"] == "done"

    listed = client.get(
        f"/api/v1/prospection/deals/{deal['id']}/tasks", headers=auth_headers
    )
    assert listed.status_code == 200
    assert any(t["id"] == task["id"] for t in listed.json())


@pytest.fixture(scope="module")
def seeded_analysis_id(run, seeded_users) -> int:
    """Seed une LeadAnalysis directement en DB — la table porte la colonne
    JSONB ``validation_warnings`` (compilée en JSON sous SQLite)."""
    from tests.smoke.conftest import TestSessionLocal

    async def _seed() -> int:
        from app.models.lead_analysis import LeadAnalysis

        async with TestSessionLocal() as session:
            rec = LeadAnalysis(
                status="a_analyser",
                address="789 boul. Smoke",
                city="Montréal",
                asking_price=650000,
                nb_logements=6,
                validation_warnings=[
                    {
                        "field": "asking_price",
                        "severity": "info",
                        "message": "seed smoke test",
                    }
                ],
                created_by_user_id=seeded_users["admin_id"],
            )
            session.add(rec)
            await session.flush()
            rec_id = rec.id
            await session.commit()
            return rec_id

    return run(_seed())


def test_lead_analysis_read(client, auth_headers, seeded_analysis_id):
    got = client.get(
        f"/api/v1/lead-analyses/{seeded_analysis_id}", headers=auth_headers
    )
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["id"] == seeded_analysis_id
    assert body["address"] == "789 boul. Smoke"
    assert body["nb_logements"] == 6
    # La colonne JSONB revient bien structurée.
    warnings = body.get("validation_warnings")
    assert isinstance(warnings, list) and warnings
    assert warnings[0]["field"] == "asking_price"

    listed = client.get("/api/v1/lead-analyses", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert any(a["id"] == seeded_analysis_id for a in listed.json())


def test_lead_analysis_patch(client, auth_headers, seeded_analysis_id):
    patched = client.patch(
        f"/api/v1/lead-analyses/{seeded_analysis_id}",
        headers=auth_headers,
        json={"notes": "Note smoke", "city": "Laval"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["notes"] == "Note smoke"
    assert body["city"] == "Laval"
