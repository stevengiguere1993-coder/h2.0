"""Smoke — signature guidée (Phil 2026-11-13, « comme c'est fait par Authentisign »).

À l'écran, chaque endroit à signer se clique ; le signataire trace sa signature et ses initiales
une seule fois. Côté serveur, une seule règle nouvelle : un endroit FACULTATIF que le signataire
n'a pas cliqué ne reçoit ni signature ni initiales dans le PDF final. Un endroit obligatoire
reste toujours signé, même si la page le déclarait sauté.
"""
from __future__ import annotations

import base64
import hashlib
import io
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from app.integrations.tal import client as tal_client
from app.models.esign import EsignDocument, EsignField, EsignSigner
from app.services import esign_pdf
from tests.smoke.conftest import TestSessionLocal


def _png() -> str:
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (240, 80), (0, 0, 0, 0))
    ImageDraw.Draw(img).line([(10, 60), (90, 15), (150, 55), (230, 20)], fill=(10, 10, 60, 255), width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _document(run, *, champs: list[tuple[str, bool]]) -> tuple[int, str, list[int]]:
    """Document envoyé à un seul signataire, avec les zones demandées (genre, obligatoire)."""

    async def _creer():
        async with TestSessionLocal() as s:
            pdf = tal_client.pdf_simulation({}, "SIM-guidee")
            doc = EsignDocument(
                title="Contrat à signer", status="envoye", use_signing_order=False, filename="contrat.pdf",
                content_type="application/pdf", pdf_blob=pdf, page_count=4, sha256=hashlib.sha256(pdf).hexdigest(),
            )
            doc.sent_at = datetime.now(timezone.utc)
            s.add(doc)
            await s.flush()
            signataire = EsignSigner(document_id=doc.id, order_index=0, first_name="Julie", last_name="Roy",
                                     email="julie.roy@contrat-guide.ca", require_sms_auth=False)
            signataire.signature_token = secrets.token_urlsafe(24)
            signataire.sent_at = datetime.now(timezone.utc)
            s.add(signataire)
            await s.flush()
            ids = []
            for i, (genre, requis) in enumerate(champs):
                f = EsignField(document_id=doc.id, signer_id=signataire.id, kind=genre, page=1, x=0.1, y=0.1 + 0.05 * i,
                               w=0.2, h=0.03, required=requis)
                s.add(f)
                await s.flush()
                ids.append(f.id)
            await s.commit()
            return doc.id, signataire.signature_token, ids

    return run(_creer())


def _zones(run, doc_id: int) -> dict[int, tuple[str, str | None]]:
    async def _lire():
        async with TestSessionLocal() as s:
            rows = (await s.execute(select(EsignField).where(EsignField.document_id == doc_id))).scalars().all()
            return {f.id: (f.kind, f.value_text) for f in rows}

    return run(_lire())


def test_endroit_facultatif_non_clique_reste_vide(client, run, monkeypatch):
    doc_id, jeton, (sig, ini_facultatif, sig_facultative, date) = _document(
        run, champs=[("signature", True), ("initiales", False), ("signature", False), ("date", True)])
    tamponnes: list[int] = []
    origine = esign_pdf._draw_field

    def _espion(c, field, signer, page_w, page_h):
        if field.kind in ("signature", "initiales") and (field.value_text or "") != "non":
            tamponnes.append(field.id)
        return origine(c, field, signer, page_w, page_h)

    monkeypatch.setattr(esign_pdf, "_draw_field", _espion)
    # Le signataire a cliqué sa signature obligatoire seulement ; aucun tracé d'initiales n'est fourni.
    r = client.post(f"/api/v1/public/esign/{jeton}/sign", json={
        "signature_data_url": _png(), "consent": True,
        # La page déclare sautés les deux endroits facultatifs… et, à tort, l'obligatoire.
        "skipped_field_ids": [ini_facultatif, sig_facultative, sig],
    })
    assert r.status_code == 200, r.text
    assert r.json()["completed"] is True
    z = _zones(run, doc_id)
    assert z[ini_facultatif] == ("initiales", "non") and z[sig_facultative] == ("signature", "non")
    assert z[sig] == ("signature", None), "un endroit obligatoire reste signé"
    assert z[date][1], "la date se pose seule"
    assert tamponnes == [sig], "seul l'endroit cliqué est tamponné dans le PDF final"


def test_sans_declaration_tout_est_signe_comme_avant(client, run):
    doc_id, jeton, (sig, ini_facultatif) = _document(run, champs=[("signature", True), ("initiales", False)])
    # Ancienne page (ou appel direct) : rien n'est déclaré sauté → les initiales sont exigées et posées.
    r = client.post(f"/api/v1/public/esign/{jeton}/sign", json={"signature_data_url": _png(), "consent": True})
    assert r.status_code == 422 and "Initiales" in r.json()["detail"]
    r = client.post(f"/api/v1/public/esign/{jeton}/sign",
                    json={"signature_data_url": _png(), "initials_data_url": _png(), "consent": True})
    assert r.status_code == 200, r.text
    z = _zones(run, doc_id)
    assert z[sig][1] is None and z[ini_facultatif][1] is None


def test_endroit_obligatoire_exige_toujours_le_trace(client, run):
    _doc_id, jeton, (sig,) = _document(run, champs=[("signature", True)])
    r = client.post(f"/api/v1/public/esign/{jeton}/sign", json={"consent": True, "skipped_field_ids": [sig]})
    assert r.status_code == 422 and "Signature" in r.json()["detail"]
