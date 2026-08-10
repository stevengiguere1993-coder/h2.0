"""Smoke — hub d'infos de la INC sur la fiche entreprise (2026-08-10).

1. PATCH /entreprises/{id} accepte les infos légales (TPS/TVQ, siège
   social, date de constitution, notes) et la liste les re-sert.
2. Les partenaires portent adresse / date de naissance / téléphone.
"""
from __future__ import annotations


def test_infos_legales_entreprise(client, auth_headers):
    r = client.post(
        "/api/v1/entreprises",
        headers=auth_headers,
        json={"name": "INC Smoke Hub"},
    )
    assert r.status_code in (200, 201), r.text
    ent_id = r.json()["id"]

    p = client.patch(
        f"/api/v1/entreprises/{ent_id}",
        headers=auth_headers,
        json={
            "neq": "1234567890",
            "tps_number": "123456789 RT0001",
            "tvq_number": "1234567890 TQ0001",
            "siege_social": "100 rue Principale, Montréal",
            "date_constitution": "2020-01-15",
            "notes_legales": "Fin d'année financière : 31 décembre.",
        },
    )
    assert p.status_code == 200, p.text

    ents = client.get(
        "/api/v1/entreprises", headers=auth_headers
    ).json()
    ent = next(e for e in ents if e["id"] == ent_id)
    assert ent["neq"] == "1234567890"
    assert ent["tps_number"] == "123456789 RT0001"
    assert ent["tvq_number"] == "1234567890 TQ0001"
    assert ent["siege_social"] == "100 rue Principale, Montréal"
    assert ent["date_constitution"] == "2020-01-15"
    assert "31 décembre" in ent["notes_legales"]


def test_partenaire_coordonnees(client, auth_headers):
    ent_id = client.post(
        "/api/v1/entreprises",
        headers=auth_headers,
        json={"name": "INC Smoke Partenaires"},
    ).json()["id"]

    r = client.post(
        "/api/v1/entreprises/partners",
        headers=auth_headers,
        json={
            "entreprise_id": ent_id,
            "partner_name": "Alex Actionnaire",
            "partner_email": "alex@example.com",
            "partner_adresse": "22 av. des Érables, Laval",
            "partner_naissance": "1990-06-01",
            "partner_telephone": "514 555-0199",
            "ownership_pct": 50,
        },
    )
    assert r.status_code == 201, r.text

    partners = client.get(
        f"/api/v1/entreprises/{ent_id}/partners", headers=auth_headers
    ).json()
    assert len(partners) == 1
    pa = partners[0]
    assert pa["partner_adresse"] == "22 av. des Érables, Laval"
    assert pa["partner_naissance"] == "1990-06-01"
    assert pa["partner_telephone"] == "514 555-0199"
