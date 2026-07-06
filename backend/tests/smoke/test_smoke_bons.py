"""Smoke — Bon de travail INTERNE : création, lignes, récap refacturation.

⚠️ La référence auto-générée (BT-AAMMJJ-HHMMSS) n'a qu'une granularité
d'UNE SECONDE et la colonne est UNIQUE : deux bons créés dans la même
seconde → violation de contrainte (HTTP 500) — bug latent en prod. Les
tests passent donc une référence explicite unique, sauf le premier qui
valide le format auto.
"""

import uuid


def _create_bon_interne(client, auth_headers, *, auto_ref: bool = False) -> dict:
    payload = {
        "title": "Entretien smoke — plomberie",
        "kind": "interne",
        "address": "10 rue du Smoke",
        "marge_pct": 15,
    }
    if not auto_ref:
        payload["reference"] = f"BT-SMK-{uuid.uuid4().hex[:12]}"
    resp = client.post(
        "/api/v1/bons-travail", headers=auth_headers, json=payload
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_bon_interne(client, auth_headers):
    bon = _create_bon_interne(client, auth_headers, auto_ref=True)
    assert bon["id"] > 0
    assert bon["kind"] == "interne"
    # Référence auto-générée BT-… quand absente.
    assert bon["reference"].startswith("BT-")


def test_bon_items_and_rollup(client, auth_headers):
    bon = _create_bon_interne(client, auth_headers)

    # Ligne main-d'œuvre : 3 h × 55 $ facturé (× 1.10 marge), coût 35 $/h.
    item1 = client.post(
        f"/api/v1/bons-travail/{bon['id']}/items",
        headers=auth_headers,
        json={
            "description": "Main-d'œuvre plomberie",
            "item_type": "heure",
            "quantity": 3,
            "cost_rate": 35,
            "bill_rate": 55,
            "marge_pct": 10,
        },
    )
    assert item1.status_code == 201, item1.text
    line = item1.json()
    assert line["total"] == 181.5  # 3 × 55 × 1.10
    assert line["cost_total"] == 105.0  # 3 × 35

    # Ligne matériel : 2 × 40 $ coûtant, marge 10 %.
    item2 = client.post(
        f"/api/v1/bons-travail/{bon['id']}/items",
        headers=auth_headers,
        json={
            "description": "Tuyaux",
            "item_type": "materiel",
            "quantity": 2,
            "cost_rate": 40,
            "marge_pct": 10,
        },
    )
    assert item2.status_code == 201, item2.text

    # Roll-up : le montant du bon = somme des lignes facturées.
    got = client.get(
        f"/api/v1/bons-travail/{bon['id']}", headers=auth_headers
    )
    assert got.status_code == 200, got.text
    amount = got.json()["amount"]
    assert isinstance(amount, (int, float))
    assert amount == 181.5 + 88.0  # 88 = 2 × 40 × 1.10

    # Liste des lignes.
    items = client.get(
        f"/api/v1/bons-travail/{bon['id']}/items", headers=auth_headers
    )
    assert items.status_code == 200
    assert len(items.json()) == 2


def test_bon_recap_does_not_500(client, auth_headers):
    bon = _create_bon_interne(client, auth_headers)
    client.post(
        f"/api/v1/bons-travail/{bon['id']}/items",
        headers=auth_headers,
        json={
            "description": "Forfait smoke",
            "item_type": "materiel",
            "quantity": 1,
            "cost_rate": 100,
            "marge_pct": 0,
        },
    )

    recap = client.get(
        f"/api/v1/bons-travail/{bon['id']}/recap", headers=auth_headers
    )
    assert recap.status_code == 200, recap.text
    body = recap.json()
    # Forme minimale du récap + un montant numérique.
    for key in ("bon_type", "hours", "labor_total", "achats_total", "total"):
        assert key in body, f"clé manquante : {key}"
    assert isinstance(body["total"], (int, float))
