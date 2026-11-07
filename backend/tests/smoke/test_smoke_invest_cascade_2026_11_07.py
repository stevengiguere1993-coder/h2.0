"""Smoke — Portail Investisseur : participations EN CASCADE
(Steven, 2026-11-07).

« Vincent détient 30 % dans la compagnie X, celle-ci détient 50 % d'un
projet : Vincent doit voir le projet, sa valeur globale et sa valeur
personnelle. » Et : un actionnaire inscrit dans « Parts &
actionnaires » voit son projet SANS qu'un admin ait à cocher « Visible »
(c'est ce qui bloquait Vincent Clark : participations « activées »
restées masquées). L'admin garde une exception « Masquer ».

Structure montée ici :

    Vincent (compte)  ── 30 % ──▶ Holding X ── 50 % ──▶ Projet A (immeuble)
    Vincent           ── 10 % ──▶ Projet A                      (direct)
    Éric (courriel)   ── 70 % ──▶ Holding X
    Holding X         ── 25 % ──▶ Holding Y ── 40 % ──▶ Projet B
"""
from __future__ import annotations

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.entreprise import Entreprise, EntreprisePartner
from app.models.immobilier import Immeuble
from app.models.invest_portal import InvestParticipation
from app.models.user import User

from .conftest import TestSessionLocal


@pytest.fixture(scope="module")
def cascade_ids(run, db_setup) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            holding_x = Entreprise(name="Holding X Cascade")
            holding_y = Entreprise(name="Holding Y Cascade")
            projet_a = Entreprise(name="Projet A Cascade")
            projet_b = Entreprise(name="Projet B Cascade")
            s.add_all([holding_x, holding_y, projet_a, projet_b])
            await s.flush()
            s.add_all(
                [
                    Immeuble(
                        name="Imm A Cascade",
                        address="1 rue Cascade",
                        city="Montréal",
                        is_active=True,
                        owner_entreprise_id=projet_a.id,
                        purchase_price=1_000_000,
                    ),
                    Immeuble(
                        name="Imm B Cascade",
                        address="2 rue Cascade",
                        city="Montréal",
                        is_active=True,
                        owner_entreprise_id=projet_b.id,
                        purchase_price=500_000,
                    ),
                ]
            )
            vincent = User(
                email="vincent.cascade@smoke.test",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=False,
                role="employee",
                volets_json='["investisseur"]',
                first_name="Vincent",
                last_name="Cascade",
            )
            eric = User(
                email="eric.cascade@smoke.test",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=False,
                role="employee",
                volets_json='["investisseur"]',
                first_name="Éric",
                last_name="Cascade",
            )
            s.add_all([vincent, eric])
            await s.flush()
            s.add_all(
                [
                    # Vincent : 30 % de Holding X (par son compte).
                    EntreprisePartner(
                        entreprise_id=holding_x.id,
                        user_id=vincent.id,
                        partner_name="Vincent Cascade",
                        ownership_pct=30,
                    ),
                    # Vincent : 10 % direct dans Projet A (par courriel).
                    EntreprisePartner(
                        entreprise_id=projet_a.id,
                        partner_name="Vincent Cascade",
                        partner_email="vincent.cascade@smoke.test",
                        ownership_pct=10,
                    ),
                    # Éric : 70 % de Holding X, lié par COURRIEL seulement
                    # (le cas de Vincent Clark en prod).
                    EntreprisePartner(
                        entreprise_id=holding_x.id,
                        partner_name="Éric Cascade",
                        partner_email="ERIC.cascade@smoke.test",
                        ownership_pct=70,
                    ),
                    # Holding X détient 50 % de Projet A (arête).
                    EntreprisePartner(
                        entreprise_id=projet_a.id,
                        partner_name="Holding X Cascade",
                        is_personne_morale=True,
                        partner_entreprise_id=holding_x.id,
                        ownership_pct=50,
                    ),
                    # Holding X détient 25 % de Holding Y ; Y détient
                    # 40 % de Projet B (deux niveaux).
                    EntreprisePartner(
                        entreprise_id=holding_y.id,
                        partner_name="Holding X Cascade",
                        is_personne_morale=True,
                        partner_entreprise_id=holding_x.id,
                        ownership_pct=25,
                    ),
                    EntreprisePartner(
                        entreprise_id=projet_b.id,
                        partner_name="Holding Y Cascade",
                        is_personne_morale=True,
                        partner_entreprise_id=holding_y.id,
                        ownership_pct=40,
                    ),
                ]
            )
            await s.commit()
            return {
                "holding_x": holding_x.id,
                "holding_y": holding_y.id,
                "projet_a": projet_a.id,
                "projet_b": projet_b.id,
                "vincent": vincent.id,
                "eric": eric.id,
            }

    return run(_seed())


def _headers(user_id: int) -> dict:
    return {
        "Authorization": f"Bearer {create_access_token(subject=str(user_id))}"
    }


def test_service_cascade_calcule_les_chemins(run, cascade_ids):
    from app.services.invest_cascade import Identite, detentions_de

    async def _go():
        async with TestSessionLocal() as s:
            return await detentions_de(
                s, Identite(user_id=cascade_ids["vincent"])
            )

    dets = run(_go())
    a = dets[cascade_ids["projet_a"]]
    # 10 % direct + 30 % × 50 % = 15 % indirect → 25 %.
    assert a.pct_direct == 10.0
    assert a.pct_indirect == 15.0
    assert a.pct_total == 25.0
    assert sorted(len(c.maillons) for c in a.chemins) == [1, 2]
    # Deux niveaux : 30 % × 25 % × 40 % = 3 %.
    b = dets[cascade_ids["projet_b"]]
    assert b.pct_total == 3.0
    assert b.pct_direct == 0.0
    chemin = b.chemins[0]
    assert [m.name for m in chemin.maillons] == [
        "Holding X Cascade",
        "Holding Y Cascade",
        "Projet B Cascade",
    ]
    # La holding elle-même figure (30 %) — l'appelant la classe à part.
    assert dets[cascade_ids["holding_x"]].pct_total == 30.0


def test_detenteurs_d_un_projet_remontent_les_compagnies(run, cascade_ids):
    from app.services.invest_cascade import detenteurs_de

    async def _go():
        async with TestSessionLocal() as s:
            return await detenteurs_de(s, cascade_ids["projet_a"])

    dets = {d.name: d for d in run(_go())}
    assert dets["Vincent Cascade"].pct_total == 25.0
    assert dets["Vincent Cascade"].user_id == cascade_ids["vincent"]
    # Éric : 70 % × 50 % = 35 %, reconnu par courriel (casse ignorée).
    assert dets["Éric Cascade"].pct_total == 35.0
    assert dets["Éric Cascade"].user_id == cascade_ids["eric"]


def test_portefeuille_sans_activation_manuelle(client, cascade_ids):
    """Aucune InvestParticipation n'existe : Vincent voit quand même
    ses deux projets, avec la valeur globale et sa part."""
    r = client.get(
        "/api/v1/invest/me/portefeuille",
        headers=_headers(cascade_ids["vincent"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    par_id = {p["entreprise_id"]: p for p in body["projets"]}
    assert set(par_id) == {cascade_ids["projet_a"], cascade_ids["projet_b"]}
    a = par_id[cascade_ids["projet_a"]]
    assert a["parts_pct"] == 25.0
    assert a["pct_direct"] == 10.0
    assert a["pct_indirect"] == 15.0
    assert a["valeur_totale"] == 1_000_000.0  # prix d'achat (repli)
    assert a["equite"] == 1_000_000.0
    assert a["valeur_parts"] == 250_000.0
    assert any(not c["direct"] for c in a["chemins"])
    # Holding X (pas d'immeuble) n'est pas un projet : elle est décrite
    # dans « compagnies » avec la valeur consolidée et la part de Vincent.
    assert cascade_ids["holding_x"] not in par_id
    comps = {c["entreprise_id"]: c for c in body["compagnies"]}
    x = comps[cascade_ids["holding_x"]]
    assert x["mon_pct"] == 30.0
    # 50 % × 1 000 000 + 25 % × (40 % × 500 000) = 550 000.
    assert x["valeur"] == 550_000.0
    assert x["ma_valeur"] == 165_000.0
    assert body["valeur_parts"] == 250_000.0 + 15_000.0


def test_fiche_projet_et_actionnaires_via_moi(client, cascade_ids):
    r = client.get(
        f"/api/v1/invest/me/projets/{cascade_ids['projet_a']}",
        headers=_headers(cascade_ids["vincent"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parts_pct"] == 25.0
    assert body["valeur_parts"] == 250_000.0
    par_nom = {a["name"]: a for a in body["actionnaires"]}
    assert par_nom["Vincent Cascade"]["is_me"] is True
    # La compagnie actionnaire montre « dont vous : 15 % ».
    assert par_nom["Holding X Cascade"]["via_moi_pct"] == 15.0
    assert par_nom["Holding X Cascade"]["is_me"] is False

    # Éric n'a RIEN directement dans Projet A mais 35 % via Holding X.
    r2 = client.get(
        f"/api/v1/invest/me/projets/{cascade_ids['projet_a']}",
        headers=_headers(cascade_ids["eric"]),
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["parts_pct"] == 35.0
    assert r2.json()["pct_direct"] == 0.0


def test_admin_masque_est_la_seule_exception(client, auth_headers, cascade_ids, run):
    """La console admin voit les détenteurs en cascade ; « masquer » une
    participation cache le projet à cet investisseur, et lui seul."""
    eid = cascade_ids["projet_a"]
    r = client.get(f"/api/v1/invest/admin/projets/{eid}", headers=auth_headers)
    assert r.status_code == 200, r.text
    dets = {d["name"]: d for d in r.json()["detenteurs"]}
    assert dets["Vincent Cascade"]["pct_total"] == 25.0
    assert dets["Éric Cascade"]["pct_indirect"] == 35.0
    # La ligne « Holding X » de la fiche est signalée comme compagnie
    # du groupe (cascade), pas comme un actionnaire à activer.
    liee = [p for p in r.json()["partenaires"] if p["personne_morale_liee"]]
    assert liee and liee[0]["personne_morale_liee"] == cascade_ids["holding_x"]

    # Participation créée par l'admin (ex. pour y rattacher des apports) :
    # visible d'office (plus de « masqué par défaut »).
    r = client.post(
        "/api/v1/invest/admin/participations",
        headers=auth_headers,
        json={
            "entreprise_id": eid,
            "user_id": cascade_ids["vincent"],
            "parts_pct": 99,  # ignoré : la fiche entreprise fait foi
        },
    )
    assert r.status_code == 201, r.text
    part_id = r.json()["id"]
    assert r.json()["masque"] is False
    r = client.get(
        f"/api/v1/invest/me/projets/{eid}",
        headers=_headers(cascade_ids["vincent"]),
    )
    assert r.status_code == 200 and r.json()["parts_pct"] == 25.0

    # Masquer → 404 pour Vincent, Éric n'est pas touché.
    r = client.patch(
        f"/api/v1/invest/admin/participations/{part_id}",
        headers=auth_headers,
        json={"masque": True},
    )
    assert r.status_code == 200 and r.json()["masque"] is True
    r = client.get(
        f"/api/v1/invest/me/projets/{eid}",
        headers=_headers(cascade_ids["vincent"]),
    )
    assert r.status_code == 404
    r = client.get(
        "/api/v1/invest/me/portefeuille",
        headers=_headers(cascade_ids["vincent"]),
    )
    assert {p["entreprise_id"] for p in r.json()["projets"]} == {
        cascade_ids["projet_b"]
    }
    r = client.get(
        f"/api/v1/invest/me/projets/{eid}",
        headers=_headers(cascade_ids["eric"]),
    )
    assert r.status_code == 200

    # Démasquer.
    r = client.patch(
        f"/api/v1/invest/admin/participations/{part_id}",
        headers=auth_headers,
        json={"masque": False},
    )
    assert r.status_code == 200
    r = client.get(
        f"/api/v1/invest/me/projets/{eid}",
        headers=_headers(cascade_ids["vincent"]),
    )
    assert r.status_code == 200


def test_apercu_partenaire_sans_compte_suit_la_cascade(
    client, auth_headers, cascade_ids, run
):
    """Un actionnaire SANS compte (par son nom dans la fiche) : l'aperçu
    admin montre le portefeuille qu'il aura, cascade comprise."""

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            pr = EntreprisePartner(
                entreprise_id=cascade_ids["holding_y"],
                partner_name="Sans Compte Cascade",
                ownership_pct=50,
            )
            s.add(pr)
            await s.commit()
            return pr.id

    partner_id = run(_seed())
    r = client.get(
        f"/api/v1/invest/admin/apercu-partenaire/{partner_id}/portefeuille",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    projets = {p["entreprise_id"]: p for p in r.json()["projets"]}
    # 50 % × 40 % = 20 % de Projet B.
    assert projets[cascade_ids["projet_b"]]["parts_pct"] == 20.0
    r = client.get(
        f"/api/v1/invest/admin/apercu-partenaire/{partner_id}/projets/"
        f"{cascade_ids['projet_a']}",
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_participation_orpheline_reste_visible(client, auth_headers, cascade_ids, run):
    """Une participation saisie à la main (personne absente de la fiche)
    garde son % saisi et reste visible — rien n'est perdu."""

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = User(
                email="orphelin.cascade@smoke.test",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=False,
                role="employee",
                volets_json='["investisseur"]',
            )
            s.add(u)
            await s.flush()
            s.add(
                InvestParticipation(
                    user_id=u.id,
                    entreprise_id=cascade_ids["projet_b"],
                    parts_pct=12.5,
                )
            )
            await s.commit()
            return u.id

    uid = run(_seed())
    r = client.get("/api/v1/invest/me/portefeuille", headers=_headers(uid))
    assert r.status_code == 200, r.text
    assert [p["parts_pct"] for p in r.json()["projets"]] == [12.5]
    assert r.json()["projets"][0]["chemins"] == []
