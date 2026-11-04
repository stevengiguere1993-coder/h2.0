"""Smoke — Facturation locative → QuickBooks : produit/service réglé dans
Kratos (2026-11-03).

Phil 2026-11-02 : « le type de transaction et les détails de cette facture,
je ne peux rien changer dans Kratos… pour l'instant les factures c'est des
services non catégorisés ». Avec un faux QuickBooks :

1. le catalogue expose produits/services (sans les catégories), comptes de
   revenus et réglages ;
2. les réglages (item par type de ligne + type de facture) s'enregistrent,
   les valeurs inconnues sont refusées ;
3. créer un service le rattache au compte de revenus CHOISI et peut
   l'affecter à un type de ligne ;
4. une ligne du panier part avec l'item choisi sur la ligne (ou celui des
   Réglages) et la description saisie ; l'historique garde l'item ;
5. une catégorie ou un item inactif est refusé (422) ;
6. le mode « facture distincte » crée une nouvelle facture à chaque envoi.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from app.api.v1.endpoints import immobilier_frais_gestion as ep
from app.integrations.quickbooks import QuickBooksError
from app.models.automation_setting import AutomationSetting
from app.models.immobilier import Immeuble

from tests.smoke.conftest import TestSessionLocal

FG = "/api/v1/immobilier/frais-gestion"
IDS: Dict[str, Any] = {}


class FakeQbo:
    scope = "immobilier"
    realm_id = "realm-items"
    ready = True

    def __init__(self) -> None:
        self.items: Dict[str, Dict[str, Any]] = {
            "1": {"Id": "1", "Name": "Services", "Type": "Service", "Active": True,
                  "IncomeAccountRef": {"value": "90", "name": "Services non catégorisés"}},
            "7": {"Id": "7", "Name": "Frais de gestion immobilière", "Type": "Service", "Active": True,
                  "IncomeAccountRef": {"value": "81", "name": "Revenus de gestion"}},
            "9": {"Id": "9", "Name": "Entretien ménager", "Type": "Service", "Active": True,
                  "IncomeAccountRef": {"value": "82", "name": "Revenus d'entretien"}},
            "20": {"Id": "20", "Name": "Matériaux", "Type": "Category", "Active": True},
            "21": {"Id": "21", "Name": "Vieux service", "Type": "Service", "Active": False,
                   "IncomeAccountRef": {"value": "81", "name": "Revenus de gestion"}},
        }
        self.accounts = [
            {"Id": "81", "Name": "Revenus de gestion", "FullyQualifiedName": "Revenus de gestion", "AccountType": "Income", "AccountSubType": "ServiceFeeIncome", "Active": True},
            {"Id": "82", "Name": "Revenus d'entretien", "FullyQualifiedName": "Revenus d'entretien", "AccountType": "Income", "AccountSubType": "ServiceFeeIncome", "Active": True},
            {"Id": "90", "Name": "Services non catégorisés", "FullyQualifiedName": "Services non catégorisés", "AccountType": "Income", "AccountSubType": "SalesOfProductIncome", "Active": True},
        ]
        self.invoices: Dict[str, Dict[str, Any]] = {}
        self.created_items: List[Dict[str, Any]] = []
        self._next = 100

    async def _load_refresh_from_db(self) -> None:
        return None

    async def query(self, q: str) -> List[Dict[str, Any]]:
        if "FROM Item" in q:
            if "WHERE Name =" in q:
                nom = q.split("'")[1]
                return [i for i in self.items.values() if i["Name"] == nom]
            return [i for i in self.items.values() if i.get("Active", True)]
        if "FROM Account" in q:
            return list(self.accounts)
        if "DocNumber" in q:
            return [{"DocNumber": inv.get("DocNumber")} for inv in self.invoices.values()]
        return []

    async def get_item(self, item_id: str):
        return self.items.get(str(item_id))

    async def list_items(self):
        return [i for i in self.items.values() if i.get("Active", True) and i["Type"] != "Category"]

    async def list_income_accounts(self):
        return list(self.accounts)

    async def create_item(self, name, description=None, income_account_id=None):
        self._next += 1
        compte = next((a for a in self.accounts if a["Id"] == str(income_account_id)), None)
        it = {"Id": str(self._next), "Name": name, "Type": "Service", "Active": True,
              "Description": description,
              "IncomeAccountRef": {"value": str(income_account_id), "name": compte["Name"] if compte else None}}
        self.items[it["Id"]] = it
        self.created_items.append(it)
        return it

    async def ensure_item(self, name, description=None):
        for it in self.items.values():
            if it["Name"] == name and it["Type"] != "Category":
                return it
        return await self.create_item(name, description, income_account_id="90")

    async def get_invoice(self, invoice_id: str):
        inv = self.invoices.get(str(invoice_id))
        if inv is None:
            raise QuickBooksError("QBO 400: Object Not Found (code 610)")
        return {"Invoice": dict(inv)}

    async def create_invoice(self, payload: Dict[str, Any]):
        if payload.get("Id"):
            inv = dict(payload)
            self.invoices[str(inv["Id"])] = inv
            return {"Invoice": inv}
        self._next += 1
        inv = dict(payload)
        inv["Id"] = str(self._next)
        inv.setdefault("DocNumber", str(1000 + len(self.invoices)))
        inv["TotalAmt"] = sum(float(l.get("Amount") or 0) for l in inv.get("Line") or [])
        inv["Balance"] = inv["TotalAmt"]
        self.invoices[inv["Id"]] = inv
        return {"Invoice": inv}


@pytest.fixture(scope="module")
def fake_qbo():
    return FakeQbo()


@pytest.fixture(autouse=True)
def _brancher_fake(monkeypatch, fake_qbo):
    monkeypatch.setattr(ep, "get_qbo", lambda scope=None: fake_qbo)


@pytest.fixture(scope="module")
def seed(run, seeded_users) -> Dict[str, Any]:
    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(name="Immeuble Smoke QBO Items", address="12 rue Facture", city="Montréal", is_active=True,
                           qbo_customer_id="C-77", qbo_customer_name="Proprio Smoke")
            s.add(imm)
            s.add(AutomationSetting(key="timesheet_qbo", enabled=True, config_json=json.dumps({"tax_code_id": "5", "tax_code_name": "TPS/TVQ"})))
            await s.flush()
            await s.commit()
            return {"imm": imm.id}

    return run(_seed())


def test_catalogue_items_comptes_et_reglages(client, auth_headers, employee_headers, seed):
    assert client.get(f"{FG}/qbo-catalogue", headers=employee_headers).status_code == 403
    r = client.get(f"{FG}/qbo-catalogue", headers=auth_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["connected"] is True and d["error"] is None
    noms = {i["name"]: i for i in d["items"]}
    assert "Matériaux" not in noms and "Vieux service" not in noms          # catégorie et inactif écartés
    assert noms["Frais de gestion immobilière"]["income_account"] == "Revenus de gestion"
    assert {c["id"] for c in d["income_accounts"]} == {"81", "82", "90"}
    assert d["reglages"] == {"items": {}, "mode_facture": "mensuelle"}
    assert [t["key"] for t in d["types"]] == ["gestion", "relocation", "manuel", "heures"]
    assert [m["key"] for m in d["modes"]] == ["mensuelle", "distincte"]


def test_reglages_enregistres_et_valides(client, auth_headers, seed):
    r = client.put(f"{FG}/qbo-reglages", headers=auth_headers, json={
        "items": {"gestion": {"id": "7", "name": "Frais de gestion immobilière"}, "relocation": None},
        "mode_facture": "mensuelle",
    })
    assert r.status_code == 200, r.text
    assert r.json()["reglages"]["items"] == {"gestion": {"id": "7", "name": "Frais de gestion immobilière"}}
    assert client.get(f"{FG}/qbo-catalogue", headers=auth_headers).json()["reglages"]["items"]["gestion"]["id"] == "7"
    assert client.put(f"{FG}/qbo-reglages", headers=auth_headers, json={"items": {}, "mode_facture": "bidon"}).status_code == 422
    assert client.put(f"{FG}/qbo-reglages", headers=auth_headers, json={"items": {"nimporte": {"id": "7"}}, "mode_facture": "mensuelle"}).status_code == 422
    assert client.put(f"{FG}/qbo-reglages", headers=auth_headers, json={"items": {"manuel": {"id": "", "name": "x"}}, "mode_facture": "mensuelle"}).status_code == 422


def test_creer_un_service_sur_le_bon_compte(client, auth_headers, seed, fake_qbo):
    r = client.post(f"{FG}/qbo-items", headers=auth_headers, json={
        "name": "Frais de relocation", "income_account_id": "81", "description": "Relocation d'un logement ou d'une chambre",
        "type_ligne": "relocation",
    })
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["item"]["name"] == "Frais de relocation" and d["item"]["income_account_id"] == "81" and d["item"]["income_account"] == "Revenus de gestion"
    assert d["reglages"]["items"]["relocation"] == {"id": d["item"]["id"], "name": "Frais de relocation"}
    assert fake_qbo.created_items[-1]["IncomeAccountRef"]["value"] == "81"   # plus jamais « non catégorisé » par défaut
    assert client.post(f"{FG}/qbo-items", headers=auth_headers, json={"name": "X", "income_account_id": "81", "type_ligne": "bidon"}).status_code == 422


def _frais_manuel(client, auth_headers, imm: int, libelle: str, montant: float) -> int:
    r = client.post(f"{FG}/frais-manuels", headers=auth_headers, json={"immeuble_id": imm, "libelle": libelle, "montant": montant})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_ligne_avec_item_et_description_choisis(client, auth_headers, seed, fake_qbo):
    imm = seed["imm"]
    fm1 = _frais_manuel(client, auth_headers, imm, "Ménage du 3e", 80)
    fm2 = _frais_manuel(client, auth_headers, imm, "Frais divers", 20)
    r = client.post(f"{FG}/facturer-groupe", headers=auth_headers, json={
        "qbo_customer_id": "C-77",
        "lignes": [
            {"immeuble_id": imm, "libelle": "Ménage du 3e", "frais_manuel_id": fm1, "montant": 80, "item_id": "9", "description": "Grand ménage du 3e étage après départ"},
            {"immeuble_id": imm, "libelle": "Frais divers", "frais_manuel_id": fm2, "montant": 20},
        ],
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] is True and d["nb_lignes"] == 2 and d["total"] == 100
    IDS["invoice_1"] = d["invoice_id"]
    lignes = fake_qbo.invoices[d["invoice_id"]]["Line"]
    assert lignes[0]["SalesItemLineDetail"]["ItemRef"]["value"] == "9"
    assert lignes[0]["Description"] == "Grand ménage du 3e étage après départ"
    # Ligne sans choix : aucun réglage « manuel » → service historique « Frais de gestion » (créé au besoin)…
    assert lignes[1]["Description"] == "Frais divers — Immeuble Smoke QBO Items"
    nom_defaut = fake_qbo.items[lignes[1]["SalesItemLineDetail"]["ItemRef"]["value"]]["Name"]
    assert nom_defaut == "Frais de gestion"
    # …et l'historique garde l'item porté par chaque ligne.
    hist = client.get(FG, headers=auth_headers).json()["historique"]
    noms = {h["label"]: h.get("qbo_item_name") for h in hist if h["immeuble_id"] == imm}
    assert noms["Ménage du 3e"] == "Entretien ménager" and noms["Frais divers"] == "Frais de gestion"


def test_item_des_reglages_puis_refus_categorie_et_inactif(client, auth_headers, seed, fake_qbo):
    imm = seed["imm"]
    assert client.put(f"{FG}/qbo-reglages", headers=auth_headers, json={
        "items": {"manuel": {"id": "9", "name": "Entretien ménager"}}, "mode_facture": "mensuelle",
    }).status_code == 200
    fm = _frais_manuel(client, auth_headers, imm, "Déneigement", 150)
    r = client.post(f"{FG}/facturer-groupe", headers=auth_headers, json={
        "qbo_customer_id": "C-77", "lignes": [{"immeuble_id": imm, "libelle": "Déneigement", "frais_manuel_id": fm, "montant": 150}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["created"] is False                                     # greffée sur la facture du mois
    inv = fake_qbo.invoices[r.json()["invoice_id"]]
    assert inv["Line"][-1]["SalesItemLineDetail"]["ItemRef"]["value"] == "9"  # item des Réglages pour « manuel »
    # Catégorie / inactif choisis sur la ligne → refus propre, le frais reste à facturer.
    for mauvais in ("20", "21", "999"):
        fm_x = _frais_manuel(client, auth_headers, imm, f"Essai {mauvais}", 10)
        r = client.post(f"{FG}/facturer-groupe", headers=auth_headers, json={
            "qbo_customer_id": "C-77", "lignes": [{"immeuble_id": imm, "libelle": f"Essai {mauvais}", "frais_manuel_id": fm_x, "montant": 10, "item_id": mauvais}],
        })
        assert r.status_code == 422, r.text
        assert "inutilisable" in r.json()["detail"]
        assert client.delete(f"{FG}/frais-manuels/{fm_x}", headers=auth_headers).status_code in (200, 204)


def test_mode_facture_distincte(client, auth_headers, seed, fake_qbo):
    imm = seed["imm"]
    assert client.put(f"{FG}/qbo-reglages", headers=auth_headers, json={"items": {}, "mode_facture": "distincte"}).status_code == 200
    avant = set(fake_qbo.invoices)
    ids = []
    for i in range(2):
        fm = _frais_manuel(client, auth_headers, imm, f"Distinct {i}", 30)
        r = client.post(f"{FG}/facturer-groupe", headers=auth_headers, json={
            "qbo_customer_id": "C-77", "lignes": [{"immeuble_id": imm, "libelle": f"Distinct {i}", "frais_manuel_id": fm, "montant": 30}],
        })
        assert r.status_code == 200, r.text
        assert r.json()["created"] is True
        ids.append(r.json()["invoice_id"])
    assert len(set(ids)) == 2 and not (set(ids) & avant)                    # deux nouvelles factures, pas de greffe
    assert all(len(fake_qbo.invoices[i]["Line"]) == 1 for i in ids)
    # Retour au mode mensuel : on greffe de nouveau sur la facture du mois existante.
    assert client.put(f"{FG}/qbo-reglages", headers=auth_headers, json={"items": {}, "mode_facture": "mensuelle"}).status_code == 200
