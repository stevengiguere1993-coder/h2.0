"""Smoke — Bon de travail INTERNE : création, lignes, récap refacturation.

La référence auto-générée (BT-AAMMJJ-HHMMSS) n'a qu'une granularité d'UNE
SECONDE et la colonne est UNIQUE. Ce risque de collision (deux bons dans la
même seconde → HTTP 500) est désormais couvert par le helper anti-collision
`generate_bt_reference` (suffixe `-N`) ; `test_two_auto_ref_bons_same_second_no_500`
en fait la régression. Les autres tests passent une référence explicite unique
pour rester indépendants, sauf ceux qui valident le format auto.
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


def test_two_auto_ref_bons_same_second_no_500(client, auth_headers):
    """Deux bons créés « coup sur coup » (référence auto, même seconde
    probable) ne doivent PAS lever de 500 et doivent porter deux références
    distinctes. Régression du bug historique décrit en tête de fichier :
    la colonne `reference` est UNIQUE et l'horodatage n'a qu'une granularité
    d'une seconde — le helper anti-collision suffixe la 2e (`…-2`)."""
    bon1 = _create_bon_interne(client, auth_headers, auto_ref=True)
    bon2 = _create_bon_interne(client, auth_headers, auto_ref=True)

    # Aucun 500 : les deux POST ont renvoyé 201 (assert dans _create_bon_interne).
    assert bon1["id"] != bon2["id"]
    # Références distinctes malgré la même seconde.
    assert bon1["reference"] != bon2["reference"]
    assert bon1["reference"].startswith("BT-")
    assert bon2["reference"].startswith("BT-")
    # Elles tiennent dans String(32).
    assert len(bon1["reference"]) <= 32
    assert len(bon2["reference"]) <= 32


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
