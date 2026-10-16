"""Smoke — page « À refacturer » (Steven 2026-10-16).

« J'ai besoin d'un endroit dans Kratos qui me mentionne quand un reçu
d'achat est ajouté après la facture finale dans un projet, quand un BT
est fermé et que l'achat n'a pas été refacturé dans la facture du BT. »

Couvre :
1. détection : reçu arrivé APRÈS la facture finale émise (et pas
   avant, ni non refacturable, ni déjà refacturé) ; achat d'un BT fermé
   (y compris non coché par défaut, mais pas exclu à la main) ; rien
   pour un BT encore « à refacturer » ;
2. « Ne pas refacturer » : raison exigée, trace qui / quand / pourquoi,
   l'achat sort de la liste ; « Rétablir » le remet ;
3. « Refacturer » : sur une facture neuve (brouillon du projet) ou sur
   une facture existante du projet → l'achat sort de la liste ;
4. réservé aux admins.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.models.achat import Achat
from app.models.bon_travail import BonTravail
from app.models.client import Client
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.project import Project
from tests.smoke.conftest import TestSessionLocal

FINALE_LE = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


@pytest.fixture()
def donnees(run, db_setup):
    ids: dict = {}

    async def _go() -> None:
        async with TestSessionLocal() as s:
            tag = uuid.uuid4().hex[:8]
            cl = Client(name=f"Client refact {tag}")
            s.add(cl)
            await s.flush()
            proj = Project(name=f"Chantier refact {tag}", client_id=cl.id)
            proj_bt = Project(
                name=f"BT-R-{tag} — Fuite", client_id=cl.id, kind="bon_travail"
            )
            proj_bt2 = Project(
                name=f"BT-R2-{tag} — Porte", client_id=cl.id, kind="bon_travail"
            )
            s.add_all([proj, proj_bt, proj_bt2])
            await s.flush()
            finale = Facture(
                reference=f"F-R-{tag}",
                client_id=cl.id,
                project_id=proj.id,
                status="sent",
                is_final=True,
                issued_at=FINALE_LE,
            )
            fac_bt = Facture(
                reference=f"F-RB-{tag}",
                client_id=cl.id,
                project_id=proj_bt.id,
                status="sent",
            )
            s.add_all([finale, fac_bt])
            await s.flush()
            bon = BonTravail(
                reference=f"BT-R-{tag}",
                title="Fuite",
                client_id=cl.id,
                project_id=proj_bt.id,
                facture_id=fac_bt.id,
                status="facture",
                kind="interne",
            )
            bon2 = BonTravail(
                reference=f"BT-R2-{tag}",
                title="Porte",
                client_id=cl.id,
                project_id=proj_bt2.id,
                status="complete_a_refacturer",
                kind="interne",
            )
            s.add_all([bon, bon2])
            avant = FINALE_LE - timedelta(days=3)
            apres = FINALE_LE + timedelta(days=3)

            def achat(pid, desc, cree, **kw) -> Achat:
                base = dict(
                    project_id=pid,
                    description=desc,
                    amount=100,
                    kind="material",
                    is_billable=True,
                    markup_percent=10,
                    created_at=cree,
                )
                base.update(kw)
                a = Achat(**base)
                s.add(a)
                return a

            a_avant = achat(proj.id, "Reçu avant la finale", avant)
            a_apres = achat(proj.id, "Reçu après la finale", apres)
            a_absorbe = achat(
                proj.id, "Absorbé", apres, is_billable=False, markup_percent=0
            )
            a_facture = achat(
                proj.id, "Déjà refacturé", apres, invoiced_at=apres
            )
            a_annule = achat(proj.id, "Annulé", apres, status="cancelled")
            b_oublie = achat(proj_bt.id, "Robinet oublié", apres)
            b_defaut = achat(
                proj_bt.id, "Joint non coché", apres, is_billable=False
            )
            b_exclu = achat(
                proj_bt.id,
                "Exclu à la main",
                apres,
                is_billable=False,
                billable_manual=True,
            )
            c_ouvert = achat(proj_bt2.id, "BT pas fermé", apres)
            await s.flush()
            ids.update(
                client=cl.id,
                projets=[proj.id, proj_bt.id, proj_bt2.id],
                projet=proj.id,
                projet_bt=proj_bt.id,
                facture_bt=fac_bt.id,
                a_avant=a_avant.id,
                a_apres=a_apres.id,
                a_absorbe=a_absorbe.id,
                a_facture=a_facture.id,
                a_annule=a_annule.id,
                b_oublie=b_oublie.id,
                b_defaut=b_defaut.id,
                b_exclu=b_exclu.id,
                c_ouvert=c_ouvert.id,
            )
            await s.commit()

    run(_go())
    yield ids

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            fac_ids = (
                await s.execute(
                    select(Facture.id).where(Facture.project_id.in_(ids["projets"]))
                )
            ).scalars().all()
            await s.execute(delete(Achat).where(Achat.project_id.in_(ids["projets"])))
            await s.execute(delete(BonTravail).where(BonTravail.client_id == ids["client"]))
            if fac_ids:
                await s.execute(delete(FactureItem).where(FactureItem.facture_id.in_(fac_ids)))
                await s.execute(delete(Facture).where(Facture.id.in_(fac_ids)))
            await s.execute(delete(Project).where(Project.id.in_(ids["projets"])))
            await s.execute(delete(Client).where(Client.id == ids["client"]))
            await s.commit()

    run(_nettoyer())


def _liste(client, headers) -> dict[int, dict]:
    r = client.get("/api/v1/achats-a-refacturer", headers=headers)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["compte"] == len(corps["lignes"])
    return {l["achat_id"]: l for l in corps["lignes"]}


def test_detection_des_deux_cas(donnees, client, auth_headers):
    lignes = _liste(client, auth_headers)
    d = donnees

    assert lignes[d["a_apres"]]["motif"] == "apres_facture_finale"
    assert lignes[d["a_apres"]]["facture_reference"].startswith("F-R-")
    assert lignes[d["a_apres"]]["montant_refacturable"] == 110.0
    assert lignes[d["b_oublie"]]["motif"] == "bt_ferme"
    assert lignes[d["b_oublie"]]["bon_reference"].startswith("BT-R-")
    assert lignes[d["b_defaut"]]["motif"] == "bt_ferme"
    for absent in (
        "a_avant", "a_absorbe", "a_facture", "a_annule", "b_exclu", "c_ouvert"
    ):
        assert d[absent] not in lignes, absent

    r = client.get("/api/v1/achats-a-refacturer/compte", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["compte"] >= 3


def test_ne_pas_refacturer_puis_retablir(donnees, client, auth_headers, run):
    aid = donnees["b_oublie"]
    url = f"/api/v1/achats-a-refacturer/{aid}/ne-pas-refacturer"
    assert client.post(url, json={"raison": ""}, headers=auth_headers).status_code == 422

    r = client.post(url, json={"raison": "Geste commercial"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert aid not in _liste(client, auth_headers)

    hist = client.get("/api/v1/achats-a-refacturer/dispenses", headers=auth_headers)
    assert hist.status_code == 200
    trace = next(h for h in hist.json() if h["achat_id"] == aid)
    assert trace["raison"] == "Geste commercial"
    assert trace["dispense_par"]
    assert trace["dispense_le"]

    async def _lire() -> Achat:
        async with TestSessionLocal() as s:
            return await s.get(Achat, aid)

    a = run(_lire())
    assert a.is_billable is False and a.billable_manual is True

    r = client.post(f"/api/v1/achats-a-refacturer/{aid}/retablir", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert aid in _liste(client, auth_headers)


def test_refacturer_sur_facture_neuve(donnees, client, auth_headers):
    aid = donnees["a_apres"]
    r = client.post(
        "/api/v1/achats-a-refacturer/facturer",
        json={"achat_ids": [aid]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["nouvelle"] is True and res["lignes_ajoutees"] == 1
    assert aid not in _liste(client, auth_headers)

    fac = client.get(f"/api/v1/factures/{res['facture_id']}", headers=auth_headers).json()
    assert fac["status"] == "draft"
    assert fac["project_id"] == donnees["projet"]
    items = client.get(
        f"/api/v1/factures/{res['facture_id']}/items", headers=auth_headers
    ).json()
    assert [round(i["total"], 2) for i in items] == [110.0]


def test_refacturer_sur_facture_existante(donnees, client, auth_headers):
    aid = donnees["b_defaut"]
    cibles = client.get(
        f"/api/v1/achats-a-refacturer/{aid}/factures", headers=auth_headers
    )
    assert cibles.status_code == 200
    assert [c["id"] for c in cibles.json()] == [donnees["facture_bt"]]

    # Facture d'un autre projet : refusée.
    r = client.post(
        "/api/v1/achats-a-refacturer/facturer",
        json={"achat_ids": [donnees["a_apres"]], "facture_id": donnees["facture_bt"]},
        headers=auth_headers,
    )
    assert r.status_code == 409

    r = client.post(
        "/api/v1/achats-a-refacturer/facturer",
        json={"achat_ids": [aid], "facture_id": donnees["facture_bt"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["nouvelle"] is False
    assert aid not in _liste(client, auth_headers)


def test_reserve_aux_admins(donnees, client, employee_headers):
    r = client.get("/api/v1/achats-a-refacturer", headers=employee_headers)
    assert r.status_code == 403
