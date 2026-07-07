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


# Petit PNG 1x1 valide (data-URL) pour les signatures des tests.
_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M8AAAMCAoEB0nkAAAAASUVORK5CYII="
)


def _set_token(run, contrat_id: int, field: str, token: str, status_val: str):
    async def _do():
        async with TestSessionLocal() as s:
            c = (
                await s.execute(
                    select(ContratGestion).where(ContratGestion.id == contrat_id)
                )
            ).scalar_one()
            setattr(c, field, token)
            c.status = status_val
            await s.commit()

    run(_do())


def test_dual_signature_flow(client, auth_headers, run):
    immeuble_id = _mk_immeuble(run)
    created = client.post(
        "/api/v1/contrats-gestion",
        headers=auth_headers,
        json={"immeuble_id": immeuble_id},
    ).json()
    contrat_id = created["id"]
    # Le signataire MGV est pré-rempli à la création.
    assert created["mandataire_courriel"]

    client.patch(
        f"/api/v1/contrats-gestion/{contrat_id}",
        headers=auth_headers,
        json={"mandant_courriel": "proprio@example.com", "representant_nom": "Marie T."},
    )

    # ── Étape 1 : le Mandataire (MGV) signe ──
    mgv_token = secrets.token_urlsafe(24)
    _set_token(
        run, contrat_id, "mandataire_signature_token", mgv_token,
        ContratGestionStatus.ATTENTE_MGV.value,
    )
    pub = client.get(f"/api/v1/public/contrats-gestion/{mgv_token}")
    assert pub.status_code == 200, pub.text
    assert pub.json()["party"] == "mandataire"

    # Signature obligatoire : sans image → 422.
    no_sig = client.post(
        f"/api/v1/public/contrats-gestion/{mgv_token}/sign",
        json={"signed_name": "Philippe Meuser"},
    )
    assert no_sig.status_code == 422, no_sig.text

    mgv_signed = client.post(
        f"/api/v1/public/contrats-gestion/{mgv_token}/sign",
        json={"signed_name": "Philippe Meuser", "signature_image_data_url": _PNG_DATA_URL},
    )
    assert mgv_signed.status_code == 200, mgv_signed.text
    assert mgv_signed.json()["status"] == ContratGestionStatus.ATTENTE_CLIENT.value

    # ── Étape 2 : le Mandant signe (token posé directement — le relais
    # courriel dépend de Graph, absent en test) ──
    mandant_token = secrets.token_urlsafe(24)
    _set_token(
        run, contrat_id, "signature_token", mandant_token,
        ContratGestionStatus.ATTENTE_CLIENT.value,
    )
    pub2 = client.get(f"/api/v1/public/contrats-gestion/{mandant_token}")
    assert pub2.json()["party"] == "mandant"

    mandant_signed = client.post(
        f"/api/v1/public/contrats-gestion/{mandant_token}/sign",
        json={"signed_name": "Marie T.", "signature_image_data_url": _PNG_DATA_URL},
    )
    assert mandant_signed.status_code == 200, mandant_signed.text
    assert mandant_signed.json()["status"] == ContratGestionStatus.SIGNE.value

    # PDF signé récupérable (contient les deux signatures).
    spdf = client.get(
        f"/api/v1/contrats-gestion/{contrat_id}/signed-pdf", headers=auth_headers
    )
    assert spdf.status_code == 200, spdf.text
    assert spdf.content[:4] == b"%PDF"

    # Un contrat signé peut être supprimé (confirmation côté UI).
    deleted = client.delete(
        f"/api/v1/contrats-gestion/{contrat_id}", headers=auth_headers
    )
    assert deleted.status_code == 204, deleted.text
