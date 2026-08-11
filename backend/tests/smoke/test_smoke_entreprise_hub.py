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
            "arc_business_number": "123456789",
            "rq_identification_number": "1023456789",
            "cnesst_number": "CN-445566",
            "regime_constitution": "Québec (LSAQ)",
            "fin_annee_financiere": "31 décembre",
            "clicsequr_details": "Code utilisateur : mgv-admin",
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
    assert ent["arc_business_number"] == "123456789"
    assert ent["rq_identification_number"] == "1023456789"
    assert ent["cnesst_number"] == "CN-445566"
    assert ent["regime_constitution"] == "Québec (LSAQ)"
    assert ent["fin_annee_financiere"] == "31 décembre"
    assert "mgv-admin" in ent["clicsequr_details"]
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
    assert pa["is_personne_morale"] is False


def test_partenaire_morale_et_annuaire(client, auth_headers):
    ent_id = client.post(
        "/api/v1/entreprises",
        headers=auth_headers,
        json={"name": "INC Smoke Morale"},
    ).json()["id"]

    r = client.post(
        "/api/v1/entreprises/partners",
        headers=auth_headers,
        json={
            "entreprise_id": ent_id,
            "partner_name": "9999-8888 Québec inc.",
            "is_personne_morale": True,
            "partner_neq": "9998887776",
            "ownership_pct": 25,
        },
    )
    assert r.status_code == 201, r.text
    pa = r.json()
    assert pa["is_personne_morale"] is True
    assert pa["partner_neq"] == "9998887776"

    # L'annuaire (toutes entreprises) re-sert les partenaires saisis —
    # base du préremplissage du modal.
    annuaire = client.get(
        "/api/v1/entreprises/partners-annuaire", headers=auth_headers
    ).json()
    entry = next(
        a for a in annuaire if a["partner_name"] == "9999-8888 Québec inc."
    )
    assert entry["is_personne_morale"] is True
    assert entry["partner_neq"] == "9998887776"
    # Le partenaire du test précédent y est aussi (dédup inter-entreprises).
    assert any(a["partner_name"] == "Alex Actionnaire" for a in annuaire)


def test_modification_partenaire_propagee(client, auth_headers):
    """Retour Phil 2026-08-10 : modifier un partenaire le change PARTOUT
    où il est utilisé — coordonnées propagées, parts/rôle locaux."""
    def _ent(nom: str) -> int:
        return client.post(
            "/api/v1/entreprises", headers=auth_headers, json={"name": nom}
        ).json()["id"]

    ent_a, ent_b = _ent("INC Propagation A"), _ent("INC Propagation B")
    ids = {}
    for ent_id, pct in ((ent_a, 50), (ent_b, 25)):
        ids[ent_id] = client.post(
            "/api/v1/entreprises/partners",
            headers=auth_headers,
            json={
                "entreprise_id": ent_id,
                "partner_name": "Paula Propagation",
                "partner_adresse": "1 rue Départ",
                "ownership_pct": pct,
            },
        ).json()["id"]

    # PATCH sur l'entreprise A : adresse + téléphone (+ % local à A).
    r = client.patch(
        f"/api/v1/entreprises/partners/{ids[ent_a]}",
        headers=auth_headers,
        json={
            "partner_adresse": "99 rue Arrivée",
            "partner_telephone": "438 555-0100",
            "ownership_pct": 60,
        },
    )
    assert r.status_code == 200, r.text

    autres = client.get(
        f"/api/v1/entreprises/{ent_b}/partners", headers=auth_headers
    ).json()
    pb = next(p for p in autres if p["id"] == ids[ent_b])
    # Coordonnées propagées…
    assert pb["partner_adresse"] == "99 rue Arrivée"
    assert pb["partner_telephone"] == "438 555-0100"
    # …mais les parts de l'entreprise B n'ont PAS bougé.
    assert float(pb["ownership_pct"]) == 25.0


def test_inc_liee_comme_actionnaire(client, auth_headers):
    """Interconnexion : une de NOS INCs devient actionnaire d'une autre —
    sa fiche (nom, NEQ, siège) est la source de vérité du partenaire."""
    def _ent(nom: str, **extra) -> int:
        return client.post(
            "/api/v1/entreprises",
            headers=auth_headers,
            json={"name": nom, **extra},
        ).json()["id"]

    holding = _ent(
        "Holding Interco inc.",
        neq="1112223334",
        siege_social="500 boul. Groupe, Montréal",
    )
    filiale = _ent("Filiale Interco inc.")

    # L'annuaire propose nos INCs (entrées synthétiques, id négatif).
    annuaire = client.get(
        "/api/v1/entreprises/partners-annuaire", headers=auth_headers
    ).json()
    inc = next(
        a for a in annuaire if a.get("partner_entreprise_id") == holding
    )
    assert inc["is_personne_morale"] is True
    assert inc["partner_neq"] == "1112223334"

    # La holding devient actionnaire de la filiale, LIÉE à sa fiche.
    r = client.post(
        "/api/v1/entreprises/partners",
        headers=auth_headers,
        json={
            "entreprise_id": filiale,
            "partner_entreprise_id": holding,
            "ownership_pct": 100,
        },
    )
    assert r.status_code == 201, r.text
    pa = r.json()
    assert pa["display_name"] == "Holding Interco inc."
    assert pa["partner_neq"] == "1112223334"
    assert pa["partner_adresse"] == "500 boul. Groupe, Montréal"
    assert pa["is_personne_morale"] is True

    # La fiche de la holding change → le partenaire reflète le changement
    # SANS resaisie (source de vérité).
    client.patch(
        f"/api/v1/entreprises/{holding}",
        headers=auth_headers,
        json={"neq": "9990001112"},
    )
    partners = client.get(
        f"/api/v1/entreprises/{filiale}/partners", headers=auth_headers
    ).json()
    assert partners[0]["partner_neq"] == "9990001112"

    # Sens INVERSE : le courriel saisi sur la ligne « actionnaire »
    # remonte sur la FICHE de la holding (qui n'en avait pas).
    client.patch(
        f"/api/v1/entreprises/partners/{pa['id']}",
        headers=auth_headers,
        json={"partner_email": "info@holding-interco.com"},
    )
    ents2 = client.get(
        "/api/v1/entreprises", headers=auth_headers
    ).json()
    hold = next(e for e in ents2 if e["id"] == holding)
    assert hold["contact_email"] == "info@holding-interco.com"

    # La fiche de la holding liste ses PARTICIPATIONS (sens inverse).
    parts = client.get(
        f"/api/v1/entreprises/{holding}/participations",
        headers=auth_headers,
    ).json()
    assert any(
        x["entreprise_id"] == filiale and x["ownership_pct"] == 100
        for x in parts
    )

    # Garde-fou : une compagnie ne peut pas être actionnaire d'elle-même.
    r2 = client.post(
        "/api/v1/entreprises/partners",
        headers=auth_headers,
        json={"entreprise_id": holding, "partner_entreprise_id": holding},
    )
    assert r2.status_code == 422


def test_sync_detention_organigramme(client, auth_headers):
    """L'organigramme se reconstruit depuis les partenaires : nœud par
    INC + par investisseur externe, parent = plus gros détenteur, % dans
    la description. Idempotent."""
    def _ent(nom: str) -> int:
        return client.post(
            "/api/v1/entreprises", headers=auth_headers, json={"name": nom}
        ).json()["id"]

    holding = _ent("Sync Holding inc.")
    filiale = _ent("Sync Filiale inc.")
    client.post(
        "/api/v1/entreprises/partners",
        headers=auth_headers,
        json={
            "entreprise_id": filiale,
            "partner_entreprise_id": holding,
            "ownership_pct": 100,
        },
    )
    client.post(
        "/api/v1/entreprises/partners",
        headers=auth_headers,
        json={
            "entreprise_id": holding,
            "partner_name": "Sam Sync",
            "ownership_pct": 50,
        },
    )

    r = client.post(
        "/api/v1/org-nodes/sync-detention", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    nodes = r.json()
    n_hold = next(n for n in nodes if n["entreprise_id"] == holding)
    n_fil = next(n for n in nodes if n["entreprise_id"] == filiale)
    n_sam = next(
        n
        for n in nodes
        if n["kind"] == "person" and n["label"] == "Sam Sync"
    )
    # La filiale est détenue par la holding ; la holding par Sam.
    assert n_fil["parent_id"] == n_hold["id"]
    assert "Détention : Sync Holding inc. 100 %" in (
        n_fil["description"] or ""
    )
    assert n_hold["parent_id"] == n_sam["id"]

    # Idempotent : un second sync ne duplique ni nœud ni personne.
    nodes2 = client.post(
        "/api/v1/org-nodes/sync-detention", headers=auth_headers
    ).json()
    assert (
        len(
            [
                n
                for n in nodes2
                if n["kind"] == "person" and n["label"] == "Sam Sync"
            ]
        )
        == 1
    )
    assert len([n for n in nodes2 if n["entreprise_id"] == filiale]) == 1

    # Quotes-parts stockées sur le nœud détenu (affichées sur les
    # flèches du canvas).
    n_fil2 = next(n for n in nodes2 if n["entreprise_id"] == filiale)
    import json as _json

    own = _json.loads(n_fil2["ownership_json"] or "{}")
    n_hold2 = next(n for n in nodes2 if n["entreprise_id"] == holding)
    assert own.get(str(n_hold2["id"])) == 100.0


def test_versions_organigramme(client, auth_headers):
    """Plusieurs versions d'organigramme : création par copie du
    Principal, listing filtré, suppression."""
    r = client.post(
        "/api/v1/org-nodes/versions",
        headers=auth_headers,
        json={"name": "Scénario 2027"},
    )
    assert r.status_code == 201, r.text
    vid = r.json()["id"]

    versions = client.get(
        "/api/v1/org-nodes/versions", headers=auth_headers
    ).json()
    assert any(v["id"] == vid for v in versions)

    nodes_p = client.get("/api/v1/org-nodes", headers=auth_headers).json()
    nodes_v = client.get(
        f"/api/v1/org-nodes?version_id={vid}", headers=auth_headers
    ).json()
    # La copie reprend tous les nœuds du Principal, isolés dans la
    # version.
    assert len(nodes_v) == len(nodes_p)
    assert all(n["version_id"] == vid for n in nodes_v)
    assert all(n["version_id"] is None for n in nodes_p)

    d = client.delete(
        f"/api/v1/org-nodes/versions/{vid}", headers=auth_headers
    )
    assert d.status_code == 204
    assert (
        client.get(
            f"/api/v1/org-nodes?version_id={vid}", headers=auth_headers
        ).json()
        == []
    )
