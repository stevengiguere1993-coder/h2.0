"""Smoke — lien vers un PDF de courtier (Phil 2026-10-07,
immeublesgloria.com « Sommaire Investissement ») : le PDF est téléchargé,
lu comme un fichier joint, attaché à la fiche ; un code postal impossible
(« I0O 3O1 », lu dans des octets) n'est plus retenu."""
from __future__ import annotations

import asyncio
import io

from app.services import lead_extraction as ex

URL = "https://immeublesgloria.com/pdf/Pie-IX%206630%20-%20FR%20-%20Sommaire%20Investissement.pdf"


def _pdf_courtier() -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 760
    for ligne in (
        "Sommaire d'investissement — Rosemont",
        "Prix demandé : 2 500 000 $",
        "12 logements",
        "Revenus bruts : 150 720 $",
        "6630 boulevard Pie-IX, Montréal (Québec) H1X 2Y3",
    ):
        c.drawString(72, y, ligne)
        y -= 24
    c.showPage()
    c.save()
    return buf.getvalue()


def test_lien_pdf_detecte_et_nomme():
    assert ex._url_semble_pdf(URL) is True
    assert ex._url_semble_pdf(URL + "?dl=1") is True
    assert ex._url_semble_pdf("https://www.centris.ca/fr/plex~a-vendre~montreal") is False
    assert ex._nom_fichier_depuis_url(URL) == "Pie-IX 6630 - FR - Sommaire Investissement.pdf"
    assert ex._nom_fichier_depuis_url("https://x.com/doc") == "doc.pdf"


def test_lien_pdf_traite_comme_fichier(monkeypatch):
    pdf = _pdf_courtier()

    async def _telecharge(url):
        assert url == URL
        return pdf, None

    async def _gemini_ko(material, images, *, system=None, guide=None):
        # Le PDF (couche texte) arrive bien à l'IA comme matière.
        assert "[PDF : Pie-IX 6630 - FR - Sommaire Investissement.pdf]" in material
        return None, "clé GEMINI_API_KEY absente du serveur", None

    async def _groq_ko(material, images, *, system=None, guide=None):
        return None, "clé GROQ_API_KEY absente du serveur", None

    monkeypatch.setattr(ex, "_telecharger_pdf", _telecharge)
    monkeypatch.setattr(ex, "_run_gemini_safely", _gemini_ko)
    monkeypatch.setattr(ex, "_run_groq_safely", _groq_ko)
    res = asyncio.run(ex.extract_lead_info(urls=[URL]))
    assert res.data, res.warnings
    d = res.data[0]
    assert d["asking_price"] == 2_500_000 and d["nb_logements"] == 12
    assert d.get("postal_code") == "H1X 2Y3"
    assert [f[0] for f in res.fichiers_telecharges] == ["Pie-IX 6630 - FR - Sommaire Investissement.pdf"]
    assert res.fichiers_telecharges[0][1] == "application/pdf"
    assert not any("HTML" in w or "Cloudflare" in w for w in res.warnings)

    # Lien qui ne renvoie pas un PDF → avertissement clair, pas de plantage.
    async def _pas_pdf(url):
        return None, "le lien ne renvoie pas un PDF"

    monkeypatch.setattr(ex, "_telecharger_pdf", _pas_pdf)
    res = asyncio.run(ex.extract_lead_info(urls=[URL]))
    assert res.data == [] and any("ne renvoie pas un PDF" in w for w in res.warnings)


def test_endpoint_lien_pdf_joint_a_la_fiche(client, auth_headers, monkeypatch):
    pdf = _pdf_courtier()

    async def _telecharge(url):
        return pdf, None

    async def _gemini_ko(material, images, *, system=None, guide=None):
        return None, "clé GEMINI_API_KEY absente du serveur", None

    async def _groq_ko(material, images, *, system=None, guide=None):
        return None, "clé GROQ_API_KEY absente du serveur", None

    monkeypatch.setattr(ex, "_telecharger_pdf", _telecharge)
    monkeypatch.setattr(ex, "_run_gemini_safely", _gemini_ko)
    monkeypatch.setattr(ex, "_run_groq_safely", _groq_ko)
    r = client.post("/api/v1/lead-analyses/extract", headers=auth_headers, data={"urls": URL + "?v=2"})
    assert r.status_code == 201, r.text
    fiche = r.json()["created"][0]
    assert fiche["asking_price"] == 2_500_000 and fiche["nb_logements"] == 12
    d = client.get(f"/api/v1/lead-analyses/{fiche['id']}", headers=auth_headers).json()
    assert [a["filename"] for a in d["attachments"]] == ["Pie-IX 6630 - FR - Sommaire Investissement.pdf"]
    assert d["source_urls"] == URL + "?v=2"


def test_code_postal_impossible_ignore():
    d = ex.parse_text("123 rue Test, Montréal I0O 3O1 — Prix demandé 500 000 $ — 6 logements")
    assert "postal_code" not in d
    d = ex.parse_text("123 rue Test, Montréal H1X 2Y3 — Prix demandé 500 000 $ — 6 logements")
    assert d["postal_code"] == "H1X 2Y3"
