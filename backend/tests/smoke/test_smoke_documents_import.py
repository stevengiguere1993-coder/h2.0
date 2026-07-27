"""Smoke — import de documents + « document courant » (2026-07-27).

Retour Phil : démêlage communications/documents.
1. Importer un PDF au dossier d'un locataire → visible dans ses
   documents, source='importe', catégorie « dossier ».
2. Importer LE bail → devient le document courant (bail.document_id) ;
   le remplacer archive l'ancien (remplace_document_id) et les DEUX
   restent listés dans les Documents.
3. categorie=dossier exclut les communications générées sans signature.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
)

from .conftest import TestSessionLocal

_PDF = b"%PDF-1.4 smoke test document"


@pytest.fixture(scope="module")
def doc_seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Smoke Docs", address="9 rue Dossier",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="A",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(full_name="Diane Dossier")
            s.add_all([lg, loc])
            await s.flush()
            bail = Bail(
                logement_id=lg.id,
                locataire_id=loc.id,
                date_debut=date(2026, 7, 1),
                date_fin=date(2026, 7, 1) + timedelta(days=365),
                loyer_mensuel=900.0,
                status=BailStatus.ACTIF.value,
            )
            s.add(bail)
            await s.commit()
            return {
                "immeuble_id": imm.id,
                "logement_id": lg.id,
                "locataire_id": loc.id,
                "bail_id": bail.id,
            }

    return run(_seed())


def _upload(client, headers, url: str, extra: dict | None = None):
    return client.post(
        url,
        headers=headers,
        files={"file": ("bail-signe.pdf", _PDF, "application/pdf")},
        data=extra or {},
    )


def test_import_document_locataire(client, auth_headers, doc_seed):
    r = _upload(
        client, auth_headers, "/api/v1/immobilier/documents/import",
        {"locataire_id": str(doc_seed["locataire_id"]), "type": "autre",
         "titre": "Preuve d'assurance 2026"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["source"] == "importe"
    assert d["filename"] == "bail-signe.pdf"

    docs = client.get(
        f"/api/v1/immobilier/locataires/{doc_seed['locataire_id']}"
        "/documents?categorie=dossier",
        headers=auth_headers,
    ).json()
    assert any(x["id"] == d["id"] for x in docs)

    # Le PDF se rouvre tel quel.
    pdf = client.get(
        f"/api/v1/immobilier/documents/{d['id']}/pdf", headers=auth_headers
    )
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")


def test_import_sans_rattachement_rejete(client, auth_headers):
    r = _upload(client, auth_headers, "/api/v1/immobilier/documents/import")
    assert r.status_code == 422


def test_bail_courant_et_remplacement(client, auth_headers, doc_seed):
    bail_id = doc_seed["bail_id"]
    # 1er import → document courant du bail.
    r1 = _upload(
        client, auth_headers, f"/api/v1/immobilier/baux/{bail_id}/document"
    )
    assert r1.status_code == 200, r1.text
    v1 = r1.json()

    # « Clic sur le bail » = GET /baux/{id}/document → sert maintenant le
    # PDF importé (avant : 409 tant que pas signé en ligne).
    ouvert = client.get(
        f"/api/v1/immobilier/baux/{bail_id}/document", headers=auth_headers
    )
    assert ouvert.status_code == 200, ouvert.text
    assert ouvert.content.startswith(b"%PDF-")

    # Remplacement → nouveau courant, l'ancien archivé mais conservé.
    r2 = _upload(
        client, auth_headers, f"/api/v1/immobilier/baux/{bail_id}/document"
    )
    assert r2.status_code == 200, r2.text
    v2 = r2.json()
    assert v2["id"] != v1["id"]
    assert v2["remplace_document_id"] == v1["id"]

    docs = client.get(
        f"/api/v1/immobilier/baux/{bail_id}/documents?categorie=dossier",
        headers=auth_headers,
    ).json()
    ids = {x["id"] for x in docs}
    assert v1["id"] in ids and v2["id"] in ids  # historique conservé

    # Les deux apparaissent aussi côté logement et locataire.
    for url in (
        f"/api/v1/immobilier/logements/{doc_seed['logement_id']}/documents",
        f"/api/v1/immobilier/locataires/{doc_seed['locataire_id']}/documents",
    ):
        ids2 = {x["id"] for x in client.get(url, headers=auth_headers).json()}
        assert v1["id"] in ids2 and v2["id"] in ids2
