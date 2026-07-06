"""Smoke — CONTRATS FIGÉS du connecteur API/MCP (clé krts_…).

Ces tests protègent le contrat PUBLIC consommé par les agents Claude de
Phil (connecteurs custom + serveur MCP). On fige la FORME des réponses
(clés de premier niveau) — pas leur contenu. Si un refactoring change
ces clés, les connecteurs externes cassent : ces tests doivent péter.

La clé d'API est seedée directement en DB (hash SHA-256, voir conftest),
comme le ferait POST /api-keys ; clé sans scopes = lecture de tous les
pôles (rétrocompat assumée par le code).
"""

from tests.smoke.conftest import API_KEY_PLAINTEXT

# ── Connecteur REST (/activity/*, auth par clé d'API) ────────────────

#: Clés de premier niveau du contrat GET /activity/me — FIGÉES.
ACTIVITY_ME_KEYS = {
    "user_id",
    "user_email",
    "timezone",
    "period_start",
    "period_end",
    "tasks",
    "audit",
    "summary",
}

#: Clés de premier niveau du contrat GET /activity/entities/{type} — FIGÉES.
LIST_ENTITIES_KEYS = {
    "entity_type",
    "pole",
    "items",
    "count",
    "limit",
    "offset",
    "truncated",
}


def test_activity_me_contract(client, api_key_headers):
    resp = client.get("/api/v1/activity/me", headers=api_key_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == ACTIVITY_ME_KEYS
    assert isinstance(body["tasks"], list)
    assert isinstance(body["audit"], list)
    assert isinstance(body["summary"], str)
    assert body["timezone"] == "America/Toronto"


def test_activity_me_requires_api_key(client):
    resp = client.get("/api/v1/activity/me")
    assert resp.status_code == 401


def test_activity_me_rejects_jwt_only(client, auth_headers):
    # Un JWT n'est PAS une clé krts_… : l'endpoint doit refuser.
    resp = client.get("/api/v1/activity/me", headers=auth_headers)
    assert resp.status_code == 401


def test_activity_list_entities_contract(client, api_key_headers, auth_headers):
    # Garantit au moins un deal (créé via l'API interne, auth JWT).
    client.post(
        "/api/v1/prospection/deals",
        headers=auth_headers,
        json={"address": "999 rue du Connecteur"},
    )
    resp = client.get(
        "/api/v1/activity/entities/deals", headers=api_key_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == LIST_ENTITIES_KEYS
    assert isinstance(body["items"], list)
    assert body["count"] >= 1
    assert isinstance(body["truncated"], bool)


def test_activity_members_contract(client, api_key_headers):
    resp = client.get("/api/v1/activity/members", headers=api_key_headers)
    assert resp.status_code == 200, resp.text
    members = resp.json()
    assert isinstance(members, list) and members
    first = members[0]
    # Forme d'un membre — FIGÉE (kind/id/name/email).
    assert set(first.keys()) == {"kind", "id", "name", "email"}


# ── Serveur MCP (JSON-RPC Streamable HTTP, clé dans le path) ─────────


def _rpc(client, payload: dict, key: str = API_KEY_PLAINTEXT):
    return client.post(f"/api/v1/mcp/{key}", json=payload)


def test_mcp_initialize_contract(client, seeded_users):
    resp = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    result = body["result"]
    # Clés du handshake MCP — FIGÉES.
    assert set(result.keys()) == {
        "protocolVersion",
        "capabilities",
        "serverInfo",
        "instructions",
    }
    assert result["protocolVersion"] == "2025-06-18"
    assert set(result["serverInfo"].keys()) == {"name", "version"}


def test_mcp_tools_list_contract(client, seeded_users):
    resp = _rpc(
        client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    assert resp.status_code == 200, resp.text
    tools = resp.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    # Outils de lecture toujours exposés — FIGÉS.
    for expected in (
        "kratos_my_activity",
        "kratos_my_summary",
        "kratos_activity_range",
        "kratos_list_entities",
        "kratos_list_members",
    ):
        assert expected in names, f"outil MCP manquant : {expected}"
    # Chaque outil déclare nom + description + schéma d'entrée.
    for t in tools:
        assert {"name", "description", "inputSchema"} <= set(t.keys())


def test_mcp_tools_call_my_activity(client, seeded_users):
    resp = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "kratos_my_activity", "arguments": {}},
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert not result.get("isError"), result
    content = result["content"]
    assert content and content[0]["type"] == "text"
    # Le payload structuré est aussi retourné (structuredContent).
    structured = result.get("structuredContent")
    assert isinstance(structured, dict)
    assert {"tasks", "audit"} <= set(structured.keys())


def test_mcp_invalid_key_401(client, seeded_users):
    resp = _rpc(
        client,
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        key="krts_invalide_0000000000000000000000000000000",
    )
    assert resp.status_code == 401
    assert "error" in resp.json()
