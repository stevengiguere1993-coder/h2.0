"""Smoke — vitesse de lecture (Phil 2026-10-08 : « 115 secondes d'IA, pas
normal »). Un Excel de 21 Ko attendait trois 503 + un timeout de 60 s.

- Excel : colonnes lues directement, aucune IA appelée ;
- cascade : un modèle en erreur transitoire est mis en pause (ignoré au
  prochain appel), pas de nouvel essai sur le même modèle quand un autre
  reste à essayer, budget réduit respecté, flash-lite en tête pour le
  rent roll ;
- diagnostic : les pauses sont visibles dans extraction-health.
"""
from __future__ import annotations

import asyncio
import io

from app.services import lead_extraction as ex
from app.services import lead_rent_roll as rr


def _xlsx(rows) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_excel_lu_directement_sans_ia(monkeypatch):
    blob = _xlsx([
        ["Rent roll — 7444 Ormeaux", None, None],
        ["Unité", "Type", "Loyer mensuel"],
        ["101", "4 1/2", 950],
        ["102", "3½", "825,00 $"],
        ["103", "5.5", 1250.0],
        ["Stationnement", None, 75],
        ["Total", None, 3100],
    ])
    unites = rr.parse_rent_roll_excel(blob)
    assert [u["numero"] for u in unites] == ["101", "102", "103"]
    assert [u["typo"] for u in unites] == ["4.5", "3.5", "5.5"]
    assert [u["loyer_actuel"] for u in unites] == [950.0, 825.0, 1250.0]

    async def _ia_interdite(*a, **k):
        raise AssertionError("l'IA ne doit pas être appelée pour un Excel lisible")

    monkeypatch.setattr(ex, "_run_gemini_safely", _ia_interdite)
    monkeypatch.setattr(ex, "_run_groq_safely", _ia_interdite)
    res = asyncio.run(rr.extraire_rent_roll(files=[("rr.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", blob)]))
    assert res.source == "local" and res.model_used == "excel"
    assert len(res.unites) == 3 and any("sans IA" in w for w in res.warnings)
    # Loyer annuel ramené au mois ; sans en-têtes reconnues → liste vide.
    assert rr.parse_rent_roll_excel(_xlsx([["Logement", "Loyer"], ["1", 11400], ["2", 12000]]))[0]["loyer_actuel"] == 950.0
    assert rr.parse_rent_roll_excel(_xlsx([["a", "b"], [1, 2], [3, 4]])) == []


def test_pause_et_pas_de_nouvel_essai_quand_un_autre_modele_existe(monkeypatch):
    ex._GEMINI_PENALITES.clear()
    monkeypatch.setattr(ex.settings, "gemini_api_key", "x", raising=False)
    appels: list = []

    async def _fake_cascade(api_key=None):
        return ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"]

    async def _fake_extract(material, images, *, model, system=None, guide=None):
        appels.append(model)
        if model == "gemini-3.8-flash":
            return None, "erreur Gemini HTTP 503", False, False
        return [{"address": "ok"}], None, False, False

    monkeypatch.setattr(ex, "resolve_gemini_cascade", _fake_cascade)
    monkeypatch.setattr(ex, "_gemini_extract", _fake_extract)
    data, err, model = asyncio.run(ex._gemini_extract_cascade("texte", []))
    assert data and model == "gemini-3.5-flash-lite (cascade)"
    # Un seul essai sur le modèle saturé (pas de retry 3 s), puis le suivant.
    assert appels == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert "gemini-3.8-flash" in ex.modeles_gemini_en_pause()
    # Appel suivant : le modèle en pause n'est même plus essayé.
    appels.clear()
    data, err, model = asyncio.run(ex._gemini_extract_cascade("texte", []))
    assert appels == ["gemini-3.5-flash-lite"]
    # Rent roll : flash-lite d'abord même si la cascade met flash en tête.
    appels.clear()
    ex._GEMINI_PENALITES.clear()

    async def _fake_extract_ok(material, images, *, model, system=None, guide=None):
        appels.append(model)
        return [{"address": "ok"}], None, False, False

    monkeypatch.setattr(ex, "_gemini_extract", _fake_extract_ok)
    asyncio.run(ex._gemini_extract_cascade("texte", [], preferer_lite=True))
    assert appels == ["gemini-3.5-flash-lite"]
    # Tous en pause → on essaie quand même (pas de blocage).
    for m in ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"):
        ex._mettre_en_pause(m, 600)
    appels.clear()
    data, _e, _m = asyncio.run(ex._gemini_extract_cascade("texte", []))
    assert data and appels == ["gemini-3.8-flash"]
    ex._GEMINI_PENALITES.clear()


def test_budget_reduit_respecte(monkeypatch):
    ex._GEMINI_PENALITES.clear()
    monkeypatch.setattr(ex.settings, "gemini_api_key", "x", raising=False)
    monkeypatch.setattr(ex, "_GEMINI_MODELES_MIN", 1)
    appels: list = []

    async def _fake_cascade(api_key=None):
        return ["a-flash", "b-flash", "c-flash"]

    async def _fake_extract(material, images, *, model, system=None, guide=None):
        appels.append(model)
        await asyncio.sleep(0.05)
        return None, "réponse Gemini vide", False, False

    monkeypatch.setattr(ex, "resolve_gemini_cascade", _fake_cascade)
    monkeypatch.setattr(ex, "_gemini_extract", _fake_extract)
    data, err, _m = asyncio.run(ex._gemini_extract_cascade("texte", [], budget_s=0.01))
    assert data is None and appels == ["a-flash"]
    assert "budget de temps épuisé" in (err or "")
    ex._GEMINI_PENALITES.clear()


def test_health_expose_les_pauses(client, auth_headers, monkeypatch):
    ex._GEMINI_PENALITES.clear()
    ex._mettre_en_pause("gemini-3.8-flash", 300)
    monkeypatch.setattr(ex.settings, "gemini_api_key", "", raising=False)
    monkeypatch.setattr(ex.settings, "groq_api_key", "", raising=False)
    r = client.get("/api/v1/lead-analyses/extraction-health", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "gemini-3.8-flash" in r.json()["gemini"]["en_pause"]
    ex._GEMINI_PENALITES.clear()
