"""Smoke — volet Gestion d'entreprises : entreprise + tâches (CRUD)."""


def test_create_entreprise(client, auth_headers):
    resp = client.post(
        "/api/v1/entreprises",
        headers=auth_headers,
        json={"name": "Smoke Inc."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] > 0
    assert body["name"] == "Smoke Inc."
    assert body["is_active"] is True


def test_list_entreprises(client, auth_headers):
    client.post(
        "/api/v1/entreprises",
        headers=auth_headers,
        json={"name": "Smoke Liste Inc."},
    )
    resp = client.get("/api/v1/entreprises", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert any(e["name"] == "Smoke Liste Inc." for e in body)


def test_entreprises_require_auth(client):
    resp = client.get("/api/v1/entreprises")
    assert resp.status_code == 401


def test_create_patch_list_tache(client, auth_headers):
    ent = client.post(
        "/api/v1/entreprises",
        headers=auth_headers,
        json={"name": "Smoke Tâches Inc."},
    ).json()

    # Création — on fournit les 3 champs ICE pour éviter le scoring IA
    # en arrière-plan (fire-and-forget) : déterminisme > exhaustivité.
    created = client.post(
        "/api/v1/entreprises/taches",
        headers=auth_headers,
        json={
            "entreprise_id": ent["id"],
            "title": "Tâche smoke",
            "impact": 5,
            "confidence": 5,
            "effort": 5,
        },
    )
    assert created.status_code == 201, created.text
    tache = created.json()
    assert tache["entreprise_id"] == ent["id"]
    assert tache["title"] == "Tâche smoke"
    assert tache["score"] is not None

    # PATCH : titre + statut.
    patched = client.patch(
        f"/api/v1/entreprises/taches/{tache['id']}",
        headers=auth_headers,
        json={"title": "Tâche smoke (renommée)", "status": "done"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["title"] == "Tâche smoke (renommée)"
    assert body["status"] == "done"
    # Passage à done → completed_at auto-rempli.
    assert body["completed_at"] is not None

    # Liste filtrée par entreprise.
    listed = client.get(
        f"/api/v1/entreprises/taches?entreprise_id={ent['id']}",
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()
    assert isinstance(items, list)
    assert any(t["id"] == tache["id"] for t in items)
