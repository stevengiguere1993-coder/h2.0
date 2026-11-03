"""Smoke — Adresses déjà connues pour le champ d'adresse (Steven 2026-11-03).

« Lorsqu'on entre un client via nouveau client dans projet, l'adresse n'a
rien qui apparaît. Il doit y avoir un choix d'adresse parmi les adresses
existantes. »

``GET /api/v1/adresses/connues`` réunit les adresses des immeubles,
projets et clients, dédoublonnées (accents / casse / ponctuation
ignorés), filtrables par mots ; un employé ne voit que ses immeubles et
projets affectés, et aucune adresse de client.
"""
from __future__ import annotations

import pytest

from app.api.v1.endpoints.adresses import (
    cle_adresse,
    composer_adresse_immeuble,
    filtrer,
    AdresseConnue,
)
from app.models.client import Client
from app.models.immobilier import Immeuble
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user_immeuble import UserImmeuble
from tests.smoke.conftest import TestSessionLocal

URL = "/api/v1/adresses/connues"


def test_cle_adresse_et_composition():
    assert cle_adresse("710, Rue Legendre") == cle_adresse("710 rue legendre")
    assert cle_adresse("Montréal") == "montreal"
    assert (
        composer_adresse_immeuble("710 rue Legendre", "Montréal", "H2M 1S2")
        == "710 rue Legendre, Montréal, H2M 1S2"
    )
    # Ville déjà dans l'adresse : pas répétée.
    assert (
        composer_adresse_immeuble("710 rue Legendre, Montréal", "Montréal", None)
        == "710 rue Legendre, Montréal"
    )


def test_filtrer_par_mots_sans_accents():
    xs = [
        AdresseConnue(adresse="710 rue Legendre, Montréal", source="immeuble", nom="Legendre"),
        AdresseConnue(adresse="9085 rue Millen, Montréal", source="projet", nom="Millen"),
    ]
    assert [a.adresse for a in filtrer(xs, "legendre MONTREAL")] == [
        "710 rue Legendre, Montréal"
    ]
    assert [a.adresse for a in filtrer(xs, "710 leg")] == ["710 rue Legendre, Montréal"]
    assert len(filtrer(xs, "")) == 2
    assert filtrer(xs, "laval") == []


@pytest.fixture(scope="module")
def seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Legendre (adresses)", address="710 rue Legendre",
                city="Montréal", postal_code="H2M 1S2", is_active=True,
                address_secondaire="9085 rue Millen",
            )
            imm_inactif = Immeuble(
                name="Vendu (adresses)", address="1 rue Vendue",
                city="Laval", is_active=False,
            )
            s.add_all([imm, imm_inactif])
            await s.flush()
            proj = Project(
                name="Chantier Legendre (adresses)",
                # Même adresse que l'immeuble, autre ponctuation : dédoublonnée.
                address="710, Rue Legendre, Montréal, H2M 1S2",
                status="planned",
            )
            proj_autre = Project(
                name="Chantier Rosemont (adresses)",
                address="5000 rue Beaubien Est, Montréal",
                status="planned",
            )
            cli = Client(name="Maxime (adresses)", address="123 rue des Clients, Longueuil")
            s.add_all([proj, proj_autre, cli])
            await s.flush()
            s.add(UserImmeuble(user_id=seeded_users["employee_id"], immeuble_id=imm.id))
            s.add(
                ProjectMember(
                    user_id=seeded_users["employee_id"], project_id=proj_autre.id
                )
            )
            await s.commit()
            return {"imm": imm.id, "proj": proj.id, "proj_autre": proj_autre.id}

    return run(_seed())


def test_admin_voit_tout_dedoublonne(client, auth_headers, seed):
    r = client.get(URL, headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    adresses = [x["adresse"] for x in rows]
    assert "710 rue Legendre, Montréal, H2M 1S2" in adresses
    assert "9085 rue Millen, Montréal, H2M 1S2" in adresses
    assert "5000 rue Beaubien Est, Montréal" in adresses
    assert "123 rue des Clients, Longueuil" in adresses
    # Immeuble inactif exclu ; doublon projet/immeuble absorbé.
    assert not any("Vendue" in a for a in adresses)
    assert sum(1 for a in adresses if cle_adresse(a) == cle_adresse("710 rue Legendre Montréal H2M 1S2")) == 1
    legendre = next(x for x in rows if x["adresse"].startswith("710 rue Legendre"))
    assert legendre["source"] == "immeuble"
    assert legendre["nom"] == "Legendre (adresses)"
    # Clés dédoublonnées globalement.
    assert len({cle_adresse(a) for a in adresses}) == len(adresses)


def test_filtre_q(client, auth_headers, seed):
    r = client.get(URL, params={"q": "beaubien"}, headers=auth_headers)
    assert r.status_code == 200
    assert [x["adresse"] for x in r.json()] == ["5000 rue Beaubien Est, Montréal"]
    r = client.get(URL, params={"q": "maxime"}, headers=auth_headers)
    assert [x["adresse"] for x in r.json()] == ["123 rue des Clients, Longueuil"]


def test_employe_ne_voit_que_le_sien(client, employee_headers, seed):
    r = client.get(URL, headers=employee_headers)
    assert r.status_code == 200, r.text
    adresses = [x["adresse"] for x in r.json()]
    assert "710 rue Legendre, Montréal, H2M 1S2" in adresses
    assert "5000 rue Beaubien Est, Montréal" in adresses
    assert "123 rue des Clients, Longueuil" not in adresses


def test_sans_jeton_401(client, seed):
    assert client.get(URL).status_code == 401
