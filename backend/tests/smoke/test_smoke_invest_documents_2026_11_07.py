"""Smoke — documents de l'espace investisseur (Steven, 2026-11-07) :
documents PRIVÉS par investisseur, DÉPÔT par l'investisseur lui-même
(signalé aux admins), types au-delà du PDF, onglet « Mes documents ».
"""
from __future__ import annotations

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.entreprise import Entreprise, EntreprisePartner
from app.models.immobilier import Immeuble
from app.models.notification import Notification
from app.models.user import User

from .conftest import TestSessionLocal

PDF = b"%PDF-1.4 doc investisseur"
PNG = b"\x89PNG\r\n\x1a\n fausse image"


@pytest.fixture(scope="module")
def doc_ids(run, db_setup) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            ent = Entreprise(name="INC Documents Invest")
            s.add(ent)
            await s.flush()
            s.add(
                Immeuble(
                    name="Imm Documents",
                    address="3 rue Documents",
                    city="Montréal",
                    is_active=True,
                    owner_entreprise_id=ent.id,
                    purchase_price=800_000,
                )
            )
            a = User(
                email="doc.alice@example.com",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=False,
                role="investisseur",
                volets_json='["investisseur"]',
                first_name="Alice",
                last_name="Documents",
            )
            b = User(
                email="doc.bob@example.com",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=False,
                role="investisseur",
                volets_json='["investisseur"]',
                first_name="Bob",
                last_name="Documents",
            )
            etranger = User(
                email="doc.etranger@example.com",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=False,
                role="investisseur",
                volets_json='["investisseur"]',
            )
            s.add_all([a, b, etranger])
            await s.flush()
            s.add_all(
                [
                    EntreprisePartner(
                        entreprise_id=ent.id, user_id=a.id,
                        partner_name="Alice Documents", ownership_pct=50,
                    ),
                    EntreprisePartner(
                        entreprise_id=ent.id, user_id=b.id,
                        partner_name="Bob Documents", ownership_pct=50,
                    ),
                ]
            )
            await s.commit()
            return {
                "ent": ent.id,
                "alice": a.id,
                "bob": b.id,
                "etranger": etranger.id,
            }

    return run(_seed())


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(subject=str(uid))}"}


def test_admin_partage_et_prive(client, auth_headers, doc_ids):
    eid = doc_ids["ent"]
    # Partagé à la compagnie (PDF).
    r = client.post(
        f"/api/v1/invest/admin/projets/{eid}/documents",
        headers=auth_headers,
        files={"file": ("Convention 2026.pdf", PDF, "application/pdf")},
    )
    assert r.status_code == 201, r.text
    partage = r.json()
    assert partage["prive"] is False and partage["extension"] == "pdf"

    # Privé à Alice (image PNG + note).
    r = client.post(
        f"/api/v1/invest/admin/projets/{eid}/documents",
        headers=auth_headers,
        files={"file": ("Releve Alice.png", PNG, "image/png")},
        data={"destinataire_user_id": str(doc_ids["alice"]), "note": "À signer"},
    )
    assert r.status_code == 201, r.text
    prive = r.json()
    assert prive["prive"] is True
    assert prive["destinataire_name"] == "Alice Documents"
    assert prive["note"] == "À signer" and prive["extension"] == "png"

    # Type refusé.
    r = client.post(
        f"/api/v1/invest/admin/projets/{eid}/documents",
        headers=auth_headers,
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 415, r.text

    # Destinataire qui ne voit pas le projet → 422.
    r = client.post(
        f"/api/v1/invest/admin/projets/{eid}/documents",
        headers=auth_headers,
        files={"file": ("x.pdf", PDF, "application/pdf")},
        data={"destinataire_user_id": str(doc_ids["etranger"])},
    )
    assert r.status_code == 422, r.text

    # La console liste les deux avec leur portée.
    r = client.get(f"/api/v1/invest/admin/projets/{eid}", headers=auth_headers)
    docs = {d["id"]: d for d in r.json()["documents"]}
    assert docs[partage["id"]]["prive"] is False
    assert docs[prive["id"]]["destinataire_user_id"] == doc_ids["alice"]

    # Alice voit les deux ; Bob ne voit que le partagé.
    r = client.get(f"/api/v1/invest/me/projets/{eid}", headers=_h(doc_ids["alice"]))
    assert {d["id"] for d in r.json()["documents"]} == {partage["id"], prive["id"]}
    r = client.get(f"/api/v1/invest/me/projets/{eid}", headers=_h(doc_ids["bob"]))
    assert {d["id"] for d in r.json()["documents"]} == {partage["id"]}

    # Le fichier privé : Alice oui (image servie telle quelle), Bob 404.
    r = client.get(
        f"/api/v1/invest/me/documents/{prive['id']}/pdf",
        headers=_h(doc_ids["alice"]),
    )
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"].startswith("image/png")
    assert 'filename="Releve Alice.png"' in r.headers["content-disposition"]
    r = client.get(
        f"/api/v1/invest/me/documents/{prive['id']}/pdf",
        headers=_h(doc_ids["bob"]),
    )
    assert r.status_code == 404
    # Étranger au projet : même le partagé est fermé.
    r = client.get(
        f"/api/v1/invest/me/documents/{partage['id']}/pdf",
        headers=_h(doc_ids["etranger"]),
    )
    assert r.status_code == 404


def test_depot_par_l_investisseur(client, auth_headers, doc_ids, run):
    eid = doc_ids["ent"]
    r = client.post(
        f"/api/v1/invest/me/projets/{eid}/documents",
        headers=_h(doc_ids["bob"]),
        files={"file": ("Permis Bob.pdf", PDF, "application/pdf")},
        data={"note": "Pièce demandée"},
    )
    assert r.status_code == 201, r.text
    depot = r.json()
    assert depot["source"] == "investisseur"
    assert depot["prive"] is True and depot["depose_par_moi"] is True
    assert depot["destinataire_user_id"] == doc_ids["bob"]

    # Les admins sont prévenus (cloche).
    async def _notifs():
        async with TestSessionLocal() as s:
            from sqlalchemy import select

            return list(
                (
                    await s.execute(
                        select(Notification).where(
                            Notification.kind == "invest_document_depose"
                        )
                    )
                ).scalars()
            )

    notifs = run(_notifs())
    assert notifs and "Bob Documents" in notifs[0].title
    assert "Permis Bob" in (notifs[0].body or "")

    # Alice (co-actionnaire) ne le voit pas ; l'admin oui, avec le nom.
    r = client.get(f"/api/v1/invest/me/projets/{eid}", headers=_h(doc_ids["alice"]))
    assert depot["id"] not in {d["id"] for d in r.json()["documents"]}
    r = client.get(f"/api/v1/invest/admin/projets/{eid}", headers=auth_headers)
    adm = {d["id"]: d for d in r.json()["documents"]}[depot["id"]]
    assert adm["depose_par_investisseur"] is True
    assert adm["depose_par_name"] == "Bob Documents"
    r = client.get(
        f"/api/v1/invest/admin/documents/{depot['id']}/pdf", headers=auth_headers
    )
    assert r.status_code == 200 and r.content == PDF

    # « Mes documents » de Bob : le partagé + son dépôt, plus récent d'abord.
    r = client.get("/api/v1/invest/me/documents", headers=_h(doc_ids["bob"]))
    assert r.status_code == 200, r.text
    mes = r.json()
    assert mes[0]["id"] == depot["id"]
    assert all(d["entreprise_name"] == "INC Documents Invest" for d in mes)
    assert len(mes) == 2

    # Un dépôt hors de ses projets est refusé.
    r = client.post(
        f"/api/v1/invest/me/projets/{eid}/documents",
        headers=_h(doc_ids["etranger"]),
        files={"file": ("x.pdf", PDF, "application/pdf")},
    )
    assert r.status_code == 404

    # Bob retire SON dépôt ; Alice ne peut pas retirer ce qui n'est pas à elle.
    r = client.delete(
        f"/api/v1/invest/me/documents/{depot['id']}", headers=_h(doc_ids["alice"])
    )
    assert r.status_code == 404
    r = client.delete(
        f"/api/v1/invest/me/documents/{depot['id']}", headers=_h(doc_ids["bob"])
    )
    assert r.status_code == 204
    r = client.get("/api/v1/invest/me/documents", headers=_h(doc_ids["bob"]))
    assert len(r.json()) == 1
