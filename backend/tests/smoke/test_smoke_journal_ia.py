"""Smoke — chantier « IA au courant de tout » (GO Phil 2026-09-02).

1. Middleware d'audit AUTOMATIQUE : chaque écriture API réussie crée
   une entrée AuditLog (utilisateur du JWT, chemin, corps masqué) ;
   les GET ne journalisent rien ; les champs sensibles sont masqués.
2. Outil MCP kratos_sommaire_du_jour : le journal complet de la
   période, tous utilisateurs, avec synthèse et pagination.
"""
from __future__ import annotations

import json

from sqlalchemy import select

from app.models.audit_log import AuditLog

from .conftest import TestSessionLocal


def _audit_rows(run, action_prefix: str | None = None):
    async def _go():
        async with TestSessionLocal() as s:
            q = select(AuditLog).order_by(AuditLog.id.desc())
            rows = (await s.execute(q)).scalars().all()
            if action_prefix:
                rows = [r for r in rows if r.action.startswith(action_prefix)]
            return rows

    return run(_go())


def test_middleware_journalise_les_ecritures(
    client, auth_headers, run, monkeypatch
):
    # Le middleware écrit via AsyncSessionLocal (hors requête) — en
    # test, on le pointe sur la base de test.
    import app.db.session as app_session

    monkeypatch.setattr(
        app_session, "AsyncSessionLocal", TestSessionLocal
    )
    # Une écriture métier quelconque : création d'une soumission.
    r = client.post(
        "/api/v1/soumissions",
        headers=auth_headers,
        json={"title": "Journal IA", "reference": "SOU-JRN-1"},
    )
    assert r.status_code in (200, 201), r.text

    rows = _audit_rows(run, "api.post")
    assert rows, "aucune entrée auto-journalisée"
    entree = next(
        (
            x
            for x in rows
            if (x.entity_type or "").startswith("soumissions")
        ),
        None,
    )
    assert entree is not None, [x.entity_type for x in rows[:5]]
    assert entree.user_email, "l'utilisateur du JWT doit être résolu"
    d = json.loads(entree.details_json or "{}")
    assert d.get("auto") is True
    assert d.get("methode") == "POST"
    assert "Journal IA" in json.dumps(d, ensure_ascii=False)


def test_middleware_masque_les_secrets_et_ignore_les_get(
    client, auth_headers, run, monkeypatch
):
    import app.db.session as app_session

    monkeypatch.setattr(
        app_session, "AsyncSessionLocal", TestSessionLocal
    )
    avant = len(_audit_rows(run))
    # GET → rien.
    client.get("/api/v1/soumissions", headers=auth_headers)
    assert len(_audit_rows(run)) == avant

    # Écriture avec un champ sensible → masqué dans le journal.
    client.put(
        "/api/v1/mon-ia",
        headers=auth_headers,
        json={"provider": "anthropic", "api_key": "sk-super-secret-123"},
    )
    rows = _audit_rows(run, "api.put")
    entree = next(
        (x for x in rows if (x.entity_type or "").startswith("mon_ia")),
        None,
    )
    assert entree is not None
    assert "sk-super-secret-123" not in (entree.details_json or "")
    assert "•••" in (entree.details_json or "")

    # Nettoyage : ne pas laisser une config Mon IA derrière (le test
    # du cycle complet part d'un état « rien de connecté »).
    client.delete("/api/v1/mon-ia", headers=auth_headers)


def test_mcp_catalogue_et_action(client, seeded_users, auth_headers, run):
    """« Tout ce qui est actionnable doit pouvoir être fait via la
    clé » (Phil 2026-09-02) : le catalogue OpenAPI liste chaque
    opération (futures incluses, auto-généré), et kratos_action exécute
    au nom du propriétaire — capacité api:actions:executer requise,
    chemins d'auth/clés bloqués."""
    from .test_smoke_mcp import _rpc

    # Catalogue : dispo pour toute clé, contient la création de
    # soumission et se filtre.
    resp = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 51,
            "method": "tools/call",
            "params": {
                "name": "kratos_api_catalogue",
                "arguments": {"recherche": "soumissions", "methode": "POST"},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    cat = resp.json()["result"]["structuredContent"]
    chemins = {o["chemin"] for o in cat["operations"]}
    assert "/api/v1/soumissions" in chemins, sorted(chemins)[:10]

    # La clé de test n'a pas la capacité → l'outil n'est même pas
    # exposé (erreur JSON-RPC « outil indisponible »).
    resp = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 52,
            "method": "tools/call",
            "params": {
                "name": "kratos_action",
                "arguments": {
                    "methode": "POST",
                    "chemin": "/api/v1/soumissions",
                    "corps": {"title": "Refusée"},
                },
            },
        },
    )
    assert "error" in resp.json(), resp.json()

    # Clé AVEC la capacité : création via l'admin, puis action réelle.
    r = client.post(
        "/api/v1/api-keys",
        headers=auth_headers,
        json={"name": "cle action", "scopes": ["api:actions:executer"]},
    )
    assert r.status_code in (200, 201), r.text
    cle = r.json().get("api_key")
    assert cle, r.json()

    resp = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 53,
            "method": "tools/call",
            "params": {
                "name": "kratos_action",
                "arguments": {
                    "methode": "POST",
                    "chemin": "/api/v1/soumissions",
                    "corps": {"title": "Créée par kratos_action"},
                },
            },
        },
        key=cle,
    )
    assert resp.status_code == 200, resp.text
    assert "result" in resp.json(), resp.json()
    res = resp.json()["result"]
    assert not res.get("isError"), res
    s = res["structuredContent"]
    assert s["ok"] is True and s["statut"] in (200, 201), s
    assert "Créée par kratos_action" in json.dumps(
        s["reponse"], ensure_ascii=False
    )

    # Chemin bloqué (gestion des clés) → refus net.
    resp = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 54,
            "method": "tools/call",
            "params": {
                "name": "kratos_action",
                "arguments": {
                    "methode": "POST",
                    "chemin": "/api/v1/api-keys",
                    "corps": {"name": "escalade"},
                },
            },
        },
        key=cle,
    )
    assert resp.json()["result"].get("isError"), resp.json()


def test_mcp_sommaire_du_jour(
    client, seeded_users, auth_headers, run, monkeypatch
):
    import app.db.session as app_session

    monkeypatch.setattr(
        app_session, "AsyncSessionLocal", TestSessionLocal
    )
    from .test_smoke_mcp import _rpc

    # Génère au moins un événement aujourd'hui.
    client.post(
        "/api/v1/soumissions",
        headers=auth_headers,
        json={"title": "Événement sommaire", "reference": "SOU-JRN-2"},
    )

    resp = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 41,
            "method": "tools/call",
            "params": {"name": "kratos_sommaire_du_jour", "arguments": {}},
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert not result.get("isError"), result
    s = result.get("structuredContent")
    assert isinstance(s, dict)
    assert {"periode", "synthese", "evenements", "total_visibles"} <= set(
        s.keys()
    )
    assert s["total_visibles"] >= 1
    assert s["synthese"]["par_action"]
    # L'événement d'écriture est dedans, avec son auteur.
    actions = {e["action"] for e in s["evenements"]}
    assert any(a.startswith("api.post") for a in actions), actions
