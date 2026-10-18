"""Smoke — inventaire interne chargé aux projets (2026-10-18).

Steven : « une section avec notre inventaire qu'on utilise sur un projet
et qu'on va recharger de notre inventaire interne ».

Couvre :
1. stock de départ + entrée → coût unitaire MOYEN pondéré ;
2. sortie vers un projet → achat « inventaire » du projet (quantité ×
   coût moyen, hors taxes, payé), stock diminué, historique lisible ;
   « à refacturer » selon le projet (bon de travail oui, sans contrat
   non) ou le choix explicite ;
3. stock insuffisant → 409, rien ne bouge ;
4. la sortie refacturée suit le matériel : ligne « Matériaux » de la
   facture, majoration comprise ;
5. annuler une sortie remet en stock et retire l'achat — refusé une fois
   refacturée (depuis l'inventaire comme depuis les achats) ;
6. supprimer l'achat depuis les achats remet aussi en stock ;
7. jamais dans QuickBooks ; coût du projet hors taxes dans les finances ;
8. cliquet IA + liste MCP « inventaire ».
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from app.models.achat import KIND_INVENTAIRE, Achat
from app.models.client import Client
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.inventaire import InventaireArticle, InventaireMouvement
from app.models.project import Project
from tests.smoke.conftest import TestSessionLocal

BASE = "/api/v1/inventaire"


@pytest.fixture()
def chantier(run, db_setup):
    """Fabrique de projets (sans soumission, ou mini-projet de bon de
    travail) ; tout ce qui y est rattaché est nettoyé à la fin."""
    crees: dict[str, list[int]] = {"clients": [], "articles": []}

    def _creer(kind: str = "standard") -> int:
        async def _go() -> int:
            async with TestSessionLocal() as s:
                tag = uuid.uuid4().hex[:8]
                cl = Client(name=f"Client inv {tag}")
                s.add(cl)
                await s.flush()
                proj = Project(name=f"Chantier inv {tag}", client_id=cl.id, kind=kind)
                s.add(proj)
                await s.commit()
                crees["clients"].append(cl.id)
                return proj.id

        return run(_go())

    _creer.articles = crees["articles"]  # type: ignore[attr-defined]
    yield _creer

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            for cid in crees["clients"]:
                pids = (
                    await s.execute(select(Project.id).where(Project.client_id == cid))
                ).scalars().all()
                fac_ids = (
                    await s.execute(select(Facture.id).where(Facture.client_id == cid))
                ).scalars().all()
                if fac_ids:
                    await s.execute(
                        delete(FactureItem).where(FactureItem.facture_id.in_(fac_ids))
                    )
                    await s.execute(delete(Facture).where(Facture.id.in_(fac_ids)))
                await s.execute(
                    delete(InventaireMouvement).where(
                        InventaireMouvement.project_id.in_(pids)
                    )
                )
                await s.execute(delete(Achat).where(Achat.project_id.in_(pids)))
                await s.execute(delete(Project).where(Project.id.in_(pids)))
                await s.execute(delete(Client).where(Client.id == cid))
            for aid in crees["articles"]:
                await s.execute(
                    delete(InventaireMouvement).where(InventaireMouvement.article_id == aid)
                )
                await s.execute(delete(InventaireArticle).where(InventaireArticle.id == aid))
            await s.commit()

    run(_nettoyer())


def _article(client, headers, chantier, **kw) -> dict:
    corps = {"name": f"Vis 2 po {uuid.uuid4().hex[:6]}", "unit": "boîte", **kw}
    r = client.post(f"{BASE}/articles", json=corps, headers=headers)
    assert r.status_code == 201, r.text
    chantier.articles.append(r.json()["id"])
    return r.json()


def _sortie(client, headers, article_id: int, projet_id: int, qte: float, **kw):
    return client.post(
        f"{BASE}/articles/{article_id}/sortie",
        json={"project_id": projet_id, "quantite": qte, **kw},
        headers=headers,
    )


def _achat(run, achat_id: int) -> Achat | None:
    async def _go():
        async with TestSessionLocal() as s:
            return await s.get(Achat, achat_id)

    return run(_go())


def test_cout_moyen_et_sortie_vers_projet(chantier, client, auth_headers, run):
    projet = chantier()
    art = _article(client, auth_headers, chantier, quantite=10, cout_unitaire=5)
    assert (art["quantite"], art["cout_unitaire"], art["valeur"]) == (10.0, 5.0, 50.0)

    r = client.post(
        f"{BASE}/articles/{art['id']}/entree",
        json={"quantite": 10, "cout_unitaire": 7, "note": "Achat Canac"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert (r.json()["quantite"], r.json()["cout_unitaire"]) == (20.0, 6.0)

    r = _sortie(client, auth_headers, art["id"], projet, 4)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["article"]["quantite"] == 16.0
    assert res["montant"] == 24.0
    # Projet sans contrat : coût du projet, pas refacturé par défaut.
    assert res["is_billable"] is False
    mv = res["mouvement"]
    assert (mv["type"], mv["quantite"], mv["project_id"]) == ("sortie", -4.0, projet)
    assert mv["achat_id"] == res["achat_id"] and mv["refacturee"] is False

    achat = _achat(run, res["achat_id"])
    assert achat.kind == KIND_INVENTAIRE
    assert achat.project_id == projet
    assert float(achat.amount) == 24.0 and float(achat.amount_taxes) == 0.0
    assert achat.status == "paid" and achat.fournisseur_id is None
    assert achat.reference == f"INV-{mv['id']}"
    assert achat.description.startswith("Inventaire interne — Vis 2 po")
    assert achat.billable_manual is False

    hist = client.get(
        f"{BASE}/mouvements", params={"project_id": projet}, headers=auth_headers
    ).json()
    assert [m["id"] for m in hist] == [mv["id"]]
    assert hist[0]["project_name"].startswith("Chantier inv")

    # Choix explicite à la sortie : respecté et verrouillé.
    r = _sortie(client, auth_headers, art["id"], projet, 1, is_billable=True)
    assert r.status_code == 200, r.text
    explicite = _achat(run, r.json()["achat_id"])
    assert explicite.is_billable is True and explicite.billable_manual is True
    assert float(explicite.markup_percent) == 10.0


def test_bon_de_travail_refacture_par_defaut(chantier, client, auth_headers):
    projet = chantier(kind="bon_travail")
    art = _article(client, auth_headers, chantier, quantite=5, cout_unitaire=2.5)
    d = client.get(
        f"{BASE}/sortie-defaut", params={"project_id": projet}, headers=auth_headers
    )
    assert d.status_code == 200 and d.json() == {"is_billable": True}
    r = _sortie(client, auth_headers, art["id"], projet, 2)
    assert r.status_code == 200, r.text
    assert r.json()["is_billable"] is True and r.json()["montant"] == 5.0


def test_stock_insuffisant_et_cout_inconnu(chantier, client, auth_headers):
    projet = chantier()
    art = _article(client, auth_headers, chantier, quantite=3, cout_unitaire=4)
    r = _sortie(client, auth_headers, art["id"], projet, 5)
    assert r.status_code == 409
    assert "Stock insuffisant" in r.json()["detail"]
    lu = client.get(f"{BASE}/articles", params={"q": art["name"]}, headers=auth_headers)
    assert lu.json()[0]["quantite"] == 3.0

    sans_cout = _article(client, auth_headers, chantier, quantite=2)
    r = _sortie(client, auth_headers, sans_cout["id"], projet, 1)
    assert r.status_code == 409 and "Coût unitaire inconnu" in r.json()["detail"]
    # Coût donné à la sortie : accepté et retenu pour l'article.
    r = _sortie(client, auth_headers, sans_cout["id"], projet, 1, cout_unitaire=3)
    assert r.status_code == 200, r.text
    assert r.json()["article"]["cout_unitaire"] == 3.0


def test_ajustement_de_compte(chantier, client, auth_headers):
    art = _article(client, auth_headers, chantier, quantite=10, cout_unitaire=1)
    r = client.post(
        f"{BASE}/articles/{art['id']}/ajustement",
        json={"quantite": 7, "note": "Compte du vendredi"},
        headers=auth_headers,
    )
    assert r.status_code == 200 and r.json()["quantite"] == 7.0
    hist = client.get(
        f"{BASE}/mouvements", params={"article_id": art["id"]}, headers=auth_headers
    ).json()
    assert [(m["type"], m["quantite"]) for m in hist] == [
        ("ajustement", -3.0),
        ("entree", 10.0),
    ]


def test_refacturee_sur_la_ligne_materiaux(chantier, client, auth_headers, run):
    projet = chantier()
    art = _article(client, auth_headers, chantier, quantite=10, cout_unitaire=12.5)
    r = _sortie(client, auth_headers, art["id"], projet, 4, is_billable=True)
    assert r.status_code == 200, r.text
    sortie = r.json()

    r = client.post(
        f"/api/v1/projects/{projet}/convert-to-facture",
        json={"include_soumission": False, "include_hours": False, "include_achats": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    fid = int(r.json()["id"])
    items = client.get(f"/api/v1/factures/{fid}/items", headers=auth_headers).json()
    assert [(i["description"], i["total"]) for i in items] == [("Matériaux", 55.0)]
    assert [a["id"] for a in items[0]["achats"]] == [sortie["achat_id"]]

    # Refacturée : ne s'annule plus, ni d'ici ni depuis les achats.
    r = client.delete(f"{BASE}/mouvements/{sortie['mouvement']['id']}", headers=auth_headers)
    assert r.status_code == 409 and "déjà refacturée" in r.json()["detail"]
    r = client.delete(f"/api/v1/achats/{sortie['achat_id']}", headers=auth_headers)
    assert r.status_code == 409
    hist = client.get(
        f"{BASE}/mouvements", params={"article_id": art["id"]}, headers=auth_headers
    ).json()
    assert hist[0]["refacturee"] is True
    assert client.get(f"{BASE}/articles", params={"q": art["name"]}, headers=auth_headers).json()[0][
        "quantite"
    ] == 6.0


def test_annuler_et_supprimer_remettent_en_stock(chantier, client, auth_headers, run):
    projet = chantier()
    art = _article(client, auth_headers, chantier, quantite=10, cout_unitaire=3)

    r = _sortie(client, auth_headers, art["id"], projet, 4)
    sortie = r.json()
    r = client.delete(f"{BASE}/mouvements/{sortie['mouvement']['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["quantite"] == 10.0
    assert _achat(run, sortie["achat_id"]) is None

    r = _sortie(client, auth_headers, art["id"], projet, 6)
    sortie = r.json()
    r = client.delete(f"/api/v1/achats/{sortie['achat_id']}", headers=auth_headers)
    assert r.status_code == 204, r.text
    lu = client.get(f"{BASE}/articles", params={"q": art["name"]}, headers=auth_headers).json()
    assert lu[0]["quantite"] == 10.0
    hist = client.get(
        f"{BASE}/mouvements", params={"article_id": art["id"]}, headers=auth_headers
    ).json()
    assert [m["type"] for m in hist] == ["entree"]

    # Une entrée ne s'annule pas (on corrige par un compte).
    r = client.delete(f"{BASE}/mouvements/{hist[0]['id']}", headers=auth_headers)
    assert r.status_code == 409


def test_jamais_dans_quickbooks_et_finances_hors_taxes(chantier, client, auth_headers, run):
    from app.services.achat_qbo import AchatSyncError, sync_achat_to_qbo

    projet = chantier()
    art = _article(client, auth_headers, chantier, quantite=10, cout_unitaire=10)
    sortie = _sortie(client, auth_headers, art["id"], projet, 5).json()

    async def _pousser():
        async with TestSessionLocal() as s:
            await sync_achat_to_qbo(s, sortie["achat_id"])

    with pytest.raises(AchatSyncError, match="inventaire interne"):
        run(_pousser())

    # Un achat de matériel taxé à côté : 114,98 $ TTC → 100 $ HT.
    async def _materiel():
        async with TestSessionLocal() as s:
            s.add(
                Achat(
                    project_id=projet,
                    description="Rona",
                    amount=100,
                    amount_taxes=14.98,
                    kind="material",
                    is_billable=False,
                )
            )
            await s.commit()

    run(_materiel())
    f = client.get(f"/api/v1/projects/{projet}/finances", headers=auth_headers).json()
    assert f["actual_material_cost"] == 164.98
    # La sortie (50 $) reste à 50 $ HT ; seul le matériel taxé est dé-taxé.
    assert f["actual_material_cost_ht"] == 150.0


def test_supprimer_ou_desactiver_un_article(chantier, client, auth_headers):
    projet = chantier()
    jamais = _article(client, auth_headers, chantier, quantite=1, cout_unitaire=1)
    r = client.delete(f"{BASE}/articles/{jamais['id']}", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"action": "supprime"}

    sorti = _article(client, auth_headers, chantier, quantite=2, cout_unitaire=1)
    assert _sortie(client, auth_headers, sorti["id"], projet, 1).status_code == 200
    r = client.delete(f"{BASE}/articles/{sorti['id']}", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"action": "desactive"}
    actifs = client.get(f"{BASE}/articles", params={"q": sorti["name"]}, headers=auth_headers)
    assert actifs.json() == []
    tous = client.get(
        f"{BASE}/articles", params={"q": sorti["name"], "actifs": False}, headers=auth_headers
    )
    assert [a["is_active"] for a in tous.json()] == [False]
    r = _sortie(client, auth_headers, sorti["id"], projet, 1)
    assert r.status_code == 409 and "désactivé" in r.json()["detail"]


def test_employe_ne_sort_pas_du_stock(chantier, client, auth_headers, employee_headers):
    projet = chantier()
    art = _article(client, auth_headers, chantier, quantite=2, cout_unitaire=1)
    r = _sortie(client, employee_headers, art["id"], projet, 1)
    assert r.status_code == 403


def test_cliquet_ia_et_liste_mcp(chantier, client, auth_headers, api_key_headers):
    from app.core.api_ia_couverture import TABLES_COUVERTES

    assert {"inventaire_articles", "inventaire_mouvements"} <= TABLES_COUVERTES
    projet = chantier()
    art = _article(client, auth_headers, chantier, quantite=3, cout_unitaire=2)
    assert _sortie(client, auth_headers, art["id"], projet, 1).status_code == 200

    r = client.get("/api/v1/activity/entities/inventaire", headers=api_key_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pole"] == "construction" and body["count"] >= 1
    lu = next(i for i in body["items"] if i["id"] == art["id"])
    assert lu["entity_type"] == "inventaire_article"
    assert (lu["quantite"], lu["cout_unitaire"], lu["valeur"]) == (2.0, 2.0, 4.0)

    r = client.get(
        "/api/v1/activity/entities/inventaire_mouvements",
        params={"stage": "sortie"},
        headers=api_key_headers,
    )
    assert r.status_code == 200, r.text
    items = [i for i in r.json()["items"] if i["article_id"] == art["id"]]
    assert items and items[0]["type"] == "sortie" and items[0]["achat_id"]
