"""Smoke — fiche, transactions et MODIFICATION d'un client QuickBooks
par l'API et le connecteur Claude (Steven 2026-11-04 : « passe par le
lien Kratos » pour nettoyer les clients en double)."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

import pytest

from app.integrations import quickbooks as qbo_mod
from app.integrations.quickbooks import QuickBooksClient, QuickBooksError
from app.services import qbo_clients_modif as modif
from tests.smoke.test_smoke_mcp import _rpc

_RE_SUPPRIME = re.compile(r"\s*\(supprimé\)\s*$")


def _c(
    id_: str,
    nom: str,
    *,
    actif: bool = True,
    solde: float = 0.0,
    solde_jobs: Optional[float] = None,
    parent: Optional[str] = None,
    bwp: bool = False,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "Id": id_,
        "SyncToken": "2",
        "DisplayName": nom,
        "FullyQualifiedName": nom,
        "Active": actif,
        "Job": parent is not None,
        "Balance": solde,
        "BalanceWithJobs": solde if solde_jobs is None else solde_jobs,
        "BillWithParent": bwp,
        "MetaData": {"CreateTime": "2025-01-01T00:00:00-05:00"},
    }
    if parent:
        row["ParentRef"] = {"value": parent}
    return row


def _clients() -> List[Dict[str, Any]]:
    return [
        _c("233", "3165 holt inc"),
        _c("247", "3165 holt inc (supprimé)", actif=False),
        _c("208", "8900 St  Hubert Inc.", solde=0.0, solde_jobs=-1750.65),
        _c("289", "8900 St-Hubert", parent="208"),
        _c("178", "8900 Rue Saint-Hubert, Montréal, Québec, H2M 1Y7", solde=-0.01),
        _c("53", "8900 Saint-Hubert Inc.", solde=0.0, solde_jobs=-1750.65),
        _c("94", "Patate (supprimé)", actif=False, parent="53"),
        _c("209", "9520-8955 Québec Inc. (Millen)"),
        _c("110", "2 - 9085 Millen Montréal", parent="209"),
        _c("108", "1 - 9085 Millen Montréal"),
        _c("227", "Projet — MGV Développement inc."),
    ]


_RAPPORT_178 = {
    "Columns": {
        "Column": [
            {"ColTitle": "Date", "ColType": "tx_date"},
            {"ColTitle": "Type de transaction", "ColType": "txn_type"},
            {"ColTitle": "N°", "ColType": "doc_num"},
            {"ColTitle": "Nom", "ColType": "name"},
            {"ColTitle": "Note", "ColType": "memo"},
            {"ColTitle": "Compte", "ColType": "account_name"},
            {"ColTitle": "Montant", "ColType": "subt_nat_amount"},
        ]
    },
    "Rows": {
        "Row": [
            {
                "type": "Data",
                "ColData": [
                    {"value": "2026-09-30"},
                    {"value": "Facture", "id": "5127"},
                    {"value": "5127"},
                    {"value": "8900 Rue Saint-Hubert", "id": "178"},
                    {"value": ""},
                    {"value": "Comptes clients"},
                    {"value": "24387.94"},
                ],
            },
            {
                "type": "Data",
                "ColData": [
                    {"value": "2026-10-15"},
                    {"value": "Paiement", "id": "6001"},
                    {"value": ""},
                    {"value": "8900 Rue Saint-Hubert", "id": "178"},
                    {"value": "Virement"},
                    {"value": "Fonds non déposés"},
                    {"value": "-24387.95"},
                ],
            },
            {
                "type": "Section",
                "Summary": {"ColData": [{"value": "TOTAL"}, {"value": "-0.01"}]},
            },
        ]
    },
}


class _FauxQbo:
    """QuickBooks en mémoire : clients, comptages par type, rapport
    TransactionList, mise à jour sparse qui refuse les noms en double
    (comme la vraie compagnie)."""

    def __init__(self) -> None:
        self.clients: Dict[str, Dict[str, Any]] = {c["Id"]: c for c in _clients()}
        self.comptes: Dict[tuple, int] = {("Invoice", "178"): 1, ("Payment", "178"): 1}
        self.rapports: Dict[str, Dict[str, Any]] = {"178": _RAPPORT_178}
        self.mises_a_jour: List[Dict[str, Any]] = []
        self.refus_comptage: set[str] = set()

    async def all_customers_any(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(list(self.clients.values()))

    async def get_customer_any(self, customer_id: str) -> Optional[Dict[str, Any]]:
        row = self.clients.get(str(customer_id))
        return copy.deepcopy(row) if row else None

    async def count(self, sql: str) -> int:
        m = re.match(r"SELECT COUNT\(\*\) FROM (\w+) WHERE CustomerRef = '(\d+)'", sql)
        assert m, sql
        if m.group(1) in self.refus_comptage:
            raise QuickBooksError("QBO refus : Invalid query — count failed")
        return self.comptes.get((m.group(1), m.group(2)), 0)

    async def report(self, name: str, **params: str) -> Dict[str, Any]:
        assert name == "TransactionList" and params.get("start_date") == "2000-01-01"
        return copy.deepcopy(self.rapports.get(params["customer"], {"Rows": {}}))

    async def update_customer_fields(self, customer_id: str, **champs: Any) -> Dict[str, Any]:
        row = self.clients.get(str(customer_id))
        if row is None:
            raise QuickBooksError(f"Client QuickBooks {customer_id} introuvable.")
        corps = {"Id": row["Id"], "SyncToken": row["SyncToken"], "sparse": True, **champs}
        self.mises_a_jour.append(corps)
        nom = champs.get("DisplayName", row["DisplayName"])
        if champs.get("Active") is True:
            nom = _RE_SUPPRIME.sub("", nom)
        elif champs.get("Active") is False and not _RE_SUPPRIME.search(nom):
            nom = f"{nom} (supprimé)"
        for autre in self.clients.values():
            if autre["Id"] != row["Id"] and autre["DisplayName"].casefold() == nom.casefold():
                raise QuickBooksError(
                    "QBO refus : Duplicate Name Exists Error — QBO POST /customer failed: 400"
                )
        row.update({k: v for k, v in champs.items() if k not in ("DisplayName", "Active")})
        row["DisplayName"] = nom
        if "Active" in champs:
            row["Active"] = champs["Active"]
        row["SyncToken"] = str(int(row["SyncToken"]) + 1)
        return copy.deepcopy(row)


@pytest.fixture
def qb(monkeypatch) -> _FauxQbo:
    faux = _FauxQbo()
    monkeypatch.setattr(qbo_mod, "get_qbo", lambda scope="construction": faux)
    return faux


def test_fiche_meme_inactive_et_sous_clients(client, auth_headers, qb):
    r = client.get("/api/v1/qbo/customers/247", headers=auth_headers)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["Active"] is False and b["DisplayName"] == "3165 holt inc (supprimé)"
    assert b["SyncToken"] == "2" and b["sous_clients"] == [] and b["compagnie"] == "construction"

    b = client.get("/api/v1/qbo/customers/53", headers=auth_headers).json()
    assert [s["Id"] for s in b["sous_clients"]] == ["94"]
    assert b["sous_clients"][0]["Active"] is False and b["BalanceWithJobs"] == -1750.65

    assert client.get("/api/v1/qbo/customers/999", headers=auth_headers).status_code == 404
    assert client.get("/api/v1/qbo/customers/abc", headers=auth_headers).status_code == 422
    assert (
        client.get(
            "/api/v1/qbo/customers/53", params={"compagnie": "x; drop"}, headers=auth_headers
        ).status_code
        == 422
    )


def test_inventaire_des_transactions(client, auth_headers, qb):
    r = client.get("/api/v1/qbo/customers/178/transactions", headers=auth_headers)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["transactions_par_type"]["factures"] == 1
    assert b["transactions_par_type"]["paiements"] == 1
    assert b["transactions_par_type"]["temps"] == 0
    assert b["nb_transactions"] == 2 and b["vide"] is False
    f = b["transactions"][0]
    assert f["type"] == "Facture" and f["id"] == "5127" and f["numero"] == "5127"
    assert f["montant"] == 24387.94 and f["date"] == "2026-09-30"
    assert b["transactions"][1]["montant"] == -24387.95

    # Fiche sans rien : « vide », le comptage refusé est signalé sans bloquer.
    qb.refus_comptage.add("TimeActivity")
    b = client.get("/api/v1/qbo/customers/227/transactions", headers=auth_headers).json()
    assert b["vide"] is True and b["transactions"] == []
    assert b["transactions_par_type"]["temps"] is None and b["notes"]
    # Un parent avec sous-clients n'est jamais « vide ».
    b = client.get("/api/v1/qbo/customers/53/transactions", headers=auth_headers).json()
    assert b["vide"] is False and [s["Id"] for s in b["sous_clients"]] == ["94"]


def test_nom_deja_porte_409_l_api_ne_fusionne_pas(client, auth_headers, qb):
    r = client.post(
        "/api/v1/qbo/customers/247/modifier",
        json={"nom": "3165 HOLT inc"},
        headers=auth_headers,
    )
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["fiche"]["Id"] == "233" and "fusion" in d["message"].lower()
    assert qb.mises_a_jour == []

    # Réactiver « … (supprimé) » reprendrait un nom déjà porté → même refus.
    r = client.post(
        "/api/v1/qbo/customers/247/modifier", json={"actif": True}, headers=auth_headers
    )
    assert r.status_code == 409 and r.json()["detail"]["fiche"]["Id"] == "233"
    assert qb.mises_a_jour == []

    assert (
        client.post(
            "/api/v1/qbo/customers/53/modifier",
            json={"nom": "8900 Saint-Hubert Inc.:ancien"},
            headers=auth_headers,
        ).status_code
        == 422
    )


def test_simuler_puis_deplacer_un_sous_client(client, auth_headers, qb):
    r = client.post(
        "/api/v1/qbo/customers/108/modifier",
        json={"parent_id": "209", "simuler": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["simule"] is True and b["apres"] is None
    assert b["changements"] == [
        {"champ": "parent", "de": None, "a": "209", "nom_parent": "9520-8955 Québec Inc. (Millen)"}
    ]
    assert b["corps"] == {"ParentRef": {"value": "209"}, "Job": True}
    assert qb.mises_a_jour == []

    r = client.post(
        "/api/v1/qbo/customers/108/modifier", json={"parent_id": "209"}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["simule"] is False and b["apres"]["ParentRef"]["value"] == "209"
    assert b["apres"]["SyncToken"] == "3" and b["avant"]["ParentRef"] is None
    assert qb.mises_a_jour == [
        {"Id": "108", "SyncToken": "2", "sparse": True, "ParentRef": {"value": "209"}, "Job": True}
    ]
    # Le déplacement ne coche pas « facturer avec le parent » de lui-même.
    assert "BillWithParent" not in qb.mises_a_jour[-1]

    # Déjà sous ce parent : rien à changer, rien d'envoyé.
    b = client.post(
        "/api/v1/qbo/customers/108/modifier", json={"parent_id": "209"}, headers=auth_headers
    ).json()
    assert b["changements"] == [] and "Rien" in b["note"] and len(qb.mises_a_jour) == 1


def test_parent_refuse_422(client, auth_headers, qb):
    def _essai(cid: str, parent: str) -> int:
        return client.post(
            f"/api/v1/qbo/customers/{cid}/modifier",
            json={"parent_id": parent},
            headers=auth_headers,
        ).status_code

    assert _essai("108", "999") == 422  # introuvable
    assert _essai("108", "108") == 422  # soi-même
    assert _essai("209", "110") == 422  # son propre sous-client
    assert _essai("108", "94") == 422  # parent inactif
    assert _essai("110", "") == 422  # retirer le parent : pas par l'API
    assert qb.mises_a_jour == []


def test_desactiver_garde_fous_puis_fiche_vide(client, auth_headers, qb):
    r = client.post(
        "/api/v1/qbo/customers/53/modifier", json={"actif": False}, headers=auth_headers
    )
    assert r.status_code == 409 and "solde" in r.json()["detail"].lower()

    r = client.post(
        "/api/v1/qbo/customers/209/modifier", json={"actif": False}, headers=auth_headers
    )
    assert r.status_code == 409, r.text
    assert [s["Id"] for s in r.json()["detail"]["sous_clients"]] == ["110"]
    assert qb.mises_a_jour == []

    r = client.post(
        "/api/v1/qbo/customers/227/modifier", json={"actif": False}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["changements"] == [{"champ": "actif", "de": True, "a": False}]
    assert b["apres"]["Active"] is False
    assert b["apres"]["DisplayName"] == "Projet — MGV Développement inc. (supprimé)"
    assert qb.mises_a_jour[-1]["Active"] is False

    # Forcer : la demande part, QuickBooks tranche (ici le faux accepte).
    r = client.post(
        "/api/v1/qbo/customers/209/modifier",
        json={"actif": False, "forcer": True},
        headers=auth_headers,
    )
    assert r.status_code == 200 and r.json()["avertissements"]


def test_renommer_et_facturer_avec_parent(client, auth_headers, qb):
    r = client.post(
        "/api/v1/qbo/customers/53/modifier",
        json={"nom": "  8900 Saint-Hubert inc. (ancien)  "},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["apres"]["DisplayName"] == "8900 Saint-Hubert inc. (ancien)"
    assert qb.mises_a_jour[-1]["DisplayName"] == "8900 Saint-Hubert inc. (ancien)"

    r = client.post(
        "/api/v1/qbo/customers/233/modifier",
        json={"facturer_avec_parent": True},
        headers=auth_headers,
    )
    assert r.status_code == 422  # client de premier niveau

    r = client.post(
        "/api/v1/qbo/customers/289/modifier",
        json={"facturer_avec_parent": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert qb.mises_a_jour[-1] == {
        "Id": "289", "SyncToken": "2", "sparse": True,
        "BillWithParent": True, "ParentRef": {"value": "208"}, "Job": True,
    }
    assert r.json()["apres"]["BillWithParent"] is True


def test_refus_quickbooks_remonte_en_502(client, auth_headers, qb):
    # Le faux QB refuse un doublon de nom que le garde-fou n'a pas vu
    # (fiche créée entre la lecture et l'écriture) : 502 avec le motif.
    qb.clients["233"]["DisplayName"] = "Nom neuf"
    qb.clients["233"]["FullyQualifiedName"] = "Nom neuf"

    async def _tous_sans_233():
        return [copy.deepcopy(c) for c in qb.clients.values() if c["Id"] != "233"]

    qb.all_customers_any = _tous_sans_233  # type: ignore[method-assign]
    r = client.post(
        "/api/v1/qbo/customers/227/modifier", json={"nom": "nom NEUF"}, headers=auth_headers
    )
    assert r.status_code == 502, r.text
    assert "Duplicate Name Exists" in r.json()["detail"]


def test_par_le_connecteur_lecture_et_action(client, auth_headers, seeded_users, qb):
    res = _rpc(
        client,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "kratos_api_catalogue",
                    "arguments": {"recherche": "customers", "methode": "POST"}}},
    ).json()["result"]["structuredContent"]
    assert "/api/v1/qbo/customers/{customer_id}/modifier" in {
        o["chemin"] for o in res["operations"]
    }

    res = _rpc(
        client,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "kratos_lire",
                    "arguments": {"chemin": "/api/v1/qbo/customers/178/transactions"}}},
    ).json()["result"]
    assert not res.get("isError"), res
    assert res["structuredContent"]["reponse"]["nb_transactions"] == 2

    # Clé AVEC la capacité « Exécuter toute action » : la modification passe.
    r = client.post(
        "/api/v1/api-keys",
        headers=auth_headers,
        json={"name": "cle fiches QB", "scopes": ["api:actions:executer"]},
    )
    assert r.status_code in (200, 201), r.text
    cle = r.json()["api_key"]
    res = _rpc(
        client,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "kratos_action",
                    "arguments": {"methode": "POST",
                                  "chemin": "/api/v1/qbo/customers/108/modifier",
                                  "corps": {"parent_id": "209"}}}},
        key=cle,
    ).json()["result"]
    assert not res.get("isError"), res
    s = res["structuredContent"]
    assert s["ok"] is True and s["statut"] == 200, s
    assert s["reponse"]["apres"]["ParentRef"]["value"] == "209"
    assert qb.mises_a_jour[-1]["ParentRef"] == {"value": "209"}


def test_client_quickbooks_count_et_mise_a_jour_sparse(run):
    qbo = QuickBooksClient()
    appels: List[tuple] = []

    async def _request(method, path, *, json_body=None, params=None):
        appels.append((method, path, json_body, params))
        if path == "/query" and params["query"].startswith("SELECT COUNT"):
            return {"QueryResponse": {"totalCount": 3}}
        if path == "/query":
            return {"QueryResponse": {"Customer": [{"Id": "247", "SyncToken": "7",
                                                     "DisplayName": "x", "Active": False}]}}
        assert method == "POST" and path == "/customer"
        return {"Customer": {**json_body, "DisplayName": "3165 holt inc"}}

    qbo._request = _request  # type: ignore[method-assign]
    assert run(qbo.count("SELECT COUNT(*) FROM Invoice WHERE CustomerRef = '247'")) == 3
    maj = run(qbo.update_customer_fields("247", Active=True, ParentRef=None))
    assert maj["DisplayName"] == "3165 holt inc"
    corps = appels[-1][2]
    assert corps == {"Id": "247", "SyncToken": "7", "sparse": True, "Active": True}
    assert "Active IN (true, false)" in appels[-2][3]["query"]


def test_lignes_rapport_imbriquees_et_sections():
    rapport = {
        "Columns": {
            "Column": [
                {"ColType": "tx_date"}, {"ColType": "txn_type"}, {"ColType": "subt_amount"},
            ]
        },
        "Rows": {
            "Row": [
                {
                    "type": "Section",
                    "Header": {"ColData": [{"value": "Groupe"}]},
                    "Rows": {
                        "Row": [
                            {"type": "Data",
                             "ColData": [{"value": "2026-01-02"},
                                         {"value": "Invoice", "id": "9"},
                                         {"value": "10.5"}]}
                        ]
                    },
                    "Summary": {"ColData": [{"value": "Total"}, {"value": ""}, {"value": "10.5"}]},
                },
                {"type": "Data",
                 "ColData": [{"value": "2026-01-03"}, {"value": "Payment", "id": "10"},
                             {"value": "-10.5"}]},
            ]
        },
    }
    lignes = modif.lignes_rapport(rapport)
    assert [(l["type"], l["id"], l["montant"], l["date"]) for l in lignes] == [
        ("Invoice", "9", 10.5, "2026-01-02"),
        ("Payment", "10", -10.5, "2026-01-03"),
    ]
    assert modif.lignes_rapport({}) == []
