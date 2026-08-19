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


def test_exception_sort_de_la_liste_mais_reste_comptee(
    client, auth_headers, seed_sans_doc
):
    """« Il pourrait y avoir des situations exceptionnelles où il y en a
    pas — faudrait pas que ce soit un frein » (Phil, 2026-08-19).

    Le blocage reste la réponse par défaut, mais il se franchit avec un
    motif. La ligne quitte alors la liste ACTIONNABLE — une alerte qui
    crie pour des cas déjà tranchés finit par ne plus être lue — sans
    disparaître : elle reste comptée, avec son motif et son auteur.
    """
    bail_id = seed_sans_doc["bail_sans_doc"]
    url = f"/api/v1/immobilier/baux/{bail_id}/exception-document"

    # Un motif vide (ou trop court) est refusé : une exception sans
    # raison n'est qu'un oubli déguisé.
    assert client.post(
        url, headers=auth_headers, json={"motif": "  "}
    ).status_code == 422

    r = client.post(
        url, headers=auth_headers,
        json={"motif": "Entente verbale — chambre au mois, aucun bail écrit"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["par"], "l'exception doit être signée"

    liste = client.get(
        "/api/v1/immobilier/baux/sans-document"
        f"?immeuble_id={seed_sans_doc['immeuble_id']}",
        headers=auth_headers,
    ).json()
    assert liste["nb"] == 0, liste
    assert liste["nb_exceptions"] == 1
    exc = liste["exceptions"][0]
    assert exc["bail_id"] == bail_id
    assert "Entente verbale" in (exc["motif"] or "")
    assert exc["motif_par"]

    # Retirer l'exception ramène la ligne dans l'alerte.
    assert client.delete(url, headers=auth_headers).status_code == 200
    liste2 = client.get(
        "/api/v1/immobilier/baux/sans-document"
        f"?immeuble_id={seed_sans_doc['immeuble_id']}",
        headers=auth_headers,
    ).json()
    assert liste2["nb"] == 1
    assert liste2["nb_exceptions"] == 0


def test_exception_refusee_si_le_bail_a_deja_son_document(
    client, auth_headers, run
):
    """Déclarer une exception sur un bail QUI A son document serait un
    contresens — et masquerait un vrai document au dossier."""
    from datetime import date

    from app.models.immobilier import Bail, BailStatus, Logement

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Exception Doc", address="16 rue du Bail",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="5")
            loc = Locataire(full_name="Avec Document")
            s.add_all([lg, loc])
            await s.flush()
            b = Bail(
                logement_id=lg.id, locataire_id=loc.id,
                date_debut=date(2026, 7, 1), date_fin=date(2027, 6, 30),
                loyer_mensuel=1200.0, status=BailStatus.ACTIF.value,
                document_id=4242,
            )
            s.add(b)
            await s.flush()
            await s.commit()
            return b.id

    bail_id = run(_seed())
    r = client.post(
        f"/api/v1/immobilier/baux/{bail_id}/exception-document",
        headers=auth_headers,
        json={"motif": "on verra plus tard"},
    )
    assert r.status_code == 409, r.text


def test_reloue_bloque_puis_debloque_par_l_exception(
    client, auth_headers, run
):
    """Le garde-fou reste la réponse PAR DÉFAUT — un bail sans document
    est presque toujours un oubli — mais il ne doit pas devenir un frein
    quand il n'y a réellement rien à joindre. Blocage, puis passage
    après déclaration motivée.
    """
    from datetime import date

    from app.models.immobilier import (
        Bail,
        BailStatus,
        LocationDossier,
        LocationDossierStatut,
        Logement,
    )

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Reloue Exception", address="18 rue du Bail",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="7")
            loc = Locataire(full_name="Nouveau Sans Bail")
            s.add_all([lg, loc])
            await s.flush()
            b = Bail(
                logement_id=lg.id, locataire_id=loc.id,
                date_debut=date(2026, 8, 1), date_fin=date(2027, 7, 31),
                loyer_mensuel=1100.0, status=BailStatus.ACTIF.value,
            )
            s.add(b)
            await s.flush()
            d = LocationDossier(
                logement_id=lg.id,
                statut=LocationDossierStatut.AVIS_RECU.value,
                nouveau_bail_id=b.id,
            )
            s.add(d)
            await s.flush()
            await s.commit()
            return {"dossier_id": d.id, "bail_id": b.id}

    ids = run(_seed())

    # (a) Sans bail ni exception : bloqué, avec la marche à suivre.
    r = client.patch(
        f"/api/v1/immobilier/locations/{ids['dossier_id']}",
        headers=auth_headers,
        json={"statut": "reloue"},
    )
    assert r.status_code == 422, r.text
    assert "exception" in r.text.lower(), r.text

    # (b) Exception déclarée : le dossier passe.
    assert client.post(
        f"/api/v1/immobilier/baux/{ids['bail_id']}/exception-document",
        headers=auth_headers,
        json={"motif": "Chambre au mois — aucun bail écrit signé"},
    ).status_code == 200

    r2 = client.patch(
        f"/api/v1/immobilier/locations/{ids['dossier_id']}",
        headers=auth_headers,
        json={"statut": "reloue"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["statut"] == "reloue"
