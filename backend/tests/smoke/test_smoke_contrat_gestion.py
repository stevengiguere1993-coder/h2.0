"""Smoke — Contrat de gestion (onglet fiche immeuble + signature en ligne).

Couvre le parcours complet côté API (sans courriel réel) :
- création auto-remplie d'un brouillon depuis un immeuble,
- édition des champs + rendu du corps (placeholders substitués),
- aperçu PDF (reportlab),
- gabarit : lecture + garde admin sur l'édition,
- signature publique par token → statut « signe » + PDF signé.
"""
import secrets

from sqlalchemy import select

from app.models.contrat_gestion import ContratGestion, ContratGestionStatus
from app.models.immobilier import Immeuble

from tests.smoke.conftest import TestSessionLocal


def _mk_immeuble(run) -> int:
    async def _create():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Test Immeuble CG",
                address="123 Rue de la Convention",
                city="Montréal",
                postal_code="H2X 1Y4",
            )
            s.add(imm)
            await s.commit()
            await s.refresh(imm)
            return imm.id

    return run(_create())


def test_create_autofill_and_body(client, auth_headers, run):
    immeuble_id = _mk_immeuble(run)
    resp = client.post(
        "/api/v1/contrats-gestion",
        headers=auth_headers,
        json={"immeuble_id": immeuble_id},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == ContratGestionStatus.BROUILLON.value
    # Auto-remplissage : l'adresse de l'immeuble courant.
    assert "123 Rue de la Convention" in (body["immeubles_adresses"] or "")
    assert body["lieu_signature"] == "Montréal"
    # Le corps rendu contient le contrat + l'adresse substituée.
    assert "CONVENTION DE GESTION" in body["body_markdown"]
    assert "123 Rue de la Convention" in body["body_markdown"]

    contrat_id = body["id"]
    # Édition des champs → reflétés dans le corps.
    patch = client.patch(
        f"/api/v1/contrats-gestion/{contrat_id}",
        headers=auth_headers,
        json={
            "mandant_courriel": "proprio@example.com",
            "representant_nom": "Marie Tremblay",
            "district_judiciaire": "Montréal",
            "compagnie": "9999-8888 Québec inc.",
        },
    )
    assert patch.status_code == 200, patch.text
    pbody = patch.json()
    assert "9999-8888 Québec inc." in pbody["body_markdown"]
    assert "proprio@example.com" in pbody["body_markdown"]

    # Liste par immeuble.
    lst = client.get(
        f"/api/v1/contrats-gestion?immeuble_id={immeuble_id}",
        headers=auth_headers,
    )
    assert lst.status_code == 200
    assert any(c["id"] == contrat_id for c in lst.json())

    # Aperçu PDF.
    pdf = client.get(
        f"/api/v1/contrats-gestion/{contrat_id}/pdf", headers=auth_headers
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:4] == b"%PDF"


def test_template_read_and_admin_guard(client, auth_headers, employee_headers):
    got = client.get("/api/v1/contrats-gestion/template", headers=auth_headers)
    assert got.status_code == 200
    assert "CONVENTION DE GESTION" in got.json()["corps_markdown"]

    # Édition réservée admin+ : un employé → 403.
    denied = client.request(
        "PUT",
        "/api/v1/contrats-gestion/template",
        headers=employee_headers,
        json={"corps_markdown": got.json()["corps_markdown"] + "\n\nAjout test."},
    )
    assert denied.status_code == 403, denied.text

    # Admin → 200.
    ok = client.request(
        "PUT",
        "/api/v1/contrats-gestion/template",
        headers=auth_headers,
        json={"corps_markdown": got.json()["corps_markdown"] + "\n\nAjout test."},
    )
    assert ok.status_code == 200, ok.text
    assert "Ajout test." in ok.json()["corps_markdown"]


def test_public_sign_flow(client, auth_headers, run):
    immeuble_id = _mk_immeuble(run)
    created = client.post(
        "/api/v1/contrats-gestion",
        headers=auth_headers,
        json={"immeuble_id": immeuble_id},
    ).json()
    contrat_id = created["id"]

    # Simule l'envoi : pose un token (sans dépendre de Microsoft Graph).
    token = secrets.token_urlsafe(24)

    async def _set_token():
        async with TestSessionLocal() as s:
            c = (
                await s.execute(
                    select(ContratGestion).where(ContratGestion.id == contrat_id)
                )
            ).scalar_one()
            c.signature_token = token
            c.status = ContratGestionStatus.ENVOYE.value
            await s.commit()

    run(_set_token())

    # Page publique : consultable via token.
    pub = client.get(f"/api/v1/public/contrats-gestion/{token}")
    assert pub.status_code == 200, pub.text
    assert "CONVENTION DE GESTION" in pub.json()["body_markdown"]

    # Signature.
    signed = client.post(
        f"/api/v1/public/contrats-gestion/{token}/sign",
        json={"signed_name": "Marie Tremblay", "checkbox_confirmed": True},
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == ContratGestionStatus.SIGNE.value
    assert signed.json()["signed_name"] == "Marie Tremblay"

    # Re-signer est refusé.
    again = client.post(
        f"/api/v1/public/contrats-gestion/{token}/sign",
        json={"signed_name": "Autre"},
    )
    assert again.status_code == 409

    # PDF signé récupérable côté admin.
    spdf = client.get(
        f"/api/v1/contrats-gestion/{contrat_id}/signed-pdf", headers=auth_headers
    )
    assert spdf.status_code == 200, spdf.text
    assert spdf.content[:4] == b"%PDF"
