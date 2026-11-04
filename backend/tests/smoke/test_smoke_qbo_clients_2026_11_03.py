"""Smoke — liste des Customers QuickBooks (actifs ET inactifs) lisible par
l'API et le connecteur Claude (Steven 2026-11-03)."""

from app.integrations import quickbooks as qbo_mod
from tests.smoke.test_smoke_mcp import _rpc

_CLIENTS = [
    {"Id": "1", "DisplayName": "Groupe Alpha", "Active": True, "Balance": 120.5,
     "Job": False, "FullyQualifiedName": "Groupe Alpha",
     "PrimaryEmailAddr": {"Address": "a@alpha.ca"}},
    {"Id": "2", "DisplayName": "1660 Saint-Clément", "Active": True,
     "Balance": 0, "Job": True, "Level": 1,
     "ParentRef": {"value": "1", "name": "Groupe Alpha"},
     "FullyQualifiedName": "Groupe Alpha:1660 Saint-Clément"},
    {"Id": "3", "DisplayName": "Ancien client", "Active": False, "Balance": 0},
]


class _FauxQbo:
    def __init__(self):
        self.requetes = []

    async def query_all(self, sql, **kw):
        self.requetes.append(sql)
        if "Active = false" in sql:
            return [c for c in _CLIENTS if not c["Active"]]
        if "Active = true" in sql:
            return [c for c in _CLIENTS if c["Active"]]
        return list(_CLIENTS)


def test_customers_qbo_actifs_et_inactifs(client, auth_headers, monkeypatch):
    faux = _FauxQbo()
    scopes = []
    monkeypatch.setattr(
        qbo_mod, "get_qbo", lambda scope="construction": scopes.append(scope) or faux
    )
    for chemin in ("/api/v1/qbo/customers", "/api/v1/qbo/clients"):
        r = client.get(chemin, headers=auth_headers)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["total"] == 3 and b["actifs"] == 2 and b["inactifs"] == 1
        ids = {c["Id"]: c for c in b["clients"]}
        assert ids["3"]["Active"] is False
        assert ids["1"]["Balance"] == 120.5
        assert ids["2"]["ParentRef"] == {"value": "1", "name": "Groupe Alpha"}
    assert "Active IN (true, false)" in faux.requetes[0]

    r = client.get(
        "/api/v1/qbo/customers",
        params={"compagnie": "immobilier", "statut": "inactifs", "limit": 1},
        headers=auth_headers,
    )
    assert r.status_code == 200 and r.json()["total"] == 1
    assert scopes[-1] == "immobilier"
    assert client.get(
        "/api/v1/qbo/customers", params={"compagnie": "x; drop"},
        headers=auth_headers,
    ).status_code == 422


def test_customers_qbo_par_le_connecteur(client, seeded_users, monkeypatch):
    monkeypatch.setattr(qbo_mod, "get_qbo", lambda scope="construction": _FauxQbo())
    res = _rpc(
        client,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "kratos_api_catalogue",
                    "arguments": {"recherche": "customer", "methode": "GET"}}},
    ).json()["result"]["structuredContent"]
    assert "/api/v1/qbo/customers" in {o["chemin"] for o in res["operations"]}

    res = _rpc(
        client,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "kratos_lire",
                    "arguments": {"chemin": "/api/v1/qbo/customers"}}},
    ).json()["result"]
    assert not res.get("isError"), res
    s = res["structuredContent"]
    assert s["statut"] == 200, s
    assert s["reponse"]["total"] == 3
