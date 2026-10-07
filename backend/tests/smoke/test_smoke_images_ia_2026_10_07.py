"""Smoke — photos lourdes et modèle saturé (Phil 2026-10-07, capture
« Regarde cette erreur ») : gemini-3.8-flash en 503 après avoir épuisé le
budget de temps → les autres modèles « non essayés » ; relais Groq en 413
(photo trop lourde)."""
from __future__ import annotations

import asyncio
import io

from app.core.config import settings
from app.services import lead_extraction as ex
from app.services import lead_rent_roll as rr


def _png(taille: int, couleur=(255, 255, 255)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (taille, taille), couleur).save(buf, format="PNG")
    return buf.getvalue()


def test_photo_lourde_reduite_avant_l_ia():
    from PIL import Image

    grosse = _png(4000)
    mime, data = ex.preparer_image_pour_ia("image/png", grosse)
    assert mime == "image/jpeg" and len(data) < len(grosse)
    img = Image.open(io.BytesIO(data))
    assert max(img.size) <= 2000
    # Petite image : inchangée.
    petite = _png(64)
    assert ex.preparer_image_pour_ia("image/png", petite) == ("image/png", petite)
    # Contenu illisible : originale renvoyée, pas d'exception.
    assert ex.preparer_image_pour_ia("image/png", b"pas une image") == ("image/png", b"pas une image")


def test_pipeline_envoie_la_photo_reduite(monkeypatch):
    recu: dict = {}

    async def _gemini_ok(material, images, *, system=None, guide=None):
        recu["images"] = images
        return [{"asking_price": 1}], None, "gemini-3.8-flash"

    monkeypatch.setattr(ex, "_gemini_extract_cascade", _gemini_ok)
    monkeypatch.setattr(ex, "parse_image_ocr", lambda blob, filename="image": "")
    grosse = _png(4000)
    res = asyncio.run(ex.extract_lead_info(files=[("photo.png", "image/png", grosse)]))
    assert res.data
    mime, data = recu["images"][0]
    assert mime == "image/jpeg" and len(data) < len(grosse)

    # Rent roll : même réduction.
    async def _gemini_rr(material, images, *, system=None, guide=None):
        recu["rr"] = images
        return [{"unites": [{"numero": "1", "typo": "4.5", "loyer_actuel": 900}]}], None, "gemini-3.8-flash"

    monkeypatch.setattr(ex, "_run_gemini_safely", _gemini_rr)
    asyncio.run(rr.extraire_rent_roll(files=[("rr.png", "image/png", grosse)]))
    assert recu["rr"][0][0] == "image/jpeg" and len(recu["rr"][0][1]) < len(grosse)


def test_modele_sature_puis_suivant_toujours_essaye(monkeypatch):
    """503 sur le premier modèle : un nouvel essai après 3 s, puis le
    deuxième modèle est essayé même si le budget est dépassé."""
    monkeypatch.setattr(ex, "_GEMINI_BUDGET_S", 0.2)
    monkeypatch.setattr(settings, "gemini_api_key", "cle-test")
    appels: list = []

    async def _extract(material, images, model=None, system=None, guide=None):
        appels.append(model)
        await asyncio.sleep(0.15)
        if model == "m2":
            return [{"asking_price": 2}], None, False, False
        return None, "erreur Gemini HTTP 503", False, False

    async def _cascade(_key=None):
        return ["m1", "m2", "m3"]

    monkeypatch.setattr(ex, "_gemini_extract", _extract)
    monkeypatch.setattr(ex, "resolve_gemini_cascade", _cascade)
    data, raison, modele = asyncio.run(ex._gemini_extract_cascade("texte", []))
    assert data == [{"asking_price": 2}] and modele == "m2 (cascade)"
    # Budget (0,2 s) dépassé après m1 : m2 quand même essayé (au moins deux
    # modèles) ; pas de nouvel essai sur m1 car 3 s ne tiennent pas dans
    # le budget.
    assert appels == ["m1", "m2"]


def test_erreur_transitoire_un_nouvel_essai(monkeypatch):
    monkeypatch.setattr(ex, "_GEMINI_BUDGET_S", 30.0)
    monkeypatch.setattr(settings, "gemini_api_key", "cle-test")
    monkeypatch.setattr(asyncio, "sleep", _sans_attente)
    appels: list = []

    async def _extract(material, images, model=None, system=None, guide=None):
        appels.append(model)
        if len(appels) == 1:
            return None, "erreur Gemini HTTP 503", False, False
        return [{"asking_price": 3}], None, False, False

    async def _cascade(_key=None):
        return ["m1", "m2"]

    monkeypatch.setattr(ex, "_gemini_extract", _extract)
    monkeypatch.setattr(ex, "resolve_gemini_cascade", _cascade)
    data, raison, modele = asyncio.run(ex._gemini_extract_cascade("texte", []))
    assert data == [{"asking_price": 3}]
    assert appels == ["m1", "m1"] and modele == "m1 (retry)"


async def _sans_attente(_s):
    return None
