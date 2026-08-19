"""Smoke — valeur PROBANTE d'un document signé (audit 2026-08-19).

Deux trous trouvés dans le parcours de signature, tous deux invisibles
depuis Kratos :

1. **Le PDF ne portait aucune signature.** Seul l'avis de modification
   voyait sa page « Réponse du locataire » estampillée. Les cinq autres
   types signables — non-reconduction, reprise, travaux majeurs,
   consentement aux communications, réponse à une cession — étaient
   signés en base et archivés au Drive dans leur version VIERGE. Devant
   un tribunal, le document ne prouvait rien par lui-même.
2. **Le locataire ne recevait pas sa copie.** Le renvoi n'était câblé
   que pour l'avis de modification.

Ce test signe une REPRISE DE LOGEMENT — un des documents les plus
litigieux — et exige les deux.
"""
from __future__ import annotations

import io

import pytest
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.models.immobilier import ImmDocument, Locataire

from .conftest import TestSessionLocal


class FakeMailer:
    ready = True
    sender = "systeme@immohorizon.com"

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, **kw):
        self.sent.append(kw)


@pytest.fixture()
def mailer(monkeypatch) -> FakeMailer:
    fake = FakeMailer()
    monkeypatch.setattr(
        "app.integrations.email_graph.get_mailer", lambda: fake
    )

    async def _exp():
        return (
            "gestion@immohorizon.com",
            "Horizon — Gestion locative",
            "kyle.gestion@gmail.com",
        )

    monkeypatch.setattr(
        "app.api.v1.endpoints.immobilier_communications.expediteur_defaut",
        _exp,
    )
    return fake


def _nb_pages(pdf: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(pdf)).pages)


def _texte(pdf: bytes, page: int) -> str:
    from pypdf import PdfReader

    return PdfReader(io.BytesIO(pdf)).pages[page].extract_text() or ""


def test_reprise_signee_est_estampillee_et_renvoyee(client, run, mailer):
    from app.services.tal_officiel import page_attestation_signature

    # Un PDF d'une page tient lieu d'avis de reprise.
    doc_pdf = page_attestation_signature(
        "Avis de reprise (corps)", None, None, "2026-01-01 00:00"
    )
    tok = "tok-attest-reprise"

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            loc = Locataire(
                full_name="Reprise Testeur", email="reprise@test.local"
            )
            s.add(loc)
            await s.flush()
            d = ImmDocument(
                type="avis_reprise",
                titre="Avis de reprise du logement",
                signature_token=tok,
                locataire_id=loc.id,
                pdf_blob=doc_pdf,
            )
            s.add(d)
            await s.commit()
            return d.id

    doc_id = run(_seed())
    avant = _nb_pages(doc_pdf)

    r = client.post(
        f"/api/v1/public/documents/{tok}/signer",
        json={"name": "Reprise Testeur"},
    )
    assert r.status_code == 200, r.text

    async def _relire() -> bytes:
        async with TestSessionLocal() as s:
            d = (
                await s.execute(
                    select(ImmDocument)
                    .options(undefer(ImmDocument.pdf_blob))
                    .where(ImmDocument.id == doc_id)
                )
            ).scalar_one()
            return bytes(d.pdf_blob)

    apres = run(_relire())

    # 1) Le PDF conservé porte l'attestation en dernière page.
    assert _nb_pages(apres) == avant + 1
    derniere = _texte(apres, _nb_pages(apres) - 1)
    assert "Attestation de signature" in derniere
    assert "Reprise Testeur" in derniere
    # Le fondement légal doit y être : c'est ce qui rend la signature
    # opposable (RLRQ c. C-1.1 / art. 2827 C.c.Q.).
    assert "2827" in derniere

    # 2) Le locataire reçoit sa copie, du bon expéditeur.
    assert len(mailer.sent) == 1, mailer.sent
    envoi = mailer.sent[0]
    assert envoi["to"] == ["reprise@test.local"]
    assert envoi["from_email"] == "gestion@immohorizon.com"
    assert envoi["reply_to"] == "kyle.gestion@gmail.com"
    assert "Avis de reprise du logement" in envoi["subject"]
    assert envoi["attachments"], "la copie signée doit être jointe"


def test_document_sans_signature_ne_declenche_rien(client, run, mailer):
    """Un type SANS signature (avis d'accès) refuse la signature et
    n'envoie évidemment aucune copie — la garde ne doit pas s'être
    élargie par accident aux documents de simple information."""

    async def _seed() -> None:
        async with TestSessionLocal() as s:
            s.add(
                ImmDocument(
                    type="avis_acces",
                    titre="Avis d'accès (attestation)",
                    signature_token="tok-attest-acces",
                )
            )
            await s.commit()

    run(_seed())
    r = client.post(
        "/api/v1/public/documents/tok-attest-acces/signer",
        json={"name": "Personne"},
    )
    assert r.status_code == 400, r.text
    assert mailer.sent == []
