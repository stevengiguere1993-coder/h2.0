"""Smoke — le bail signé DOIT être au dossier (audit 2026-08-19).

Les baux sont signés HORS de Kratos : le seul exemplaire au dossier est
celui qu'on importe à l'entrée du locataire. Deux pièces s'assurent que
rien ne passe :

1. le GARDE-FOU — un dossier de relocation ne passe pas à « Reloué »
   tant que le bail n'est pas importé ;
2. la LISTE — parce que le garde-fou ne couvre que ce chemin : un bail
   créé directement « déjà en vigueur » y échappe. En prod, 8 baux
   actifs étaient dans ce cas, tous récents (avril à août 2026).

La liste exclut la gestion externe : ces baux ne sont pas chez nous.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


@pytest.fixture(scope="module")
def seed_sans_doc(run, seeded_users) -> dict:
    """Deux immeubles : un à nous (2 baux, 1 sans document) et un en
    gestion externe (1 bail sans document — ne doit jamais sortir)."""

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            nous = Immeuble(
                name="Immeuble Bail Dossier", address="12 rue du Bail",
                city="Montréal", is_active=True,
            )
            externe = Immeuble(
                name="Immeuble Externe Bail", address="14 rue du Bail",
                city="Granby", is_active=True, gestion_externe=True,
            )
            s.add_all([nous, externe])
            await s.flush()
            debut = datetime.now(timezone.utc).date() - timedelta(days=120)
            ids: dict = {"immeuble_id": nous.id}
            for i, (imm, numero, avec_doc) in enumerate(
                [
                    (nous, "1", False),   # ← doit ressortir
                    (nous, "2", True),    # bail au dossier : silencieux
                    (externe, "9", False),  # gestion externe : ignoré
                ]
            ):
                lg = Logement(
                    immeuble_id=imm.id, numero=numero,
                    status=LogementStatus.OCCUPE.value,
                )
                loc = Locataire(full_name=f"Locataire Dossier {i}")
                s.add_all([lg, loc])
                await s.flush()
                b = Bail(
                    logement_id=lg.id, locataire_id=loc.id,
                    date_debut=debut, date_fin=debut + timedelta(days=365),
                    loyer_mensuel=1000.0,
                    status=BailStatus.ACTIF.value,
                    document_id=999 if avec_doc else None,
                )
                s.add(b)
                await s.flush()
                if numero == "1":
                    ids["bail_sans_doc"] = b.id
            await s.commit()
            return ids

    return run(_seed())


def test_liste_les_baux_actifs_sans_document(
    client, auth_headers, seed_sans_doc
):
    r = client.get(
        "/api/v1/immobilier/baux/sans-document"
        f"?immeuble_id={seed_sans_doc['immeuble_id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    ids = [x["bail_id"] for x in data["rows"]]
    assert seed_sans_doc["bail_sans_doc"] in ids
    # Le bail QUI A son document ne doit pas polluer la liste.
    assert data["nb"] == 1, data
    ligne = data["rows"][0]
    assert ligne["jours"] >= 119, ligne
    assert ligne["logement"] == "1"


def test_gestion_externe_jamais_listee(client, auth_headers, seed_sans_doc):
    """Sans filtre d'immeuble, le bail de l'immeuble en gestion externe
    ne doit apparaître nulle part — leurs baux ne sont pas chez nous."""
    r = client.get(
        "/api/v1/immobilier/baux/sans-document", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    noms = {x["immeuble"] for x in r.json()["rows"]}
    assert "Immeuble Externe Bail" not in noms
