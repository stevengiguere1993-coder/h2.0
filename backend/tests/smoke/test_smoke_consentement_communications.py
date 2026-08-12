"""Smoke — consentement aux communications électroniques (v17b).

1. POST /baux/{id}/tal/consentement_communications.pdf → 200, un PDF,
   et un ImmDocument type ``consentement_communications`` archivé au
   DOSSIER du locataire (signable → non exclu par ``_est_dossier``).
2. Le helper ``preparer_consentement_communications`` (accroché à la
   création d'un bail) archive le document au dossier et n'envoie
   JAMAIS de courriel — même quand le locataire en a un. Règle posée
   par Phil : aucun envoi automatique vers un locataire.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
)

from .conftest import ADMIN_EMAIL, TestSessionLocal


@pytest.fixture(scope="module")
def consentement_seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Smoke Consentement",
                address="12 rue du Consentement",
                city="Saint-Rémi",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="2",
                status=LogementStatus.OCCUPE.value,
            )
            # AVEC courriel : c'est justement le cas qui doit prouver que
            # rien ne part automatiquement.
            loc = Locataire(
                full_name="Colette Courriel",
                email="colette.courriel@example.com",
            )
            s.add_all([lg, loc])
            await s.flush()
            bail = Bail(
                logement_id=lg.id,
                locataire_id=loc.id,
                date_debut=date(2026, 8, 1),
                date_fin=date(2026, 8, 1) + timedelta(days=364),
                loyer_mensuel=1000.0,
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


def _docs_dossier(client, headers, locataire_id: int) -> list[dict]:
    r = client.get(
        f"/api/v1/immobilier/locataires/{locataire_id}"
        "/documents?categorie=dossier",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_generation_pdf_et_archivage(client, auth_headers, consentement_seed):
    r = client.post(
        f"/api/v1/immobilier/baux/{consentement_seed['bail_id']}"
        "/tal/consentement_communications.pdf",
        headers=auth_headers,
        json={},
    )
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF-")

    docs = _docs_dossier(
        client, auth_headers, consentement_seed["locataire_id"]
    )
    matches = [
        d for d in docs if d["type"] == "consentement_communications"
    ]
    assert matches, docs
    # Signable : la pièce est au dossier, pas une simple communication.
    assert all(d["signature_requise"] for d in matches)


def test_helper_archive_sans_jamais_envoyer(
    client, auth_headers, consentement_seed, run
):
    from app.api.v1.endpoints.immobilier_extras import (
        preparer_consentement_communications,
    )

    avant = len(
        [
            d
            for d in _docs_dossier(
                client, auth_headers, consentement_seed["locataire_id"]
            )
            if d["type"] == "consentement_communications"
        ]
    )

    async def _call() -> bool:
        async with TestSessionLocal() as s:
            return await preparer_consentement_communications(
                s,
                consentement_seed["bail_id"],
                SimpleNamespace(email=ADMIN_EMAIL),
            )

    assert run(_call()) is True

    apres = [
        d
        for d in _docs_dossier(
            client, auth_headers, consentement_seed["locataire_id"]
        )
        if d["type"] == "consentement_communications"
    ]
    assert len(apres) == avant + 1
    # RÈGLE ABSOLUE : le document est archivé, mais RIEN ne part au
    # locataire — même quand il a un courriel. L'envoi reste un geste
    # manuel (bouton « Envoyer pour signature » de la fiche).
    assert all(d["envoye_le"] is None for d in apres)
