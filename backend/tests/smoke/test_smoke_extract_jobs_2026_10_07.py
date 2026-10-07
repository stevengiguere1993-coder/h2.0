"""Smoke — extraction de fiches sans coupure ni doublon (Phil 2026-10-07 :
« j'ai souvent cette erreur en extrayant, mais si je refresh, la fiche
apparaît ; si je l'extrais à nouveau, elle est là en double »).

- tâche de fond : POST /extract-jobs répond tout de suite, GET
  /extract-jobs/{id} suit jusqu'à « termine » ;
- idempotence : même source dans les minutes qui suivent → fiche
  existante renvoyée (endpoint synchrone et tâche de fond) ;
- budget de temps de la cascade Gemini.
"""
from __future__ import annotations

import asyncio
import time

from app.api.v1.endpoints import lead_analyses as ep
from app.core.config import settings
from app.services import lead_extraction as ex

from tests.smoke.conftest import TestSessionLocal


def _fake_extraction(adresse: str):
    async def _fake(urls=None, text=None, files=None):
        return ex.ExtractionResult(
            data=[{"address": adresse, "city": "Montréal", "asking_price": 500_000, "nb_logements": 4}],
            model_used="local",
            warnings=[],
            per_source_values=[{}],
        )

    return _fake


def test_meme_source_ne_cree_pas_de_doublon(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ep, "extract_lead_info", _fake_extraction("77 rue Doublon"))
    texte = "77 rue Doublon, Montréal — 4 logements — 500 000 $"
    r1 = client.post("/api/v1/lead-analyses/extract", headers=auth_headers, data={"text": texte})
    assert r1.status_code == 201, r1.text
    id1 = r1.json()["created"][0]["id"]
    # Deuxième essai (comme après une erreur réseau) : même fiche, pas de doublon.
    r2 = client.post("/api/v1/lead-analyses/extract", headers=auth_headers, data={"text": texte})
    assert r2.status_code == 201, r2.text
    assert [c["id"] for c in r2.json()["created"]] == [id1]
    assert any("déjà été extraite" in w for w in r2.json()["warnings"])
    # Une source différente → nouvelle fiche.
    r3 = client.post("/api/v1/lead-analyses/extract", headers=auth_headers, data={"text": texte + " (autre)"})
    assert r3.status_code == 201 and r3.json()["created"][0]["id"] != id1
    # Même texte mais un fichier en plus → nouvelle fiche aussi.
    r4 = client.post(
        "/api/v1/lead-analyses/extract", headers=auth_headers,
        data={"text": texte}, files={"files": ("note.txt", b"bonjour", "text/plain")},
    )
    assert r4.status_code == 201 and r4.json()["created"][0]["id"] not in (id1,)


def test_extraction_en_tache_de_fond(client, auth_headers, employee_headers, monkeypatch):
    monkeypatch.setattr(ep, "extract_lead_info", _fake_extraction("88 rue du Fond"))
    monkeypatch.setattr(ep, "_session_factory_jobs", lambda: TestSessionLocal)
    r = client.post(
        "/api/v1/lead-analyses/extract-jobs", headers=auth_headers,
        data={"text": "88 rue du Fond, 6 logements"},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    etat = None
    for _ in range(100):
        j = client.get(f"/api/v1/lead-analyses/extract-jobs/{job_id}", headers=auth_headers)
        assert j.status_code == 200, j.text
        etat = j.json()
        if etat["status"] != "en_cours":
            break
        time.sleep(0.1)
    assert etat and etat["status"] == "termine", etat
    assert etat["resultat"]["created"][0]["address"] == "88 rue du Fond"
    assert "duree_s" in etat and "_task" not in etat
    # La fiche est bien en base (visible par l'API).
    fid = etat["resultat"]["created"][0]["id"]
    assert client.get(f"/api/v1/lead-analyses/{fid}", headers=auth_headers).status_code == 200
    # Un autre utilisateur ne voit pas cette tâche.
    assert client.get(f"/api/v1/lead-analyses/extract-jobs/{job_id}", headers=employee_headers).status_code in (403, 404)
    # Tâche inconnue → 404 explicite ; sans source → 400.
    assert client.get("/api/v1/lead-analyses/extract-jobs/inconnue", headers=auth_headers).status_code == 404
    assert client.post("/api/v1/lead-analyses/extract-jobs", headers=auth_headers, data={"text": ""}).status_code == 400
    # Relancer la même source en tâche de fond → même fiche (idempotent).
    r = client.post(
        "/api/v1/lead-analyses/extract-jobs", headers=auth_headers,
        data={"text": "88 rue du Fond, 6 logements"},
    )
    assert r.status_code == 202
    job2 = r.json()["job_id"]
    for _ in range(100):
        etat2 = client.get(f"/api/v1/lead-analyses/extract-jobs/{job2}", headers=auth_headers).json()
        if etat2["status"] != "en_cours":
            break
        time.sleep(0.1)
    assert etat2["status"] == "termine", etat2
    assert etat2["resultat"]["created"][0]["id"] == fid
    assert any("déjà été extraite" in w for w in etat2["resultat"]["warnings"])


def test_cascade_gemini_respecte_le_budget_de_temps(monkeypatch):
    monkeypatch.setattr(ex, "_GEMINI_BUDGET_S", 0.5)
    monkeypatch.setattr(settings, "gemini_api_key", "cle-test")
    appels: list = []

    async def _lent(material, images, model=None, system=None, guide=None):
        appels.append(model)
        await asyncio.sleep(0.4)
        return None, "erreur Gemini HTTP 503", False, False

    async def _cascade(_key=None):
        return ["m1", "m2", "m3", "m4"]

    monkeypatch.setattr(ex, "_gemini_extract", _lent)
    monkeypatch.setattr(ex, "resolve_gemini_cascade", _cascade)
    data, raison, modele = asyncio.run(ex._gemini_extract_cascade("texte", []))
    assert data is None and modele is None
    assert len(appels) <= 2, appels
    assert "budget de temps" in raison
