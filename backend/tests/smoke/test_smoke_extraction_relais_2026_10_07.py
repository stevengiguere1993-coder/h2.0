"""Smoke — extraction IA des fiches Prospection (Phil 2026-10-07 : « le
OCR semble moins bien fonctionner… il a rien trouvé »).

Causes en prod : quota quotidien gratuit Gemini épuisé (20 req/jour sur
gemini-2.5-flash, partagées par tout Kratos), modèles de secours retirés
par Google (404), Tesseract absent du serveur, diagnostic trompeur.

Vérifie : catalogue Gemini à chaud (modèles retirés ignorés), quota
quotidien sans retry, relais Groq (texte + images), alertes OCR
seulement quand l'IA n'a rien lu, endpoint extraction-health joignable.
"""
from __future__ import annotations

import asyncio
import io

from app.core.config import settings
from app.services import lead_extraction as ex


FAKE_CATALOGUE = [
    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3-flash-preview", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.1-pro", "supportedGenerationMethods": ["generateContent"]},
    # Exclus : image, TTS, embeddings, live, modèle sans generateContent.
    {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-2.5-flash-live-001", "supportedGenerationMethods": ["bidiGenerateContent"]},
    {"name": "models/gemini-2.0-flash-thinking-exp", "supportedGenerationMethods": ["generateContent"]},
]


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_catalogue_gemini_classe_et_filtre():
    noms = ex.modeles_gemini_utilisables(FAKE_CATALOGUE)
    # Stables d'abord, génération la plus récente d'abord, flash > lite > pro.
    assert noms == [
        "gemini-3.1-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-3-flash-preview",
    ]


def test_cascade_resolue_ignore_les_modeles_retires(monkeypatch):
    async def _fake_list(_key):
        return FAKE_CATALOGUE

    monkeypatch.setattr(ex, "_gemini_list_models", _fake_list)
    monkeypatch.setattr(settings, "gemini_api_key", "cle-test")
    # Préférences avec un modèle retiré (gemini-2.0-flash) : ignoré.
    monkeypatch.setattr(settings, "gemini_model_cascade", "gemini-2.5-flash,gemini-2.0-flash")
    cascade = asyncio.run(ex.resolve_gemini_cascade())
    assert cascade[0] == "gemini-2.5-flash"
    assert "gemini-2.0-flash" not in cascade
    assert cascade == [
        "gemini-2.5-flash",
        "gemini-3.1-pro",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-3-flash-preview",
    ]

    # Sans catalogue (réseau, clé) → préférences telles quelles.
    async def _fake_none(_key):
        return None

    monkeypatch.setattr(ex, "_gemini_list_models", _fake_none)
    assert asyncio.run(ex.resolve_gemini_cascade()) == ["gemini-2.5-flash", "gemini-2.0-flash"]

    # Préférences vides (défaut) → ordre du catalogue, génération la plus
    # récente d'abord (en prod : gemini-3.8-flash avant 2.5-flash).
    monkeypatch.setattr(settings, "gemini_model_cascade", "")
    monkeypatch.setattr(ex, "_gemini_list_models", _fake_list)
    assert asyncio.run(ex.resolve_gemini_cascade()) == [
        "gemini-3.1-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-3-flash-preview",
    ]
    # Ni préférences ni catalogue → liste de secours.
    monkeypatch.setattr(ex, "_gemini_list_models", _fake_none)
    assert asyncio.run(ex.resolve_gemini_cascade()) == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]


def test_quota_journalier_detecte():
    corps_jour = (
        '{"error": {"code": 429, "message": "You exceeded your current quota", '
        '"details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}, '
        '{"retryDelay": "29209s"}]}}'
    )
    assert ex._quota_est_journalier(corps_jour) is True
    assert ex._quota_est_journalier('{"details": [{"retryDelay": "12s"}]}') is False
    assert ex._quota_est_journalier("rate limit per minute") is False


def test_cascade_sans_retry_sur_quota_journalier(monkeypatch):
    # Budget court : pas de nouvel essai (3 s) sur le 503 du dernier modèle,
    # on ne teste ici que le quota quotidien et le modèle retiré.
    ex._GEMINI_PENALITES.clear()
    monkeypatch.setattr(ex, "_GEMINI_BUDGET_S", 1.0)
    appels: list = []

    async def _fake_extract(material, images, model=None, system=None, guide=None):
        appels.append(model)
        if model == "gemini-2.5-flash":
            return None, "quota quotidien gratuit atteint", True, False
        if model == "gemini-2.5-pro":
            return None, "modèle Gemini « gemini-2.5-pro » déprécié", False, True
        return None, "erreur Gemini HTTP 503", False, False

    async def _fake_cascade(_key=None):
        return ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"]

    monkeypatch.setattr(ex, "_gemini_extract", _fake_extract)
    monkeypatch.setattr(ex, "resolve_gemini_cascade", _fake_cascade)
    monkeypatch.setattr(settings, "gemini_api_key", "cle-test")
    data, raison, modele = asyncio.run(ex._gemini_extract_cascade("texte", []))
    assert data is None and modele is None
    # Un seul appel par modèle (pas de 1 s / 5 s / 30 s sur un quota du jour).
    assert appels == ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"]
    # Une raison PAR modèle — la vraie cause (quota) n'est plus cachée.
    assert "gemini-2.5-flash : quota quotidien gratuit atteint" in raison
    assert "gemini-2.5-pro : retiré par Google" in raison
    assert "gemini-2.5-flash-lite : erreur Gemini HTTP 503" in raison


def test_sortie_groq_normalisee():
    out = ex._normaliser_sortie_groq(
        {"immeubles": [{"address": "1 rue A", "typology_json": '{"4.5": 6}', "energie": None}]}
    )
    assert out == [{"address": "1 rue A", "typology": {"4.5": 6}}]
    assert ex._normaliser_sortie_groq({"asking_price": 1000000, "city": ""}) == [{"asking_price": 1000000}]
    assert ex._normaliser_sortie_groq("n'importe quoi") == []


def test_modeles_groq_choisis(monkeypatch):
    monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "groq_vision_model", "meta-llama/llama-4-scout-17b-16e-instruct")
    catalogue = ["llama-3.1-8b-instant", "meta-llama/llama-4-maverick-17b-128e-instruct", "llama-3.3-70b-versatile"]
    assert ex._groq_modele_texte(catalogue) == "llama-3.3-70b-versatile"
    # Scout absent → Maverick (Llama 4) pris pour les images.
    assert ex._groq_modele_vision(catalogue) == "meta-llama/llama-4-maverick-17b-128e-instruct"
    assert ex._groq_modele_vision(["llama-3.3-70b-versatile"]) is None
    # Catalogue inconnu → modèles configurés.
    assert ex._groq_modele_texte(None) == "llama-3.3-70b-versatile"

    # Catalogue Groq tel qu'observé en prod le 2026-10-07 : plus aucun
    # Llama. Défauts vides → gpt-oss-120b pour le texte, rien pour la vision.
    monkeypatch.setattr(settings, "groq_model", "")
    monkeypatch.setattr(settings, "groq_vision_model", "")
    prod = [
        "openai/gpt-oss-120b", "openai/gpt-oss-20b", "canopylabs/orpheus-arabic-saudi",
        "allam-2-7b", "meta-llama/llama-prompt-guard-2-86m", "qwen/qwen3.8-27b",
        "openai/gpt-oss-safeguard-20b", "whisper-large-v3", "whisper-large-v3-turbo",
    ]
    assert ex._groq_modele_texte(prod) == "openai/gpt-oss-120b"
    assert ex._groq_modele_vision(prod) is None
    # Modèle configuré disparu du catalogue → préférences.
    monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
    assert ex._groq_modele_texte(prod) == "openai/gpt-oss-120b"
    assert ex._groq_modele_texte(None) == "llama-3.3-70b-versatile"
    # Un modèle vision apparaît → pris.
    assert ex._groq_modele_vision(prod + ["qwen/qwen3-vl-32b"]) == "qwen/qwen3-vl-32b"


def test_json_lenient():
    assert ex._json_lenient('{"a": 1}') == {"a": 1}
    assert ex._json_lenient('```json\n{"a": 1}\n```') == {"a": 1}
    assert ex._json_lenient('Voici : {"unites": [{"loyer_actuel": 900}]} merci') == {"unites": [{"loyer_actuel": 900}]}
    try:
        ex._json_lenient("rien")
    except ValueError:
        pass
    else:
        raise AssertionError("ValueError attendue")


def test_relais_groq_quand_gemini_a_sec(monkeypatch):
    async def _gemini_ko(material, images, *, system=None, guide=None, **kw):
        return None, "cascade épuisée — gemini-2.5-flash : quota quotidien gratuit atteint", None

    async def _groq_ok(material, images, *, system=None, guide=None):
        return (
            [{"address": "123 rue Test", "city": "Montréal", "asking_price": 1500000,
              "nb_logements": 8, "typology": {"4.5": 8}}],
            None,
            "llama-3.3-70b-versatile",
        )

    monkeypatch.setattr(ex, "_gemini_extract_cascade", _gemini_ko)
    monkeypatch.setattr(ex, "_groq_extract", _groq_ok)
    res = asyncio.run(ex.extract_lead_info(text="Immeuble à vendre, 8 logements. Prix demandé : 1 500 000 $."))
    assert res.data and res.data[0]["asking_price"] == 1500000
    assert res.data[0]["address"] == "123 rue Test"
    assert "groq" in res.model_used and "gemini" not in res.model_used
    assert any("relais pris par Groq" in w for w in res.warnings)
    # Pas d'alerte « Tesseract » : l'IA a répondu.
    assert not any("Tesseract" in w for w in res.warnings)


def test_image_lue_par_ia_sans_alerte_ocr(monkeypatch):
    async def _gemini_ok(material, images, *, system=None, guide=None, **kw):
        assert images and images[0][0] == "image/png"
        return [{"address": "456 rue Photo", "asking_price": 2000000}], None, "gemini-2.5-flash"

    monkeypatch.setattr(ex, "_gemini_extract_cascade", _gemini_ok)
    monkeypatch.setattr(ex, "parse_image_ocr", lambda blob, filename="image": "")
    res = asyncio.run(ex.extract_lead_info(files=[("fiche.png", "image/png", _png())]))
    assert res.data and res.data[0]["asking_price"] == 2000000
    assert res.model_used == "gemini"
    assert not any("Tesseract" in w or "OCR" in w for w in res.warnings)


def test_ia_muette_alerte_quota_et_ocr(monkeypatch):
    async def _gemini_ko(material, images, *, system=None, guide=None, **kw):
        return None, "cascade épuisée — gemini-2.5-flash : quota quotidien gratuit atteint", None

    async def _groq_ko(material, images, *, system=None, guide=None):
        return None, "quota Groq atteint", "llama-3.3-70b-versatile"

    monkeypatch.setattr(ex, "_gemini_extract_cascade", _gemini_ko)
    monkeypatch.setattr(ex, "_groq_extract", _groq_ko)
    monkeypatch.setattr(ex, "parse_image_ocr", lambda blob, filename="image": "")
    res = asyncio.run(ex.extract_lead_info(files=[("fiche.png", "image/png", _png())]))
    assert res.data == [] and res.model_used == "none"
    texte = " ".join(res.warnings)
    assert "quota quotidien gratuit atteint" in texte
    assert "relais Groq impossible" in texte
    assert "facturation" in texte
    assert "Tesseract" in texte  # l'état OCR n'est utile que maintenant


def test_pdf_scanne_transmis_a_l_ia(monkeypatch):
    recu: dict = {}

    async def _gemini_ok(material, images, *, system=None, guide=None, **kw):
        recu["images"] = images
        return [{"asking_price": 900000}], None, "gemini-2.5-flash"

    monkeypatch.setattr(ex, "_gemini_extract_cascade", _gemini_ok)
    monkeypatch.setattr(ex, "parse_pdf", lambda blob: "")
    monkeypatch.setattr(ex, "parse_pdf_ocr", lambda blob, filename="pdf": "")
    res = asyncio.run(ex.extract_lead_info(files=[("scan.pdf", "application/pdf", b"%PDF-1.4 faux")]))
    assert recu["images"] == [("application/pdf", b"%PDF-1.4 faux")]
    assert res.data and res.data[0]["asking_price"] == 900000


def test_extraction_health_joignable(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)
    monkeypatch.setattr(settings, "groq_api_key", None)
    r = client.get("/api/v1/lead-analyses/extraction-health", headers=auth_headers)
    assert r.status_code == 200, r.text  # avant : /ocr-health → 422
    body = r.json()
    assert body["gemini"]["cle"] is False and body["gemini"]["cascade"] == []
    assert body["groq"]["cle"] is False
    assert "installed" in body["ocr"]
