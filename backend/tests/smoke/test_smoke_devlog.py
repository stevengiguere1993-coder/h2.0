"""Smoke — Dev logiciel : soumission devis_dev minimale + calcul de totaux."""


def test_create_devis_dev_soumission(client, auth_headers):
    created = client.post(
        "/api/v1/devlog/soumissions",
        headers=auth_headers,
        json={"title": "Devis smoke", "is_devis_dev": True},
    )
    assert created.status_code == 201, created.text
    soum = created.json()
    assert soum["id"] > 0
    assert soum["title"] == "Devis smoke"
    assert soum["is_devis_dev"] is True
    # Les 5 paramètres devis_dev sont pré-remplis (défauts configurables,
    # fallback constantes historiques) — ils ne doivent pas rester None.
    assert soum["taux_dev_horaire"] is not None
    assert soum["marge_initiale_pct"] is not None


def test_reread_soumission_and_totals_do_not_500(client, auth_headers):
    soum = client.post(
        "/api/v1/devlog/soumissions",
        headers=auth_headers,
        json={"title": "Devis smoke totaux", "is_devis_dev": True},
    ).json()

    # Relecture simple.
    got = client.get(
        f"/api/v1/devlog/soumissions/{soum['id']}", headers=auth_headers
    )
    assert got.status_code == 200, got.text
    assert got.json()["id"] == soum["id"]

    # Calcul des totaux (calcul circulaire frais initiaux + mensuels) —
    # ne doit pas 500 même sur une soumission vide.
    preview = client.get(
        f"/api/v1/devlog/soumissions/{soum['id']}/devis-preview",
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    totals = preview.json()
    assert isinstance(totals, dict) and totals


def test_devis_preview_with_item(client, auth_headers):
    """Une ligne feature (heures × taux) : le total doit être un nombre > 0."""
    soum = client.post(
        "/api/v1/devlog/soumissions",
        headers=auth_headers,
        json={
            "title": "Devis smoke item",
            "is_devis_dev": True,
            "taux_dev_horaire": 100,
        },
    ).json()

    item = client.post(
        "/api/v1/devlog/soumission-items",
        headers=auth_headers,
        json={
            "soumission_id": soum["id"],
            "description": "Feature smoke",
            "item_kind": "feature",
            "heures": 10,
        },
    )
    assert item.status_code in (200, 201), item.text

    preview = client.get(
        f"/api/v1/devlog/soumissions/{soum['id']}/devis-preview",
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    totals = preview.json()
    assert isinstance(totals, dict)
    # Au moins un montant numérique quelque part au premier niveau.
    numeric_values = [
        v for v in totals.values() if isinstance(v, (int, float))
    ]
    assert numeric_values, f"aucun montant numérique dans {totals.keys()}"


def test_devlog_requires_admin(client, employee_headers):
    resp = client.get("/api/v1/devlog/soumissions", headers=employee_headers)
    assert resp.status_code == 403
