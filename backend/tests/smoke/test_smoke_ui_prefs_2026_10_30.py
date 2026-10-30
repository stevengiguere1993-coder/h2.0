"""Smoke — états d'interface mémorisés par utilisateur (colonnes de
kanban repliées, Steven 2026-10-30 : l'état ouvert / fermé suit
l'utilisateur après déconnexion et sur un autre appareil)."""

URL = "/api/v1/auth/me/ui-prefs"


def test_ui_pref_absente_puis_enregistree(client, auth_headers):
    resp = client.get(f"{URL}/kanban.crm", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"key": "kanban.crm", "found": False, "value": None}

    resp = client.put(
        f"{URL}/kanban.crm",
        json={"value": ["won", "lost"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    # Une deuxième clé ne doit pas écraser la première.
    resp = client.put(
        f"{URL}/kanban.soumissions", json={"value": []}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    body = client.get(f"{URL}/kanban.crm", headers=auth_headers).json()
    assert body == {"key": "kanban.crm", "found": True, "value": ["won", "lost"]}
    # Liste vide enregistrée = toutes les colonnes ouvertes, distinct de
    # « jamais enregistré ».
    body = client.get(f"{URL}/kanban.soumissions", headers=auth_headers).json()
    assert body == {"key": "kanban.soumissions", "found": True, "value": []}


def test_ui_pref_par_utilisateur(client, auth_headers, employee_headers):
    client.put(
        f"{URL}/kanban.facturation",
        json={"value": ["paid"]},
        headers=auth_headers,
    )
    body = client.get(f"{URL}/kanban.facturation", headers=employee_headers).json()
    assert body["found"] is False


def test_ui_pref_cle_invalide_et_sans_jeton(client, auth_headers):
    resp = client.get(f"{URL}/Mauvaise%20Cle", headers=auth_headers)
    assert resp.status_code == 422
    assert client.get(f"{URL}/kanban.crm").status_code == 401
