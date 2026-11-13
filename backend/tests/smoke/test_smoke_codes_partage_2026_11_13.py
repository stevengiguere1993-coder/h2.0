"""Smoke — Partage contrôlé des codes d'accès (Steven 2026-11-13).

« Je ne peux pas donner accès au code à tous mes employés […] le
gestionnaire des projets a accès à la liste de codes, il peut envoyer à
un employé le code d'un endroit avec un nombre de jours défini, ou le
laisser accessible jusqu'à la fin d'un BT ou d'un projet. »

- codes cachés dans les listes, « Afficher » journalisé ;
- type, emplacement, photos (ajout réservé aux gestionnaires) ;
- partage : jours, date, BT, projet ; portée code / logement / immeuble ;
- assigner un BT rattaché à un logement donne l'accès jusqu'à la fin du
  BT (sauf ``donner_acces_codes: false``) ; réassigner le retire à
  l'ancien ;
- filet horaire : fermeture notée, alerte « compte désactivé ».
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, get_password_hash
from app.models.code_acces import CodeAccesConsultation, CodeAccesPartage
from app.models.immobilier import Immeuble, Logement
from app.models.notification import Notification
from app.models.project import Project
from app.models.user import User
from tests.smoke.conftest import TestSessionLocal

IMM = "/api/v1/immobilier/immeubles"
LOG = "/api/v1/immobilier/logements"
CA = "/api/v1/codes-acces"


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(subject=str(uid))}"}


@pytest.fixture(scope="module")
def seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Partage codes", address="55 rue Partage",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            lgs = [Logement(immeuble_id=imm.id, numero=n) for n in ("1", "2", "3")]
            # Employé de Construction : pas de volet Immobilier.
            emp = User(
                email="smoke-partage-emp@example.com",
                hashed_password=get_password_hash("Sm0kePartage!42"),
                is_active=True, is_admin=False, role="employee",
                volets_json='["construction"]', first_name="Émile",
            )
            emp2 = User(
                email="smoke-partage-emp2@example.com",
                hashed_password=get_password_hash("Sm0kePartage!42"),
                is_active=True, is_admin=False, role="employee",
                volets_json='["construction"]',
            )
            pj = Project(name="Réno partage", status="in_progress")
            s.add_all([*lgs, emp, emp2, pj])
            await s.commit()
            return {
                "imm": imm.id, "lg1": lgs[0].id, "lg2": lgs[1].id,
                "lg3": lgs[2].id, "emp": emp.id, "emp2": emp2.id, "pj": pj.id,
            }

    return run(_seed())


@pytest.fixture(scope="module")
def codes(client, auth_headers, seed) -> dict:
    r = client.post(f"{IMM}/{seed['imm']}/codes", headers=auth_headers,
                    json={"libelle": "Porte d'entrée", "code": "1111#",
                          "type_code": "porte_entree"})
    assert r.status_code == 201, r.text
    entree = r.json()
    r = client.post(f"{LOG}/{seed['lg1']}/codes", headers=auth_headers,
                    json={"libelle": "Boîte à clés", "code": "0420",
                          "type_code": "boite_cles",
                          "emplacement": "  Garde-corps arrière, à gauche "})
    assert r.status_code == 201, r.text
    boite = r.json()
    assert boite["code"] == "0420" and boite["emplacement"] == "Garde-corps arrière, à gauche"
    r = client.post(f"{LOG}/{seed['lg2']}/codes", headers=auth_headers,
                    json={"libelle": "Porte", "code": "2222", "type_code": "porte_unite"})
    lg2 = r.json()
    r = client.post(f"{LOG}/{seed['lg3']}/codes", headers=auth_headers,
                    json={"libelle": "Porte", "code": "3333", "type_code": "porte_unite"})
    lg3 = r.json()
    return {"entree": entree["id"], "boite": boite["id"], "lg2": lg2["id"], "lg3": lg3["id"]}


def test_type_inconnu_et_liste_cachee(client, auth_headers, seed, codes):
    assert client.post(f"{IMM}/{seed['imm']}/codes", headers=auth_headers,
                       json={"libelle": "x", "code": "1", "type_code": "fenetre"}).status_code == 422
    rows = client.get(f"{LOG}/{seed['lg1']}/codes", headers=auth_headers).json()
    assert rows[0]["code"] is None and rows[0]["code_masque"] is True
    assert rows[0]["type_code"] == "boite_cles"
    # Le gestionnaire affiche : journalisé « gestion ».
    r = client.post(f"{CA}/codes/{codes['boite']}/afficher", headers=auth_headers)
    assert r.status_code == 200 and r.json()["code"] == "0420"


def test_photos(client, auth_headers, seed, codes):
    emp = _h(seed["emp"])
    files = {"file": ("boite.jpg", b"\xff\xd8\xff fake jpeg", "image/jpeg")}
    assert client.post(f"{CA}/codes/{codes['boite']}/photos", headers=emp, files=files).status_code == 403
    r = client.post(f"{CA}/codes/{codes['boite']}/photos", headers=auth_headers, files=files)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    bad = {"file": ("x.txt", b"hello", "text/plain")}
    assert client.post(f"{CA}/codes/{codes['boite']}/photos", headers=auth_headers, files=bad).status_code == 415
    rows = client.get(f"{LOG}/{seed['lg1']}/codes", headers=auth_headers).json()
    assert [p["id"] for p in rows[0]["photos"]] == [pid]
    # Sans partage, l'employé ne voit ni la photo ni le code.
    assert client.get(f"{CA}/codes/{codes['boite']}/photos/{pid}", headers=emp).status_code == 403
    assert client.post(f"{CA}/codes/{codes['boite']}/afficher", headers=emp).status_code == 403
    r = client.get(f"{CA}/codes/{codes['boite']}/photos/{pid}", headers=auth_headers)
    assert r.status_code == 200 and r.content.startswith(b"\xff\xd8")


def test_bt_donne_acces_jusqu_a_la_fin(client, auth_headers, seed, codes, run):
    emp = _h(seed["emp"])
    assert client.get(f"{CA}/moi", headers=emp).json() == []
    r = client.post("/api/v1/bons-travail", headers=auth_headers, json={
        "title": "Fuite sous l'évier", "kind": "interne",
        "immeuble_id": seed["imm"], "logement_id": seed["lg1"],
        "assignee_user_id": seed["emp"], "status": "planifie",
    })
    assert r.status_code == 201, r.text
    bon = r.json()

    moi = client.get(f"{CA}/moi", headers=emp).json()
    assert len(moi) == 1
    acces = moi[0]
    assert acces["partage"]["mode"] == "bt" and acces["partage"]["bon_travail_id"] == bon["id"]
    assert "jusqu'à la fin du BT" in acces["partage"]["fin_texte"]
    # Codes du logement ET de l'immeuble, cachés.
    assert {c["id"] for c in acces["codes"]} == {codes["entree"], codes["boite"]}
    assert all(c["code"] is None for c in acces["codes"])
    r = client.post(f"{CA}/codes/{codes['boite']}/afficher", headers=emp)
    assert r.status_code == 200 and r.json()["code"] == "0420"
    # Pas le code d'un autre logement.
    assert client.post(f"{CA}/codes/{codes['lg2']}/afficher", headers=emp).status_code == 403
    # Bloc « Accès » de la fiche du BT.
    r = client.get(f"{CA}/bons/{bon['id']}", headers=emp).json()
    assert {c["id"] for c in r["codes"]} == {codes["entree"], codes["boite"]}
    assert r["gestionnaire"] is False and "fin du BT" in r["fin_texte"]
    r = client.get(f"{CA}/bons/{bon['id']}", headers=auth_headers).json()
    assert r["gestionnaire"] is True and len(r["partages"]) == 1

    async def _journal():
        async with TestSessionLocal() as s:
            rows = (await s.execute(select(CodeAccesConsultation).where(
                CodeAccesConsultation.code_id == codes["boite"]))).scalars().all()
            notifs = (await s.execute(select(Notification).where(
                Notification.user_id == seed["emp"],
                Notification.kind == "code_acces_partage"))).scalars().all()
            return sorted(r.via for r in rows), len(notifs)

    vias, n = run(_journal())
    assert vias == ["gestion", "partage"] and n == 1
    j = client.get(f"{CA}/consultations?code_id={codes['boite']}", headers=auth_headers).json()
    assert {x["via"] for x in j} == {"gestion", "partage"}
    assert client.get(f"{CA}/consultations", headers=emp).status_code == 403

    # BT complété → l'accès se ferme tout seul.
    r = client.patch(f"/api/v1/bons-travail/{bon['id']}", headers=auth_headers,
                     json={"status": "complete_a_refacturer"})
    assert r.status_code == 200, r.text
    assert client.get(f"{CA}/moi", headers=emp).json() == []
    assert client.post(f"{CA}/codes/{codes['boite']}/afficher", headers=emp).status_code == 403

    from app.services.codes_acces import filet_partages

    async def _filet():
        async with TestSessionLocal() as s:
            out = await filet_partages(s)
            await s.commit()
            p = (await s.execute(select(CodeAccesPartage).where(
                CodeAccesPartage.bon_travail_id == bon["id"]))).scalar_one()
            return out, p.ferme_motif

    out, motif = run(_filet())
    assert out["fermes"] >= 1 and motif == "fin_bt"


def test_bt_sans_acces_et_reassignation(client, auth_headers, seed, codes):
    emp, emp2 = _h(seed["emp"]), _h(seed["emp2"])
    r = client.post("/api/v1/bons-travail", headers=auth_headers, json={
        "title": "Peinture", "kind": "interne",
        "immeuble_id": seed["imm"], "logement_id": seed["lg2"],
        "assignee_user_id": seed["emp"], "donner_acces_codes": False,
    })
    assert r.status_code == 201, r.text
    bon = r.json()
    assert client.get(f"{CA}/moi", headers=emp).json() == []
    # Réassigné à emp2 (case cochée par défaut) → emp2 a l'accès.
    r = client.patch(f"/api/v1/bons-travail/{bon['id']}", headers=auth_headers,
                     json={"assignee_user_id": seed["emp2"]})
    assert r.status_code == 200, r.text
    moi2 = client.get(f"{CA}/moi", headers=emp2).json()
    assert [c["id"] for c in moi2[0]["codes"]] == [codes["entree"], codes["lg2"]]
    # Réassigné à emp → emp2 perd l'accès, emp le reçoit.
    client.patch(f"/api/v1/bons-travail/{bon['id']}", headers=auth_headers,
                 json={"assignee_user_id": seed["emp"]})
    assert client.get(f"{CA}/moi", headers=emp2).json() == []
    assert len(client.get(f"{CA}/moi", headers=emp).json()) == 1
    tous = client.get(f"{CA}/partages?bon_travail_id={bon['id']}&actifs=false",
                      headers=auth_headers).json()
    assert {(p["user_id"], p["actif"], p["raison_fin"]) for p in tous} == {
        (seed["emp2"], False, "reassigne"), (seed["emp"], True, None),
    }
    client.patch(f"/api/v1/bons-travail/{bon['id']}", headers=auth_headers,
                 json={"status": "cancelled"})


def test_partage_manuel_jours_date_projet_code(client, auth_headers, seed, codes):
    emp2 = _h(seed["emp2"])
    base = {"user_ids": [seed["emp2"]]}
    # Employé : pas le droit de partager.
    assert client.post(f"{CA}/partages", headers=emp2,
                       json={**base, "immeuble_id": seed["imm"], "mode": "jours", "jours": 1}).status_code == 403
    # Durées invalides.
    assert client.post(f"{CA}/partages", headers=auth_headers,
                       json={**base, "immeuble_id": seed["imm"], "mode": "date", "fin_le": "2020-01-01"}).status_code == 422
    assert client.post(f"{CA}/partages", headers=auth_headers,
                       json={**base, "immeuble_id": seed["imm"], "mode": "bt"}).status_code == 422
    assert client.post(f"{CA}/partages", headers=auth_headers,
                       json={**base, "immeuble_id": seed["imm"], "mode": "jours", "jours": 0}).status_code == 422
    # Un seul code (logement 3), 3 jours.
    r = client.post(f"{CA}/partages", headers=auth_headers,
                    json={**base, "code_id": codes["lg3"], "mode": "jours", "jours": 3,
                          "motif": "Visite plombier"})
    assert r.status_code == 201, r.text
    p = r.json()[0]
    assert p["code_id"] == codes["lg3"] and p["logement_id"] == seed["lg3"]
    assert p["fin_texte"].startswith("jusqu'au ") and p["actif"]
    moi = client.get(f"{CA}/moi", headers=emp2).json()
    assert [c["id"] for c in moi[0]["codes"]] == [codes["lg3"]]
    assert client.post(f"{CA}/codes/{codes['entree']}/afficher", headers=emp2).status_code == 403
    # Retrait manuel.
    r = client.post(f"{CA}/partages/{p['id']}/retirer", headers=auth_headers)
    assert r.status_code == 200 and r.json()["actif"] is False
    assert client.get(f"{CA}/moi", headers=emp2).json() == []
    # Projet en cours → accès ; liste des accès du logement.
    r = client.post(f"{CA}/partages", headers=auth_headers,
                    json={**base, "logement_id": seed["lg3"], "mode": "projet",
                          "project_id": seed["pj"]})
    assert r.status_code == 201, r.text
    assert "Réno partage" in r.json()[0]["fin_texte"]
    actifs = client.get(f"{CA}/partages?logement_id={seed['lg3']}", headers=auth_headers).json()
    assert [a["mode"] for a in actifs] == ["projet"]
    ctx = client.get(f"{CA}/contexte?logement_id={seed['lg3']}", headers=auth_headers).json()
    assert ctx["immeuble_id"] == seed["imm"]
    assert any(e["id"] == seed["emp2"] and not e["voit_deja"] for e in ctx["employes"])
    assert any(pj["id"] == seed["pj"] for pj in ctx["projets"])


def test_compte_desactive_alerte(client, auth_headers, seed, run):
    from app.services.codes_acces import filet_partages

    async def _desactiver_et_filet():
        async with TestSessionLocal() as s:
            u = await s.get(User, seed["emp2"])
            u.is_active = False
            await s.commit()
            out = await filet_partages(s)
            await s.commit()
            again = await filet_partages(s)
            await s.commit()
            notifs = (await s.execute(select(Notification).where(
                Notification.kind == "code_acces_compte_desactive"))).scalars().all()
            ouverts = (await s.execute(select(CodeAccesPartage).where(
                CodeAccesPartage.user_id == seed["emp2"],
                CodeAccesPartage.ferme_le.is_(None)))).scalars().all()
            return out, again, len(notifs), len(ouverts)

    out, again, n, ouverts = run(_desactiver_et_filet())
    assert out["alertes"] == 1 and again["alertes"] == 0
    assert n >= 1 and ouverts == 0


def test_mcp_partages(client, api_key_headers):
    from app.core.api_ia_couverture import TABLES_COUVERTES

    assert {"imm_code_partages", "imm_code_consultations", "imm_code_photos"} <= TABLES_COUVERTES
    r = client.get("/api/v1/activity/entities/code_partages", headers=api_key_headers)
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1
    assert r.json()["items"][0]["entity_type"] == "imm_code_partage"
    r = client.get("/api/v1/activity/entities/code_consultations", headers=api_key_headers)
    assert r.status_code == 200 and r.json()["count"] >= 1
