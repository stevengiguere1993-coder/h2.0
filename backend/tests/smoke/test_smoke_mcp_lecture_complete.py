"""Smoke — « les connecteurs Kratos de Claude voient la totalité de
Kratos » (Steven 2026-11-02) : l'outil MCP ``kratos_lire`` lit toute route
GET de l'API au nom du propriétaire de la clé, sans pouvoir écrire, et
reste fermé aux secrets / à l'authentification / aux clés."""

import json

from tests.smoke.test_smoke_mcp import _rpc


def _lire(client, chemin, params=None, key=None, rid=900):
    args = {"chemin": chemin}
    if params is not None:
        args["params"] = params
    kw = {"key": key} if key else {}
    return _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "tools/call",
            "params": {"name": "kratos_lire", "arguments": args},
        },
        **kw,
    )


def test_kratos_lire_expose_aux_cles_tous_poles(client, seeded_users):
    # Clé de test sans scopes = lecture de tous les pôles → outil exposé.
    resp = _rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    noms = {t["name"] for t in resp.json()["result"]["tools"]}
    assert "kratos_lire" in noms
    init = _rpc(
        client,
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
    ).json()["result"]
    assert "kratos_lire" in init["instructions"]


def test_kratos_lire_lit_modules_hors_poles(client, seeded_users, auth_headers):
    # Une donnée créée via l'API (deal) se relit par kratos_lire.
    client.post(
        "/api/v1/prospection/deals",
        headers=auth_headers,
        json={"address": "123 rue de la Lecture Complète"},
    )
    resp = _lire(client, "/api/v1/prospection/deals", params={"limit": 50})
    res = resp.json()["result"]
    assert not res.get("isError"), res
    s = res["structuredContent"]
    assert s["ok"] is True and s["statut"] == 200, s
    assert "Lecture Complète" in json.dumps(s["reponse"], ensure_ascii=False)

    # Un module hors des 6 pôles (utilisateurs) est lisible aussi.
    s = _lire(client, "/api/v1/users", rid=901).json()["result"][
        "structuredContent"
    ]
    assert s["statut"] == 200, s

    # Liste officielle des clients (demande explicite de Steven).
    s = _lire(client, "/api/v1/clients", rid=902).json()["result"][
        "structuredContent"
    ]
    assert s["statut"] == 200, s


def test_kratos_lire_bloque_secrets_et_auth(client, seeded_users):
    for chemin in (
        "/api/v1/api-keys",
        "/api/v1/auth/me",
        "/api/v1/subscriptions/1/secret",
        "/api/v1/mon-ia",
        "/api/v1/drive/auth/url",
        "/api/v1/paiements/moi",
    ):
        res = _lire(client, chemin, rid=910).json()["result"]
        assert res.get("isError"), (chemin, res)
    res = _lire(client, "../etc/passwd", rid=911).json()["result"]
    assert res.get("isError"), res


def test_kratos_lire_refuse_cle_partielle(client, seeded_users, auth_headers):
    # Clé limitée à UN pôle → pas de lecture complète.
    r = client.post(
        "/api/v1/api-keys",
        headers=auth_headers,
        json={"name": "cle partielle", "scopes": ["devlog:activity:read"]},
    )
    assert r.status_code in (200, 201), r.text
    cle = r.json()["api_key"]
    resp = _rpc(
        client, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, key=cle
    )
    noms = {t["name"] for t in resp.json()["result"]["tools"]}
    assert "kratos_lire" not in noms
    assert "error" in _lire(client, "/api/v1/users", key=cle).json()

    # … sauf si la capacité explicite est cochée.
    r = client.post(
        "/api/v1/api-keys",
        headers=auth_headers,
        json={"name": "cle lecture", "scopes": ["api:lecture:complete"]},
    )
    cle2 = r.json()["api_key"]
    res = _lire(client, "/api/v1/users", key=cle2).json()["result"]
    assert res["structuredContent"]["statut"] == 200, res


def test_catalogue_liste_les_get_lisibles(client, seeded_users):
    resp = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "kratos_api_catalogue",
                "arguments": {"methode": "GET", "recherche": "/users"},
            },
        },
    )
    cat = resp.json()["result"]["structuredContent"]
    chemins = {o["chemin"] for o in cat["operations"]}
    assert any(c.startswith("/api/v1/users") for c in chemins), chemins
    assert not any(c.endswith("/secret") for c in chemins)
