"""Smoke — alerte DOUBLON à la création d'un locataire (retour Phil
2026-08-13).

« Si j'essaie de créer un nouveau locataire et il a soit le même
courriel ou même téléphone, ça me met une alerte me disant qu'il existe
déjà. » — 6 paires de fiches en double avaient dû être fusionnées à la
main la semaine précédente.

Ce que le test verrouille :
1. la détection normalise le COURRIEL (casse, espaces) et le TÉLÉPHONE
   (« 514 555-1234 », « (514) 555-1234 », « 5145551234 » = le même) ;
2. elle rapporte le logement/bail actuel, pour reconnaître la fiche ;
3. elle ne bloque JAMAIS la création (le staff garde le dernier mot).
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


@pytest.fixture(scope="module")
def doublon_seed(run, seeded_users) -> dict:
    """Une fiche existante logée au 44 Kennedy 101."""

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="44 Kennedy (smoke doublons)",
                address="44 rue Kennedy",
                city="Montréal",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="101",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(
                full_name="Marie Doublon",
                email="Marie.Doublon@Test.Local",
                phone="(514) 555-1234",
            )
            s.add_all([lg, loc])
            await s.flush()
            today = date.today()
            s.add(
                Bail(
                    logement_id=lg.id, locataire_id=loc.id,
                    date_debut=today - timedelta(days=200),
                    date_fin=today + timedelta(days=165),
                    loyer_mensuel=1100.0,
                    status=BailStatus.ACTIF.value,
                )
            )
            await s.commit()
            return {
                "locataire_id": loc.id,
                "immeuble_id": imm.id,
                "logement_id": lg.id,
            }

    return run(_seed())


def test_doublon_courriel_insensible_a_la_casse(
    client, auth_headers, doublon_seed
):
    r = client.get(
        "/api/v1/immobilier/locataires/doublons"
        "?email=%20MARIE.DOUBLON@test.local%20",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rows = [x for x in r.json() if x["id"] == doublon_seed["locataire_id"]]
    assert len(rows) == 1
    assert rows[0]["motif"] == "courriel"
    # La fiche est reconnaissable : son logement actuel est rapporté.
    assert rows[0]["logement_numero"] == "101"
    assert rows[0]["immeuble_id"] == doublon_seed["immeuble_id"]


@pytest.mark.parametrize(
    "saisie",
    ["5145551234", "514 555-1234", "(514) 555-1234", "1-514-555-1234"],
)
def test_doublon_telephone_tous_les_formats(
    client, auth_headers, doublon_seed, saisie
):
    """Les numéros sont tapés à la main dans tous les formats — la
    comparaison se fait sur les chiffres seulement."""
    r = client.get(
        "/api/v1/immobilier/locataires/doublons",
        headers=auth_headers,
        params={"phone": saisie},
    )
    assert r.status_code == 200, r.text
    ids = [x["id"] for x in r.json()]
    assert doublon_seed["locataire_id"] in ids


def test_doublon_courriel_et_telephone(client, auth_headers, doublon_seed):
    r = client.get(
        "/api/v1/immobilier/locataires/doublons",
        headers=auth_headers,
        params={"email": "marie.doublon@test.local", "phone": "5145551234"},
    )
    rows = [x for x in r.json() if x["id"] == doublon_seed["locataire_id"]]
    assert rows[0]["motif"] == "courriel + téléphone"


def test_aucun_doublon_quand_rien_ne_matche(
    client, auth_headers, doublon_seed
):
    r = client.get(
        "/api/v1/immobilier/locataires/doublons",
        headers=auth_headers,
        params={"email": "personne@test.local", "phone": "438 000-9999"},
    )
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()] == []
    # Sans critère du tout : pas de liste complète renvoyée par erreur.
    vide = client.get(
        "/api/v1/immobilier/locataires/doublons", headers=auth_headers
    )
    assert vide.json() == []


def test_creation_jamais_bloquee(client, auth_headers, doublon_seed):
    """L'alerte est informative : le staff peut créer quand même (vrais
    homonymes, couple partageant un courriel de ménage)."""
    r = client.post(
        "/api/v1/immobilier/locataires",
        headers=auth_headers,
        json={
            "full_name": "Marie Doublon (bis)",
            "email": "marie.doublon@test.local",
            "phone": "514 555-1234",
        },
    )
    assert r.status_code == 201, r.text
    nouveau = r.json()["id"]
    # … et la nouvelle fiche devient elle-même un doublon détecté, sauf
    # si on l'exclut explicitement (édition de sa propre fiche).
    ids = [
        x["id"]
        for x in client.get(
            "/api/v1/immobilier/locataires/doublons",
            headers=auth_headers,
            params={"email": "marie.doublon@test.local"},
        ).json()
    ]
    assert set(ids) == {doublon_seed["locataire_id"], nouveau}
    ids2 = [
        x["id"]
        for x in client.get(
            "/api/v1/immobilier/locataires/doublons",
            headers=auth_headers,
            params={
                "email": "marie.doublon@test.local",
                "exclure_id": nouveau,
            },
        ).json()
    ]
    assert ids2 == [doublon_seed["locataire_id"]]
