"""Smoke — rent roll → unités (Phil 2026-10-07) : un PDF, une photo ou
un texte de la liste des loyers est lu comme la section Infos (IA,
relais Groq, parser local) et propose le loyer actuel par logement ;
le numéro d'unité suit jusqu'au moteur, à la trace et au PDF."""
from __future__ import annotations

import asyncio
import io
import json

from app.models.lead_analysis import LeadAnalysis
from app.services import lead_extraction as ex
from app.services import lead_rent_roll as rr
from app.services.lead_analysis_finance import normaliser_unites

from tests.smoke.conftest import TestSessionLocal


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_normaliser_typo():
    assert rr.normaliser_typo("4 1/2") == "4.5"
    assert rr.normaliser_typo("4½") == "4.5"
    assert rr.normaliser_typo("3,5") == "3.5"
    assert rr.normaliser_typo("5.5 chauffé") == "5.5"
    assert rr.normaliser_typo("Studio") == "1.5"
    assert rr.normaliser_typo(None) is None
    assert rr.normaliser_typo("") is None


def test_parser_local_rent_roll():
    texte = """Rent roll — 1234 rue Test
App. 1    4 1/2    950 $
App. 2 — 3½ — 825,00 $
3        5 1/2    1 250 $
Bail 2025-07-01 au 2026-06-30 : 1 100 $ (app. 4, 4½)
Total mensuel : 4 125 $
"""
    unites = rr.parse_rent_roll_text(texte)
    assert [u["numero"] for u in unites] == ["1", "2", "3", None]
    assert [u["typo"] for u in unites] == ["4.5", "3.5", "5.5", "4.5"]
    assert [u["loyer_actuel"] for u in unites] == [950.0, 825.0, 1250.0, 1100.0]
    # Une seule ligne → pas un rent roll.
    assert rr.parse_rent_roll_text("App. 1  950 $") == []


def test_normaliser_unites_extraites():
    out = rr.normaliser_unites_extraites(
        [{"unites": [
            {"numero": 101, "typo": "4½", "loyer_actuel": "1 050 $", "loyer_optimise": None, "notes": "chauffé"},
            {"numero": "App. 3", "typo": "studio", "loyer_actuel": 13200, "loyer_optimise": 14400},
            {"numero": "x", "typo": "3.5", "loyer_actuel": 0},
        ]}]
    )
    assert out == [
        {"numero": "101", "typo": "4.5", "loyer_actuel": 1050.0, "loyer_optimise": None, "notes": "chauffé"},
        {"numero": "App. 3", "typo": "1.5", "loyer_actuel": 1100.0, "loyer_optimise": 1200.0, "notes": None},
    ]
    assert rr.normaliser_unites_extraites({"unites": []}) == []
    assert rr.normaliser_unites_extraites([{"typo": "4.5", "loyer_actuel": 900}]) == [
        {"numero": None, "typo": "4.5", "loyer_actuel": 900.0, "loyer_optimise": None, "notes": None}
    ]


def test_extraire_rent_roll_ia_puis_relais_puis_local(monkeypatch):
    recu: dict = {}

    async def _gemini_ok(material, images, *, system=None, guide=None):
        recu["system"] = system
        recu["images"] = images
        return [{"unites": [{"numero": "1", "typo": "4½", "loyer_actuel": 950}]}], None, "gemini-2.5-flash"

    monkeypatch.setattr(ex, "_run_gemini_safely", _gemini_ok)
    monkeypatch.setattr(ex, "parse_image_ocr", lambda blob, filename="image": "")
    res = asyncio.run(rr.extraire_rent_roll(files=[("rentroll.png", "image/png", _png())]))
    assert res.source == "ia" and res.model_used == "gemini-2.5-flash"
    assert res.unites == [{"numero": "1", "typo": "4.5", "loyer_actuel": 950.0, "loyer_optimise": None, "notes": None}]
    assert recu["system"] == rr.SYSTEM_PROMPT_RENT_ROLL  # prompt dédié, pas celui des fiches
    assert recu["images"][0][0] == "image/png"

    # Gemini à sec → Groq.
    async def _gemini_ko(material, images, *, system=None, guide=None):
        return None, "cascade épuisée — gemini-2.5-flash : quota quotidien gratuit atteint", None

    async def _groq_ok(material, images, *, system=None, guide=None):
        return [{"numero": "2", "typo": "3 1/2", "loyer_actuel": 825}], None, "meta-llama/llama-4-scout-17b-16e-instruct"

    monkeypatch.setattr(ex, "_run_gemini_safely", _gemini_ko)
    monkeypatch.setattr(ex, "_run_groq_safely", _groq_ok)
    res = asyncio.run(rr.extraire_rent_roll(files=[("rentroll.png", "image/png", _png())]))
    assert res.source == "ia" and res.model_used.startswith("groq (")
    assert res.unites[0]["typo"] == "3.5"
    assert any("relais pris par Groq" in w for w in res.warnings)

    # Les deux IA muettes → parser local sur le texte collé.
    async def _groq_ko(material, images, *, system=None, guide=None):
        return None, "quota Groq atteint", None

    monkeypatch.setattr(ex, "_run_groq_safely", _groq_ko)
    res = asyncio.run(rr.extraire_rent_roll(text="App. 1  4½  950 $\nApp. 2  3½  825 $"))
    assert res.source == "local" and res.model_used == "local"
    assert [u["loyer_actuel"] for u in res.unites] == [950.0, 825.0]
    assert any("parser local" in w for w in res.warnings)

    # Rien de lisible.
    res = asyncio.run(rr.extraire_rent_roll(text="bonjour"))
    assert res.unites == [] and res.source == "none"


def test_numero_suit_dans_le_moteur():
    u = normaliser_unites([{"numero": "A-1", "typo": "4.5", "loyer_actuel": 900, "loyer_optimise": 1200, "mode": "post_achat"}])
    assert u[0]["numero"] == "A-1"
    assert normaliser_unites([{"typo": "4.5", "loyer_actuel": 900}])[0]["numero"] is None


def _mk_fiche(run) -> int:
    async def _create():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="789 rue du Rent Roll",
                city="Montréal",
                asking_price=1_200_000,
                nb_logements=3,
                typology_json=json.dumps({"3.5": 1, "4.5": 2}),
                revenus_bruts=(900 + 1_000 + 1_050) * 12,
                taxes_municipales=9_000,
                taxes_scolaires=700,
                assurances=3_500,
                energie=0,
                depenses_autres=0,
                loyers_projetes_json=json.dumps({"3.5": 1250, "4.5": 1450}),
                taux_interet_refi_pct=4.0,
                tga_pct=4.0,
                duree_projet_annees=2,
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    return run(_create())


def test_endpoint_rent_roll_puis_analyse(client, auth_headers, run, monkeypatch):
    async def _gemini_ok(material, images, *, system=None, guide=None):
        return (
            [{"unites": [
                {"numero": "101", "typo": "3½", "loyer_actuel": 900},
                {"numero": "201", "typo": "4½", "loyer_actuel": 1000},
                {"numero": "202", "typo": "4½", "loyer_actuel": 1050, "loyer_optimise": 1500},
            ]}],
            None,
            "gemini-2.5-flash",
        )

    monkeypatch.setattr(ex, "_run_gemini_safely", _gemini_ok)
    monkeypatch.setattr(ex, "parse_image_ocr", lambda blob, filename="image": "")
    fid = _mk_fiche(run)
    base = f"/api/v1/lead-analyses/{fid}"

    r = client.post(f"{base}/unites/extract", headers=auth_headers, files={"files": ("rentroll.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "ia" and body["nb_logements"] == 3
    assert body["typology"] == {"3.5": 1, "4.5": 2}
    assert [u["numero"] for u in body["unites"]] == ["101", "201", "202"]
    assert [u["typo"] for u in body["unites"]] == ["3.5", "4.5", "4.5"]
    # Le fichier est joint à la fiche ; le tableau n'est PAS encore touché.
    d = client.get(base, headers=auth_headers).json()
    assert [a["filename"] for a in d["attachments"]] == ["rentroll.png"]
    assert not d.get("unites_json")

    # Sans source → 400.
    assert client.post(f"{base}/unites/extract", headers=auth_headers, data={"text": ""}).status_code == 400

    # « Appliquer » côté fiche = PATCH unites_json (format v2 + numéro).
    unites = [
        {"typo": u["typo"], "numero": u["numero"], "loyer_actuel": u["loyer_actuel"],
         "loyer_optimise": u["loyer_optimise"] or {"3.5": 1250, "4.5": 1450}[u["typo"]], "mode": "post_achat"}
        for u in body["unites"]
    ]
    r = client.patch(base, headers=auth_headers, json={"unites_json": json.dumps(unites), "strategie_acquisition": "traditionnel"})
    assert r.status_code == 200, r.text
    r = client.post(f"{base}/run-financial-analysis", headers=auth_headers)
    assert r.status_code == 200, r.text
    uc = r.json()["analysis_results"]["unites_calcul"]
    assert [u["numero"] for u in uc["unites"]] == ["101", "201", "202"]
    assert uc["total_actuel_mois"] == 2950.0
    assert uc["revenus_achat"] == 2950.0 * 12
    # Trace : le numéro remplace « #1 ».
    r = client.get(f"{base}/trace", headers=auth_headers)
    if r.status_code == 200:
        texte = json.dumps(r.json(), ensure_ascii=False)
        assert "Unité 101 (3.5)" in texte
    r = client.get(f"{base}/pdf", headers=auth_headers)
    assert r.status_code == 200, r.text
