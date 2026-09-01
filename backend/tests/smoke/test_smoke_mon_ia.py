"""Smoke — « chacun son IA » (chantier IA personnelle, 2026-09-01).

Couvre : la connexion (clé jamais renvoyée en clair), le test de
connexion, le brief quotidien, le routage d'une fonction IA existante
(estimation des dépenses d'analyse) vers l'IA PERSONNELLE, et la
déconnexion (retour au comportement historique).
"""
from __future__ import annotations

from app.integrations.ai._base import CompletionResult
from app.models.lead_analysis import LeadAnalysis
from app.services import user_ai as user_ai_svc

from .conftest import TestSessionLocal

FAKE_JSON = (
    '{"taxes_municipales": 5000, "taxes_scolaires": null, '
    '"assurances": 2400, "note": "estimation test"}'
)


class FakeProvider:
    name = "fake"
    default_completion_model = "fake-1"
    default_embedding_model = ""

    def __init__(self, api_key=None):
        self.api_key = api_key

    async def complete(self, **_kw):
        assert self.api_key == "sk-test-123456789", (
            "l'appel doit passer par la clé PERSONNELLE de l'utilisateur"
        )
        return CompletionResult(
            text=FAKE_JSON, model="fake-1", provider="fake"
        )


def _seed_lead(run) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="1 rue Test IA",
                city="Montréal",
                asking_price=500_000,
                nb_logements=6,
            )
            s.add(rec)
            await s.flush()
            lid = rec.id
            await s.commit()
            return lid

    return run(_go())


def test_mon_ia_cycle_complet(client, auth_headers, run, monkeypatch):
    # 1. Rien de connecté au départ.
    r = client.get("/api/v1/mon-ia", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["connecte"] is False

    # 2. Connexion — la clé n'est JAMAIS renvoyée en clair.
    r = client.put(
        "/api/v1/mon-ia",
        headers=auth_headers,
        json={"provider": "anthropic", "api_key": "sk-test-123456789"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["connecte"] is True
    assert "sk-test-123456789" not in r.text
    assert d["api_key_masquee"].startswith("sk-te")

    # 3. Test de connexion + brief via le provider factice (la clé de
    # l'utilisateur doit lui être transmise).
    monkeypatch.setitem(
        user_ai_svc.PROVIDERS_PERSO, "anthropic", FakeProvider
    )
    r = client.post("/api/v1/mon-ia/test", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    r = client.post("/api/v1/mon-ia/brief", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["contenu"] == FAKE_JSON

    r = client.get("/api/v1/mon-ia", headers=auth_headers)
    assert r.json()["brief_contenu"] == FAKE_JSON

    # 4. Routage d'une fonction IA existante : l'estimation des
    # dépenses passe par l'IA personnelle (note préfixée du provider).
    lid = _seed_lead(run)
    r = client.post(
        f"/api/v1/lead-analyses/{lid}/estimate-expenses",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    est = r.json()
    assert est["source"] == "ai"
    assert est["taxes_municipales"] == 5000
    assert est["note"].startswith("[fake]")

    # 5. Déconnexion → l'estimation retombe sur le comportement
    # historique (heuristique ici, aucune clé maison en test).
    r = client.delete("/api/v1/mon-ia", headers=auth_headers)
    assert r.status_code == 204
    r = client.get("/api/v1/mon-ia", headers=auth_headers)
    assert r.json()["connecte"] is False

    r = client.post(
        f"/api/v1/lead-analyses/{lid}/estimate-expenses",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["source"] != "ai"
