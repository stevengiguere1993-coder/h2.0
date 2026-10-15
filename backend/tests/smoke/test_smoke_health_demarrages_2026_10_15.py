"""Smoke — /health expose le démarrage du processus (2026-10-15).

Routine du matin de Phil : le connecteur MCP « n'était pas activé ».
Cause racine : les services Render Free s'endorment et la poignée de main
expire pendant le réveil. Pour le prouver jour après jour, /health donne
l'heure de démarrage de ce processus, son uptime et les derniers
démarrages enregistrés.
"""
from __future__ import annotations

from datetime import datetime


def test_journal_des_appels_mcp(client, auth_headers, employee_headers, api_key_headers):
    """Un initialize puis un tools/list sur le serveur MCP apparaissent dans
    le journal admin (heure, méthode, client, durée) ; un employé n'y a
    pas accès ; une clé invalide est journalisée comme refusée."""
    cle = api_key_headers["Authorization"].split()[-1] if "Authorization" in api_key_headers else api_key_headers.get("X-API-Key")
    assert cle, api_key_headers
    r = client.post(
        f"/api/v1/mcp/{cle}",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                         "clientInfo": {"name": "routine-test", "version": "9"}}},
    )
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/mcp/{cle}", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).status_code == 200
    assert client.post("/api/v1/mcp/krts_bidon", json={"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {}}).status_code == 401
    j = client.get("/api/v1/automations/mcp-journal", headers=auth_headers)
    assert j.status_code == 200, j.text
    entrees = j.json()["entrees"]
    methodes = [e["methode"] for e in entrees]
    assert "initialize" in methodes and "tools/list" in methodes
    init = next(e for e in entrees if e["methode"] == "initialize" and e["client"] == "routine-test 9")
    assert init["ok"] is True and isinstance(init["duree_ms"], int) and init["utilisateur"]
    refus = [e for e in entrees if e["cle"] == "krts_bidon"[:12]]
    assert refus and refus[-1]["ok"] is False
    assert client.get("/api/v1/automations/mcp-journal", headers=employee_headers).status_code == 403


def test_health_expose_le_demarrage(client):
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "healthy"
    datetime.fromisoformat(body["demarre_a"])  # ISO valide
    assert isinstance(body["uptime_s"], int) and body["uptime_s"] >= 0
    assert isinstance(body["derniers_demarrages"], list)
    assert len(body["derniers_demarrages"]) <= 10
