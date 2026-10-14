"""Smoke — Signature (Gestion d'entreprise), retours Phil 2026-10-07 :

1. corriger le courriel d'un signataire et lui renvoyer SANS annuler le
   document (le PATCH plantait en 500 : ``EsignDocumentStatus.DRAFT``
   n'existait pas) — nouveau lien envoyé, l'ancien désactivé ;
   renvoi individuel à un signataire ;
2. supprimer un document en cours en un geste (avant : 409 « Annulez
   d'abord ») ; un document signé reste protégé ;
3. banque de contacts : partenaires/actionnaires des entreprises et
   signataires passés inclus ; une fiche employé masquée ne cache plus
   le compte au même courriel ; contact mémorisé depuis un modèle.
"""
from __future__ import annotations

import io

import pytest
from sqlalchemy import select, update

from app.models.contact_hide import ContactHide
from app.models.employe import Employe
from app.models.entreprise import Entreprise, EntreprisePartner
from app.models.esign import EsignDocument, EsignSigner
from app.models.user import User

from tests.smoke.conftest import TestSessionLocal


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
    monkeypatch.setattr("app.services.esign_send.get_mailer", lambda: fake)
    return fake


def _pdf_bytes() -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Document de test — signature")
    c.showPage()
    c.save()
    return buf.getvalue()


def _token(run, signer_id: int) -> str | None:
    async def _q():
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(EsignSigner.signature_token).where(EsignSigner.id == signer_id)
                )
            ).scalar_one()

    return run(_q())


def _creer_doc_envoye(client, h, *, n=2, ordre=False, titre="Contrat test") -> int:
    r = client.post(
        "/api/v1/esign/documents",
        headers=h,
        files={"file": ("test.pdf", _pdf_bytes(), "application/pdf")},
        data={"title": titre},
    )
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    signers = []
    for i in range(n):
        r = client.post(
            f"/api/v1/esign/documents/{doc_id}/signers",
            headers=h,
            json={
                "first_name": f"Signataire{i}",
                "last_name": "Test",
                "email": f"sig{i}-doc{doc_id}@example.com",
                "order_index": i,
            },
        )
        assert r.status_code == 201, r.text
        signers.append(r.json())
    if ordre:
        r = client.patch(
            f"/api/v1/esign/documents/{doc_id}", headers=h, json={"use_signing_order": True}
        )
        assert r.status_code == 200, r.text
    champs = [
        {
            "signer_id": sg["id"], "kind": "signature", "page": 1,
            "x": 0.1, "y": 0.1 + 0.2 * i, "w": 0.3, "h": 0.08,
        }
        for i, sg in enumerate(signers)
    ]
    r = client.put(f"/api/v1/esign/documents/{doc_id}/fields", headers=h, json=champs)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/esign/documents/{doc_id}/send", headers=h)
    assert r.status_code == 200, r.text
    return doc_id


def test_corriger_courriel_apres_envoi(client, auth_headers, mailer, run):
    doc_id = _creer_doc_envoye(client, auth_headers)
    d = client.get(f"/api/v1/esign/documents/{doc_id}", headers=auth_headers).json()
    s0 = d["signers"][0]
    ancien = _token(run, s0["id"])
    assert ancien
    # L'ancien lien fonctionne (et compte une ouverture).
    assert client.get(f"/api/v1/public/esign/{ancien}").status_code == 200
    n_avant = len(mailer.sent)

    r = client.patch(
        f"/api/v1/esign/signers/{s0['id']}",
        headers=auth_headers,
        json={"email": "Bonne.Adresse@example.com", "first_name": "Prénom-Corrigé"},
    )
    assert r.status_code == 200, r.text  # avant : 500
    body = r.json()
    assert body["email"] == "bonne.adresse@example.com"
    assert body["first_name"] == "Prénom-Corrigé"
    # Ouverture par la mauvaise adresse effacée du suivi.
    assert body["open_count"] == 0 and body["opened_at"] is None
    # Nouvelle invitation à la nouvelle adresse, sans annuler le document.
    assert len(mailer.sent) == n_avant + 1
    assert mailer.sent[-1]["to"] == ["bonne.adresse@example.com"]
    nouveau = _token(run, s0["id"])
    assert nouveau and nouveau != ancien
    assert f"/esign/{nouveau}" in mailer.sent[-1]["html_body"]
    # L'ancien lien est mort, le nouveau vit, le document reste en cours.
    assert client.get(f"/api/v1/public/esign/{ancien}").status_code == 404
    assert client.get(f"/api/v1/public/esign/{nouveau}").status_code == 200
    d = client.get(f"/api/v1/esign/documents/{doc_id}", headers=auth_headers).json()
    assert d["status"] == "envoye"
    assert any(e["type"] == "signer_email_change" for e in d["events"])

    # L'ordre et le SMS restent verrouillés après l'envoi : 409, pas 500.
    r = client.patch(
        f"/api/v1/esign/signers/{s0['id']}", headers=auth_headers, json={"order_index": 1}
    )
    assert r.status_code == 409, r.text
    # Même courriel qu'avant → rien à renvoyer.
    n = len(mailer.sent)
    r = client.patch(
        f"/api/v1/esign/signers/{s0['id']}",
        headers=auth_headers,
        json={"email": "bonne.adresse@example.com"},
    )
    assert r.status_code == 200 and len(mailer.sent) == n


def test_envoi_echoue_ne_modifie_rien(client, auth_headers, mailer, run):
    doc_id = _creer_doc_envoye(client, auth_headers, n=1)
    d = client.get(f"/api/v1/esign/documents/{doc_id}", headers=auth_headers).json()
    s0 = d["signers"][0]
    ancien = _token(run, s0["id"])
    mailer.ready = False  # mailer non configuré → EsignSendError
    r = client.patch(
        f"/api/v1/esign/signers/{s0['id']}",
        headers=auth_headers,
        json={"email": "autre@example.com"},
    )
    assert r.status_code == 502, r.text
    assert "NON modifié" in r.json()["detail"]
    d = client.get(f"/api/v1/esign/documents/{doc_id}", headers=auth_headers).json()
    assert d["signers"][0]["email"] == s0["email"]
    assert _token(run, s0["id"]) == ancien


def test_renvoi_individuel_respecte_l_ordre(client, auth_headers, mailer, run):
    doc_id = _creer_doc_envoye(client, auth_headers, ordre=True)
    d = client.get(f"/api/v1/esign/documents/{doc_id}", headers=auth_headers).json()
    s0, s1 = d["signers"]
    # Le 2e n'est pas encore à son tour.
    r = client.post(f"/api/v1/esign/signers/{s1['id']}/resend", headers=auth_headers)
    assert r.status_code == 409, r.text
    n = len(mailer.sent)
    r = client.post(f"/api/v1/esign/signers/{s0['id']}/resend", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["sent"] == 1
    assert len(mailer.sent) == n + 1
    assert mailer.sent[-1]["to"] == [s0["email"]]
    assert mailer.sent[-1]["subject"].startswith("Rappel")
    d = client.get(f"/api/v1/esign/documents/{doc_id}", headers=auth_headers).json()
    assert any(
        e["type"] == "relance" and "renvoi individuel" in (e.get("detail") or "")
        for e in d["events"]
    )


def test_supprimer_document_en_cours_mais_pas_signe(client, auth_headers, mailer, run):
    doc_id = _creer_doc_envoye(client, auth_headers, n=1)
    d = client.get(f"/api/v1/esign/documents/{doc_id}", headers=auth_headers).json()
    token = _token(run, d["signers"][0]["id"])
    r = client.delete(f"/api/v1/esign/documents/{doc_id}", headers=auth_headers)
    assert r.status_code == 204, r.text  # avant : 409 « Annulez d'abord »
    assert client.get(f"/api/v1/esign/documents/{doc_id}", headers=auth_headers).status_code == 404
    assert client.get(f"/api/v1/public/esign/{token}").status_code == 404

    # Refusé / expiré : suppression possible aussi.
    for statut in ("refuse", "expire", "annule"):
        did = _creer_doc_envoye(client, auth_headers, n=1, titre=f"Doc {statut}")

        async def _set(did=did, statut=statut):
            async with TestSessionLocal() as s:
                await s.execute(
                    update(EsignDocument).where(EsignDocument.id == did).values(status=statut)
                )
                await s.commit()

        run(_set())
        assert client.delete(f"/api/v1/esign/documents/{did}", headers=auth_headers).status_code == 204

    # Signé = pièce probante : refus explicite.
    did = _creer_doc_envoye(client, auth_headers, n=1, titre="Doc signé")

    async def _complete():
        async with TestSessionLocal() as s:
            await s.execute(
                update(EsignDocument).where(EsignDocument.id == did).values(status="complete")
            )
            await s.commit()

    run(_complete())
    r = client.delete(f"/api/v1/esign/documents/{did}", headers=auth_headers)
    assert r.status_code == 409 and "probante" in r.json()["detail"]


def test_banque_contacts_partenaires_signataires_masques(client, auth_headers, mailer, run):
    doc_id = _creer_doc_envoye(client, auth_headers, n=1)

    async def _seed():
        async with TestSessionLocal() as s:
            ent = Entreprise(name="INC Banque Contacts")
            s.add(ent)
            await s.flush()
            # Partenaire/actionnaire sans fiche employé ni compte.
            s.add(
                EntreprisePartner(
                    entreprise_id=ent.id,
                    partner_name="Steven Banque",
                    partner_email="Steven.Banque@example.com",
                    role="associe",
                )
            )
            # Compagnie actionnaire : pas un signataire.
            s.add(
                EntreprisePartner(
                    entreprise_id=ent.id,
                    partner_name="Gestion Morale inc.",
                    partner_email="morale.banque@example.com",
                    is_personne_morale=True,
                )
            )
            # Fiche employé MASQUÉE + compte portail au même courriel.
            e = Employe(full_name="Masqué Employé", email="masque.banque@example.com", active=True)
            s.add(e)
            await s.flush()
            s.add(ContactHide(source="employe", source_id=e.id))
            s.add(
                User(
                    email="masque.banque@example.com",
                    hashed_password="x",
                    is_active=True,
                    is_admin=False,
                    role="employee",
                    first_name="Masqué",
                    last_name="Compte",
                )
            )
            # Signataire d'un vieux document, jamais passé par la banque.
            s.add(
                EsignSigner(
                    document_id=doc_id,
                    order_index=5,
                    first_name="Ancien",
                    last_name="Signataire",
                    email="ancien.signataire@example.com",
                )
            )
            await s.commit()

    run(_seed())
    r = client.get("/api/v1/contacts/all", headers=auth_headers)
    assert r.status_code == 200, r.text
    par_email = {c["email"].lower(): c for c in r.json() if c.get("email")}
    assert len([c for c in r.json() if (c.get("email") or "").lower() == "steven.banque@example.com"]) == 1
    p = par_email["steven.banque@example.com"]
    assert p["source"] == "entreprise_partner" and p["full_name"] == "Steven Banque"
    assert p["company"] == "INC Banque Contacts" and p["kind"] == "partner"
    assert "morale.banque@example.com" not in par_email
    # Bug : masquer la fiche employé faisait disparaître le compte aussi.
    m = par_email["masque.banque@example.com"]
    assert m["source"] == "user" and m["full_name"] == "Masqué Compte"
    # Signataire saisi à la main → contacts ; vieux signataire → esign_signer.
    assert par_email[f"sig0-doc{doc_id}@example.com"]["source"] == "contact"
    a = par_email["ancien.signataire@example.com"]
    assert a["source"] == "esign_signer" and a["kind"] == "signer"
    assert a["detail_url"] == f"/entreprises/signature/{doc_id}"
