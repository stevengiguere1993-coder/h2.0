"""Smoke — rôle « investisseur » (Steven, 2026-11-07).

Un actionnaire externe a SON rôle, sous l'employé : aucun accès
opérationnel (construction, prospection, entreprises…), seul le volet
investisseur, et un compte créé par le pôle Investisseurs naît avec ce
rôle. Un employé déjà actionnaire garde son rôle (cohabitation).
"""
from __future__ import annotations

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.entreprise import Entreprise, EntreprisePartner
from app.models.user import User

from .conftest import TestSessionLocal


@pytest.fixture(scope="module")
def role_ids(run, db_setup) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            ent = Entreprise(name="INC Rôle Investisseur")
            s.add(ent)
            await s.flush()
            inv = User(
                email="role.investisseur@example.com",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=False,
                role="investisseur",
                # Volets « généreux » laissés en base : le rôle prime.
                volets_json='["investisseur", "construction"]',
                first_name="Rôle",
                last_name="Investisseur",
            )
            s.add(inv)
            await s.flush()
            s.add(
                EntreprisePartner(
                    entreprise_id=ent.id,
                    user_id=inv.id,
                    partner_name="Rôle Investisseur",
                    ownership_pct=40,
                )
            )
            owner = User(
                email="owner.role.investisseur@example.com",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=True,
                role="owner",
            )
            s.add(owner)
            await s.flush()
            # Actionnaire SANS compte, pour la création par la console.
            pr = EntreprisePartner(
                entreprise_id=ent.id,
                partner_name="Nouveau Actionnaire",
                partner_email="nouveau.actionnaire@example.com",
                ownership_pct=60,
            )
            s.add(pr)
            await s.commit()
            return {
                "ent": ent.id,
                "inv": inv.id,
                "partner": pr.id,
                "owner": owner.id,
            }

    return run(_seed())


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(subject=str(uid))}"}


def test_le_role_est_sous_l_employe_et_n_a_que_son_volet(run, role_ids):
    from app.models.user import ROLE_RANK, UserRole

    assert ROLE_RANK["investisseur"] < ROLE_RANK["employee"]
    assert UserRole.INVESTOR.value == "investisseur"

    async def _go():
        async with TestSessionLocal() as s:
            return await s.get(User, role_ids["inv"])

    u = run(_go())
    assert u.volets == ["investisseur"]  # construction ignoré
    assert not u.has_min_role("employee")
    assert u.has_min_role("investisseur")


def test_me_portail_ouvert_operations_fermees(client, role_ids):
    r = client.get("/api/v1/auth/me", headers=_h(role_ids["inv"]))
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["role"] == "investisseur"
    assert me["volets"] == ["investisseur"]
    access = me.get("access") or {}
    assert access.get("page:investisseur.portefeuille") is True
    assert access.get("page:general.profil") is True
    assert access.get("page:construction.projets") is False
    assert access.get("volet:construction") is False

    # Son portail répond (cascade : 40 % de la compagnie).
    r = client.get("/api/v1/invest/me/portefeuille", headers=_h(role_ids["inv"]))
    assert r.status_code == 200, r.text

    # Les routes d'un autre volet lui sont fermées (403 volet).
    r = client.get("/api/v1/projects", headers=_h(role_ids["inv"]))
    assert r.status_code == 403, r.text
    # La console admin du pôle aussi.
    r = client.get("/api/v1/invest/admin/projets", headers=_h(role_ids["inv"]))
    assert r.status_code == 403, r.text


def test_compte_cree_par_la_console_nait_investisseur(
    client, auth_headers, role_ids, run
):
    r = client.post(
        f"/api/v1/invest/admin/partenaires/{role_ids['partner']}/creer-compte",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    uid = r.json()["user_id"]

    async def _go():
        async with TestSessionLocal() as s:
            return await s.get(User, uid)

    u = run(_go())
    assert u.role == "investisseur"
    assert u.volets == ["investisseur"]
    assert u.must_change_password is True
    # Il voit son projet d'office (60 %) — aucune case à cocher.
    r = client.get("/api/v1/invest/me/portefeuille", headers=_h(uid))
    assert r.status_code == 200, r.text
    assert [p["parts_pct"] for p in r.json()["projets"]] == [60.0]


def test_changer_le_role_vers_investisseur_reduit_les_volets(
    client, role_ids, run
):
    owner_headers = _h(role_ids["owner"])
    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = User(
                email="futur.investisseur@example.com",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=False,
                role="employee",
                volets_json='["construction", "prospection"]',
            )
            s.add(u)
            await s.commit()
            return u.id

    uid = run(_seed())
    r = client.patch(
        f"/api/v1/users/{uid}/role",
        headers=owner_headers,
        json={"role": "investisseur"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "investisseur"
    r = client.get("/api/v1/auth/me", headers=_h(uid))
    assert r.json()["volets"] == ["investisseur"]

    # Rôle inconnu toujours refusé.
    r = client.patch(
        f"/api/v1/users/{uid}/role",
        headers=owner_headers,
        json={"role": "actionnaire"},
    )
    assert r.status_code == 422


def test_creation_directe_d_un_investisseur(client, auth_headers):
    r = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "direct.investisseur@example.com",
            "full_name": "Direct Investisseur",
            "role": "investisseur",
            "volets": ["construction"],  # ignoré pour ce rôle
        },
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["role"] == "investisseur"
    assert r.json()["volets"] == ["investisseur"]


def test_portail_ouvert_meme_si_la_grille_dit_employe(client, role_ids, run):
    """Steven, 2026-11-08 : Vincent (rôle investisseur, volet coché) voyait
    « Accès refusé ». En prod, la grille avait été semée à « employé »
    pour le portefeuille / le profil / les paramètres AVANT que le rôle
    existe : la dérivation « volet = au moins une page » fermait tout.
    Un seuil « employé » sur ces pages vaut « investisseur »."""
    from app.models.role_permission import RolePermission
    from app.services.permissions_service import (
        get_min_role,
        invalidate_permissions_cache,
    )

    async def _seed():
        async with TestSessionLocal() as s:
            for key in (
                "page:investisseur.portefeuille",
                "page:general.profil",
                "page:general.parametres",
            ):
                s.add(RolePermission(capability=key, min_role="employee"))
            await s.commit()

    run(_seed())
    invalidate_permissions_cache()
    try:
        assert run(get_min_role("page:investisseur.portefeuille")) == "investisseur"
        # Un choix plus strict de l'owner est respecté.
        async def _durcir():
            async with TestSessionLocal() as s:
                from sqlalchemy import update

                await s.execute(
                    update(RolePermission)
                    .where(RolePermission.capability == "page:general.parametres")
                    .values(min_role="manager")
                )
                await s.commit()

        run(_durcir())
        invalidate_permissions_cache()
        assert run(get_min_role("page:general.parametres")) == "manager"

        r = client.get("/api/v1/auth/me", headers=_h(role_ids["inv"]))
        access = r.json()["access"]
        assert access["volet:investisseur"] is True
        assert access["page:investisseur.portefeuille"] is True
        assert access["page:general.profil"] is True
        assert access["page:general.parametres"] is False
        r = client.get("/api/v1/invest/me/portefeuille", headers=_h(role_ids["inv"]))
        assert r.status_code == 200, r.text
    finally:
        async def _clean():
            async with TestSessionLocal() as s:
                from sqlalchemy import delete

                await s.execute(
                    delete(RolePermission).where(
                        RolePermission.capability.in_(
                            [
                                "page:investisseur.portefeuille",
                                "page:general.profil",
                                "page:general.parametres",
                            ]
                        )
                    )
                )
                await s.commit()

        run(_clean())
        invalidate_permissions_cache()


def test_grille_permissions_connait_le_role(client, auth_headers):
    r = client.get("/api/v1/permissions", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["roles"][0] == "investisseur"


def test_fiche_acces_investisseur_et_interrupteur(client, auth_headers, role_ids):
    """Steven, 2026-11-09 : « quand je clique sur le nom de l'investisseur,
    cela devrait m'amener à sa section du contrôle des accès de ce qu'il
    peut voir ou pas ». GET = ce que la cascade lui donne, PUT = masque /
    montre un projet sans toucher aux parts."""
    uid, eid = role_ids["inv"], role_ids["ent"]
    base = f"/api/v1/invest/admin/investisseurs/{uid}/acces"

    r = client.get(base, headers=auth_headers)
    assert r.status_code == 200, r.text
    fiche = r.json()
    assert fiche["user"]["id"] == uid
    assert fiche["user"]["role"] == "investisseur"
    ligne = next(p for p in fiche["projets"] if p["entreprise_id"] == eid)
    assert ligne["pct_total"] == 40.0
    assert ligne["source"] == "cascade"
    assert ligne["visible"] is True

    # Masquer : le projet disparaît du portail, la part reste.
    r = client.put(f"{base}/{eid}", headers=auth_headers, json={"visible": False})
    assert r.status_code == 200, r.text
    ligne = next(p for p in r.json()["projets"] if p["entreprise_id"] == eid)
    assert ligne["visible"] is False
    assert ligne["pct_total"] == 40.0
    r = client.get("/api/v1/invest/me/portefeuille", headers=_h(uid))
    assert all(p["entreprise_id"] != eid for p in r.json()["projets"])

    # Remontrer.
    r = client.put(f"{base}/{eid}", headers=auth_headers, json={"visible": True})
    assert r.status_code == 200, r.text
    ligne = next(p for p in r.json()["projets"] if p["entreprise_id"] == eid)
    assert ligne["visible"] is True
    r = client.get("/api/v1/invest/me/portefeuille", headers=_h(uid))
    assert any(p["entreprise_id"] == eid for p in r.json()["projets"])

    # Utilisateur inconnu, et l'investisseur lui-même n'y a pas accès.
    assert client.get("/api/v1/invest/admin/investisseurs/999999/acces", headers=auth_headers).status_code == 404
    assert client.get(base, headers=_h(uid)).status_code == 403
    assert client.put(f"{base}/{eid}", headers=auth_headers, json={}).status_code == 422
