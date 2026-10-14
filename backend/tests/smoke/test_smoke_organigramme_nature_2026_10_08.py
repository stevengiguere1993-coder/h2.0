"""Smoke — organigramme v4 (Phil 2026-10-08) : tout vient des fiches.

1. Nature des détenteurs : case « personne morale » → compagnie hors
   groupe (bulle company sans fiche), indices dans le nom → compagnie,
   sinon personne.
2. Les nouveautés sont PLACÉES (rangée du bas) et une bulle déplacée
   ne bouge plus au sync suivant.
3. Nature forcée (POST /org-nodes/{id}/nature) : répercutée sur la
   ligne Partenaires & parts et respectée par la sync.
4. Ligne partenaire retirée → la sync ne supprime rien : la bulle est
   marquée « absente des fiches » (rapport + lecture) ; la retirer à la
   main détache la INC qu'elle détenait au lieu de l'emporter.
"""
from __future__ import annotations


def _ent(client, h, nom: str) -> int:
    r = client.post("/api/v1/entreprises", headers=h, json={"name": nom})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _partner(client, h, **payload) -> int:
    r = client.post("/api/v1/entreprises/partners", headers=h, json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sync(client, h) -> dict:
    r = client.post("/api/v1/org-nodes/sync-detention", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"nodes", "rapport"}
    return body


def _node(nodes, label):
    return next(n for n in nodes if n["label"] == label)


def test_nature_des_detenteurs_et_placement(client, auth_headers):
    h = auth_headers
    inc = _ent(client, h, "Org Nature INC")
    _partner(
        client, h, entreprise_id=inc,
        partner_name="Forget-Léon Immobilier inc.",
        is_personne_morale=True, ownership_pct=30,
    )
    _partner(
        client, h, entreprise_id=inc,
        partner_name="Michael Test", ownership_pct=40,
    )
    # Case non cochée mais numéro de compagnie dans le nom → compagnie.
    _partner(
        client, h, entreprise_id=inc,
        partner_name="9182-4326 Québec inc.", ownership_pct=30,
    )

    body = _sync(client, h)
    nodes, rapport = body["nodes"], body["rapport"]
    forget = _node(nodes, "Forget-Léon Immobilier inc.")
    michael = _node(nodes, "Michael Test")
    numero = _node(nodes, "9182-4326 Québec inc.")
    assert forget["kind"] == "company" and forget["entreprise_id"] is None
    assert numero["kind"] == "company" and numero["entreprise_id"] is None
    assert michael["kind"] == "person"
    # (Les bulles naissent déjà au fil de la saisie — hook de la fiche —
    # donc le rapport de cette sync explicite n'a rien à « créer ».)
    assert set(rapport) == {"crees", "reclasses", "absents", "sans_lignes"}

    # Les nouveautés sont placées (plus de bulle sans position).
    n_inc = _node(nodes, "Org Nature INC")
    for n in (n_inc, forget, michael, numero):
        assert n["pos_x"] is not None and n["pos_y"] is not None
    # Détention : Michael (40 %) = détenteur principal ; les deux
    # compagnies en co-détention, quotes-parts sur le nœud détenu.
    assert n_inc["parent_id"] == michael["id"]
    assert sorted(n_inc["co_owner_node_ids"]) == sorted(
        [forget["id"], numero["id"]]
    )

    # Une bulle déplacée par l'utilisateur ne bouge pas au sync suivant
    # et rien n'est recréé.
    r = client.patch(
        f"/api/v1/org-nodes/{michael['id']}", headers=h,
        json={"pos_x": 1200, "pos_y": 48},
    )
    assert r.status_code == 200, r.text
    body2 = _sync(client, h)
    michael2 = _node(body2["nodes"], "Michael Test")
    assert michael2["id"] == michael["id"]
    assert (michael2["pos_x"], michael2["pos_y"]) == (1200, 48)
    assert "Michael Test" not in body2["rapport"]["crees"]
    assert len([n for n in body2["nodes"] if n["label"] == "Michael Test"]) == 1


def test_nature_forcee_et_nettoyage(client, auth_headers):
    h = auth_headers
    inc = _ent(client, h, "Org Nettoyage INC")
    pid = _partner(
        client, h, entreprise_id=inc,
        partner_name="Placements Ephemere inc.", ownership_pct=10,
    )
    nodes = _sync(client, h)["nodes"]
    bulle = _node(nodes, "Placements Ephemere inc.")
    assert bulle["kind"] == "company"  # indice « Placements … inc. »

    # Correction manuelle → personne, répercutée sur la ligne partenaire.
    r = client.post(
        f"/api/v1/org-nodes/{bulle['id']}/nature", headers=h,
        json={"nature": "person"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "person"
    assert r.json()["nature_forced"] == "person"
    partners = client.get(
        f"/api/v1/entreprises/{inc}/partners", headers=h
    ).json()
    ligne = next(p for p in partners if p["id"] == pid)
    assert ligne["is_personne_morale"] is False
    # La sync respecte le choix forcé.
    nodes = _sync(client, h)["nodes"]
    assert _node(nodes, "Placements Ephemere inc.")["kind"] == "person"

    # Une INC du groupe ne change pas de nature.
    n_inc = _node(nodes, "Org Nettoyage INC")
    r = client.post(
        f"/api/v1/org-nodes/{n_inc['id']}/nature", headers=h,
        json={"nature": "person"},
    )
    assert r.status_code == 409

    # Ligne retirée de la fiche → la sync ne supprime RIEN : la bulle
    # reste, marquée « absente des fiches » et listée dans le rapport ;
    # la INC n'a plus de flèche (hook de la fiche).
    r = client.delete(f"/api/v1/entreprises/partners/{pid}", headers=h)
    assert r.status_code in (200, 204), r.text
    body = _sync(client, h)
    bulle2 = _node(body["nodes"], "Placements Ephemere inc.")
    assert bulle2["absent_des_fiches"] is True
    assert "Placements Ephemere inc." in body["rapport"]["absents"]
    assert "Org Nettoyage INC" in body["rapport"]["sans_lignes"]
    n_inc2 = _node(body["nodes"], "Org Nettoyage INC")
    assert n_inc2["parent_id"] is None
    assert n_inc2["co_owner_node_ids"] == []
    # La lecture ordinaire porte le même drapeau.
    lus = client.get("/api/v1/org-nodes", headers=h).json()
    assert _node(lus, "Placements Ephemere inc.")["absent_des_fiches"] is True
    assert _node(lus, "Org Nettoyage INC")["absent_des_fiches"] is False

    # Retirer la bulle à la main : la INC qu'elle détenait reste.
    # (On la rattache d'abord pour prouver que rien n'est emporté.)
    r = client.patch(
        f"/api/v1/org-nodes/{n_inc2['id']}", headers=h,
        json={"parent_id": bulle2["id"]},
    )
    assert r.status_code == 200, r.text
    r = client.delete(f"/api/v1/org-nodes/{bulle2['id']}", headers=h)
    assert r.status_code == 204, r.text
    lus = client.get("/api/v1/org-nodes", headers=h).json()
    assert all(n["label"] != "Placements Ephemere inc." for n in lus)
    n_inc3 = _node(lus, "Org Nettoyage INC")
    assert n_inc3["parent_id"] is None
