"""Smoke — tout le matériel refacturé sur UNE ligne « Matériaux » (2026-10-17).

Steven : « les achats de matériels sur les factures apparaissent comme
facture -146. Tous les matériaux ajoutés devraient s'additionner et
apparaître sur une seule ligne. »

Couvre :
1. création depuis le projet : matériel, outils et location d'outils
   s'additionnent (majoration comprise) sur une ligne « Matériaux » ; la
   facture de sous-traitant garde sa ligne ; le détail des achats regroupés
   est lisible sous la ligne (fournisseur, no, coût, montant refacturé) ;
2. un achat importé plus tard (« Ajouter des sources », bouton
   « Refacturer » de la page À refacturer) s'ajoute à CETTE ligne ;
3. import d'un bon : « <demande du bon> / Matériaux » ;
4. supprimer la ligne libère tous ses achats ;
5. regroupement one-shot des brouillons existants (« Matériel — facture
   -146 » par achat) ; factures envoyées et lignes manuelles intactes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, update

from app.models.achat import Achat
from app.models.bon_travail import BonTravail
from app.models.client import Client
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.services.facture_lignes import regrouper_materiaux_brouillons
from tests.smoke.conftest import TestSessionLocal


@pytest.fixture()
def chantier(run, db_setup):
    """Projet sans soumission avec trois achats de matériel Rona
    (100 $ +10 %, 200 $ +10 %, outils 50 $ au coûtant) et une facture de
    sous-traitant (500 $ au coûtant)."""
    crees: list[dict] = []

    def _creer() -> dict:
        async def _go() -> dict:
            async with TestSessionLocal() as s:
                tag = uuid.uuid4().hex[:8]
                cl = Client(name=f"Client mat {tag}")
                fo = Fournisseur(name=f"Rona {tag}")
                s.add_all([cl, fo])
                await s.flush()
                proj = Project(name=f"Chantier mat {tag}", client_id=cl.id)
                s.add(proj)
                await s.flush()
                achats = [
                    Achat(
                        project_id=proj.id,
                        fournisseur_id=fo.id,
                        description="facture -146",
                        supplier_invoice_number="146",
                        amount=100,
                        kind="material",
                        is_billable=True,
                        markup_percent=10,
                    ),
                    Achat(
                        project_id=proj.id,
                        fournisseur_id=fo.id,
                        description="facture -147",
                        supplier_invoice_number="147",
                        amount=200,
                        kind="material",
                        is_billable=True,
                        markup_percent=10,
                    ),
                    Achat(
                        project_id=proj.id,
                        description="Scie",
                        amount=50,
                        kind="tools",
                        is_billable=True,
                        markup_percent=0,
                    ),
                    Achat(
                        project_id=proj.id,
                        description="Électricien",
                        amount=500,
                        kind="sub_invoice",
                        is_billable=True,
                        markup_percent=0,
                    ),
                ]
                s.add_all(achats)
                await s.commit()
                ids = {
                    "client": cl.id,
                    "fournisseur": fo.id,
                    "projet": proj.id,
                    "achats": [a.id for a in achats],
                }
                crees.append(ids)
                return ids

        return run(_go())

    yield _creer

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            for ids in crees:
                pids = (
                    await s.execute(
                        select(Project.id).where(
                            Project.client_id == ids["client"]
                        )
                    )
                ).scalars().all()
                fac_ids = (
                    await s.execute(
                        select(Facture.id).where(
                            Facture.client_id == ids["client"]
                        )
                    )
                ).scalars().all()
                await s.execute(delete(Achat).where(Achat.project_id.in_(pids)))
                await s.execute(
                    delete(BonTravail).where(BonTravail.client_id == ids["client"])
                )
                if fac_ids:
                    await s.execute(
                        delete(FactureItem).where(
                            FactureItem.facture_id.in_(fac_ids)
                        )
                    )
                    await s.execute(delete(Facture).where(Facture.id.in_(fac_ids)))
                await s.execute(delete(Project).where(Project.id.in_(pids)))
                await s.execute(
                    delete(Fournisseur).where(Fournisseur.id == ids["fournisseur"])
                )
                await s.execute(delete(Client).where(Client.id == ids["client"]))
            await s.commit()

    run(_nettoyer())


def _creer_facture(client, headers, projet_id: int, achats: bool) -> int:
    r = client.post(
        f"/api/v1/projects/{projet_id}/convert-to-facture",
        json={
            "include_soumission": False,
            "include_hours": False,
            "include_achats": achats,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


def _items(client, headers, fid: int) -> list[dict]:
    r = client.get(f"/api/v1/factures/{fid}/items", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _ajouter_achat(run, projet_id: int, montant: float, kind="material") -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            a = Achat(
                project_id=projet_id,
                description=f"facture -{int(montant)}",
                amount=montant,
                kind=kind,
                is_billable=True,
                markup_percent=10,
            )
            s.add(a)
            await s.commit()
            return a.id

    return run(_go())


def test_creation_une_ligne_materiaux(chantier, client, auth_headers):
    ids = chantier()
    fid = _creer_facture(client, auth_headers, ids["projet"], achats=True)
    items = _items(client, auth_headers, fid)

    assert sorted((i["description"], i["total"]) for i in items) == [
        ("Matériaux", 380.0),  # 110 + 220 + 50
        ("Sous-traitant — Électricien", 500.0),
    ]
    mat = next(i for i in items if i["description"] == "Matériaux")
    assert (mat["kind"], mat["quantity"], mat["unit_price"]) == (
        "materiaux",
        1.0,
        380.0,
    )
    detail = {a["id"]: a for a in mat["achats"]}
    assert set(detail) == set(ids["achats"][:3])
    a146 = detail[ids["achats"][0]]
    assert a146["fournisseur"].startswith("Rona")
    assert a146["supplier_invoice_number"] == "146"
    assert (a146["amount"], a146["montant_refacture"]) == (100.0, 110.0)

    fac = client.get(f"/api/v1/factures/{fid}", headers=auth_headers).json()
    assert fac["subtotal"] == 880.0


def test_achats_ajoutes_plus_tard_sur_la_meme_ligne(
    chantier, client, auth_headers, run
):
    ids = chantier()
    fid = _creer_facture(client, auth_headers, ids["projet"], achats=True)

    # « Ajouter des sources » : l'achat s'additionne, aucune ligne en plus.
    nouveau = _ajouter_achat(run, ids["projet"], 1000)
    r = client.post(
        f"/api/v1/factures/{fid}/import-sources",
        json={"include_achats": True, "achat_ids": [nouveau]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 0
    items = _items(client, auth_headers, fid)
    assert len(items) == 2
    mat = next(i for i in items if i["description"] == "Matériaux")
    assert mat["total"] == 1480.0
    assert len(mat["achats"]) == 4

    # Bouton « Refacturer » de la page À refacturer, facture existante.
    encore = _ajouter_achat(run, ids["projet"], 20)
    r = client.post(
        "/api/v1/achats-a-refacturer/facturer",
        json={"achat_ids": [encore], "facture_id": fid},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    items = _items(client, auth_headers, fid)
    assert len(items) == 2
    mat = next(i for i in items if i["description"] == "Matériaux")
    assert mat["total"] == 1502.0
    fac = client.get(f"/api/v1/factures/{fid}", headers=auth_headers).json()
    assert fac["subtotal"] == 2002.0

    # Supprimer la ligne libère TOUS ses achats.
    r = client.delete(
        f"/api/v1/factures/{fid}/items/{mat['id']}", headers=auth_headers
    )
    assert r.status_code == 204

    async def _libres() -> list:
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(Achat.id).where(
                        Achat.project_id == ids["projet"],
                        Achat.invoiced_at.is_(None),
                    )
                )
            ).scalars().all()

    assert len(run(_libres())) == 5


def test_import_d_un_bon(chantier, client, auth_headers, run):
    ids = chantier()
    fid = _creer_facture(client, auth_headers, ids["projet"], achats=False)

    async def _bon() -> int:
        async with TestSessionLocal() as s:
            tag = uuid.uuid4().hex[:8]
            proj = Project(
                name=f"BT {tag}", client_id=ids["client"], kind="bon_travail"
            )
            s.add(proj)
            await s.flush()
            bon = BonTravail(
                reference=f"BT-MAT-{tag}",
                title="Robinet",
                client_id=ids["client"],
                project_id=proj.id,
                status="complete_a_refacturer",
            )
            s.add(bon)
            for montant in (40, 60):
                s.add(
                    Achat(
                        project_id=proj.id,
                        description=f"facture -{montant}",
                        amount=montant,
                        kind="material",
                        is_billable=True,
                        markup_percent=0,
                    )
                )
            await s.commit()
            return bon.id

    bon_id = run(_bon())
    r = client.post(
        f"/api/v1/factures/{fid}/import-bon",
        json={"bon_id": bon_id},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 1
    items = _items(client, auth_headers, fid)
    assert len(items) == 1
    assert items[0]["description"].endswith("\nMatériaux")
    assert items[0]["total"] == 100.0
    assert len(items[0]["achats"]) == 2


def test_regroupement_des_brouillons_existants(
    chantier, client, auth_headers, run
):
    """Factures créées AVANT le correctif : une ligne par achat."""
    ids = chantier()
    brouillon = _creer_facture(client, auth_headers, ids["projet"], achats=False)
    envoyee = _creer_facture(client, auth_headers, ids["projet"], achats=False)
    a146, a147, scie, elec = ids["achats"]

    async def _ancien_etat() -> None:
        async with TestSessionLocal() as s:
            def ligne(fid, pos, desc, total, kind="materiaux"):
                return FactureItem(
                    facture_id=fid,
                    position=pos,
                    description=desc,
                    unit="lot",
                    quantity=1,
                    unit_price=total,
                    total=total,
                    kind=kind,
                )

            l146 = ligne(brouillon, 0, "Matériel — facture -146", 110)
            l147 = ligne(brouillon, 1, "Matériel — facture -147", 225)
            lscie = ligne(brouillon, 2, "Outils — Scie", 50)
            lelec = ligne(
                brouillon, 3, "Sous-traitant — Électricien", 500, "service"
            )
            manuelle = ligne(brouillon, 4, "Quincaillerie", 30)
            s.add_all([l146, l147, lscie, lelec, manuelle])
            await s.flush()
            for aid, it in ((a146, l146), (a147, l147), (scie, lscie), (elec, lelec)):
                await s.execute(
                    update(Achat)
                    .where(Achat.id == aid)
                    .values(facture_item_id=it.id)
                )
            # Facture envoyée : un achat sur sa propre ligne, intacte.
            a_env = Achat(
                project_id=ids["projet"],
                description="facture -150",
                amount=10,
                kind="material",
            )
            l_env = ligne(envoyee, 0, "Matériel — facture -150", 11)
            s.add_all([a_env, l_env])
            await s.flush()
            a_env.facture_item_id = l_env.id
            await s.execute(
                update(Facture).where(Facture.id == envoyee).values(status="sent")
            )
            await s.commit()

    run(_ancien_etat())

    async def _regrouper() -> int:
        async with TestSessionLocal() as s:
            n = await regrouper_materiaux_brouillons(s)
            await s.commit()
            return n

    assert run(_regrouper()) == 2

    items = _items(client, auth_headers, brouillon)
    assert sorted((i["description"], i["total"]) for i in items) == [
        ("Matériaux", 385.0),  # retouche à la main (225) conservée
        ("Quincaillerie", 30.0),
        ("Sous-traitant — Électricien", 500.0),
    ]
    mat = next(i for i in items if i["description"] == "Matériaux")
    assert {a["id"] for a in mat["achats"]} == {a146, a147, scie}
    assert {a["montant_refacture"] for a in mat["achats"]} == {110.0, 225.0, 50.0}

    assert [i["description"] for i in _items(client, auth_headers, envoyee)] == [
        "Matériel — facture -150"
    ]
    # Rejouer ne change plus rien.
    assert run(_regrouper()) == 0
