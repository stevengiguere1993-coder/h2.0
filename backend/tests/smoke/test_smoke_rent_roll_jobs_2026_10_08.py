"""Smoke — lecture d'un rent roll en tâche de fond (Phil 2026-10-08 :
« l'importation du rent roll, ça marche presque jamais »). La cascade IA
dépassait la coupure à 100 s de Render : le navigateur voyait un HTTP 500
alors que le serveur finissait (115 s sur un Excel de 21 Ko), et la fiche
supprimée entre-temps faisait échouer les pièces jointes.

- POST /unites/extract-jobs répond 202 tout de suite, GET suit jusqu'à
  « termine » avec la même proposition d'unités que l'endpoint synchrone ;
- fichiers attachés une seule fois ; fiche supprimée pendant la lecture →
  unités quand même renvoyées, sans pièce jointe ;
- la tâche d'un autre utilisateur (ou d'une autre fiche) est invisible.
"""
from __future__ import annotations

import json
import time

from app.api.v1.endpoints import lead_analyses as ep
from app.models.lead_analysis import LeadAnalysis
from app.services import lead_rent_roll as rr

from tests.smoke.conftest import TestSessionLocal


def _fake_rent_roll(unites):
    async def _fake(*, files=None, text=None):
        return rr.RentRollResult(unites=list(unites), warnings=["lu par le faux moteur"],
                                 model_used="fake", source="ia")

    return _fake


def _creer(run, adresse="9 rue du Rent Roll"):
    async def _c():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address=adresse, city="Montréal", asking_price=1_000_000, nb_logements=3,
                typology_json=json.dumps({"4.5": 3}), revenus_bruts=36_000,
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    return run(_c())


def _attendre(client, headers, base, job_id):
    etat = None
    for _ in range(100):
        j = client.get(f"{base}/unites/extract-jobs/{job_id}", headers=headers)
        assert j.status_code == 200, j.text
        etat = j.json()
        if etat["status"] != "en_cours":
            break
        time.sleep(0.1)
    return etat


def test_rent_roll_en_tache_de_fond(client, auth_headers, employee_headers, run, monkeypatch):
    unites = [
        {"numero": "1", "typo": "4.5", "loyer_actuel": 950.0, "loyer_optimise": None, "notes": None},
        {"numero": "2", "typo": "4.5", "loyer_actuel": 1000.0, "loyer_optimise": 1300.0, "notes": None},
    ]
    monkeypatch.setattr(rr, "extraire_rent_roll", _fake_rent_roll(unites))
    monkeypatch.setattr(ep, "_session_factory_jobs", lambda: TestSessionLocal)
    fid = _creer(run)
    base = f"/api/v1/lead-analyses/{fid}"

    r = client.post(
        f"{base}/unites/extract-jobs", headers=auth_headers,
        files={"files": ("rent_roll.xlsx", b"PK fake", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    etat = _attendre(client, auth_headers, base, job_id)
    assert etat and etat["status"] == "termine", etat
    res = etat["resultat"]
    assert [u["loyer_actuel"] for u in res["unites"]] == [950.0, 1000.0]
    assert res["typology"] == {"4.5": 3} and res["nb_logements"] == 3
    assert "_task" not in etat and "duree_s" in etat
    # Le fichier est attaché une seule fois, même après un 2e import.
    r2 = client.post(
        f"{base}/unites/extract-jobs", headers=auth_headers,
        files={"files": ("rent_roll.xlsx", b"PK fake", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert _attendre(client, auth_headers, base, r2.json()["job_id"])["status"] == "termine"
    fiche = client.get(base, headers=auth_headers).json()
    assert [a["filename"] for a in fiche["attachments"]] == ["rent_roll.xlsx"]
    # Invisible pour un autre utilisateur ou depuis une autre fiche.
    assert client.get(f"{base}/unites/extract-jobs/{job_id}", headers=employee_headers).status_code == 404
    assert client.get(f"/api/v1/lead-analyses/{fid + 1000}/unites/extract-jobs/{job_id}", headers=auth_headers).status_code == 404
    # Sans source → 400 tout de suite.
    assert client.post(f"{base}/unites/extract-jobs", headers=auth_headers, data={}).status_code == 400


def test_fiche_supprimee_pendant_la_lecture(client, auth_headers, run, monkeypatch):
    fid = _creer(run, "10 rue Fantôme")
    base = f"/api/v1/lead-analyses/{fid}"

    async def _lente(*, files=None, text=None):
        # La fiche disparaît pendant la lecture (comme le 2026-10-08 à 14:19).
        async with TestSessionLocal() as s:
            rec = await s.get(LeadAnalysis, fid)
            await s.delete(rec)
            await s.commit()
        return rr.RentRollResult(
            unites=[{"numero": "1", "typo": "3.5", "loyer_actuel": 800.0, "loyer_optimise": None, "notes": None}],
            warnings=[], model_used="fake", source="ia",
        )

    monkeypatch.setattr(rr, "extraire_rent_roll", _lente)
    r = client.post(f"{base}/unites/extract", headers=auth_headers, data={"text": "App 1 3½ 800 $"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert [u["loyer_actuel"] for u in d["unites"]] == [800.0]
    assert any("supprimée" in w for w in d["warnings"])
