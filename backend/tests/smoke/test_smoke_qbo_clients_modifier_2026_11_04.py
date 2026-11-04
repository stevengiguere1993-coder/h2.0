"""Smoke — fiche, transactions et MODIFICATION d'un client QuickBooks
par l'API et le connecteur Claude (Steven 2026-11-04 : « passe par le
lien Kratos » pour nettoyer les clients en double)."""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import select

from app.integrations import quickbooks as qbo_mod
from app.integrations.quickbooks import (
    QuickBooksClient,
    QuickBooksError,
    QuickBooksReconnexionRequise,
)
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.project import Project
from app.services import qbo_clients_modif as modif
from tests.smoke.conftest import TestSessionLocal
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
    projet: bool = False,
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
    if projet:
        row["IsProject"] = True
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
        _c("300", "Projet Millen (projet QB)", parent="209", projet=True),
        _c("108", "1 - 9085 Millen Montréal"),
        _c("227", "Projet — MGV Développement inc."),
        # Chaîne de quatre niveaux (0 à 3) et une fiche avec son propre
        # sous-client, pour la limite des cinq niveaux.
        _c("400", "Niveau 0"),
        _c("401", "Niveau 1", parent="400"),
        _c("402", "Niveau 2", parent="401"),
        _c("403", "Niveau 3", parent="402"),
        _c("410", "Parent X"),
        _c("411", "Enfant Y", parent="410"),
        _c("420", "Feuille Z"),
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
    """QuickBooks en mémoire : clients, fournisseurs et employés (nom
    unique entre les trois), comptages par type, rapport TransactionList,
    mise à jour sparse qui refuse les noms en double, ajoute le suffixe
    « (supprimé) » et rend les sous-clients inactifs avec leur parent,
    comme la vraie compagnie."""

    def __init__(self) -> None:
        self.clients: Dict[str, Dict[str, Any]] = {c["Id"]: c for c in _clients()}
        self.fournisseurs: List[Dict[str, Any]] = [
            {"Id": "V-1", "DisplayName": "Cuisine Quévillon", "Active": True}
        ]
        self.employes: List[Dict[str, Any]] = [
            {"Id": "E-1", "DisplayName": "Steven Giguère", "Active": True}
        ]
        self.comptes: Dict[tuple, int] = {("Invoice", "178"): 1, ("Payment", "178"): 1}
        self.rapports: Dict[str, Dict[str, Any]] = {"178": _RAPPORT_178}
        self.mises_a_jour: List[Dict[str, Any]] = []
        self.refus_comptage: set[str] = set()
        self.erreur_rapport: Optional[Exception] = None
        self.erreur_lecture: Optional[Exception] = None
        self.requetes: List[str] = []

    async def all_customers_any(self) -> List[Dict[str, Any]]:
        if self.erreur_lecture:
            raise self.erreur_lecture
        return copy.deepcopy(list(self.clients.values()))

    async def get_customer_any(self, customer_id: str) -> Optional[Dict[str, Any]]:
        row = self.clients.get(str(customer_id))
        return copy.deepcopy(row) if row else None

    async def query(self, sql: str) -> List[Dict[str, Any]]:
        self.requetes.append(sql)
        m = re.match(r"SELECT \* FROM (Vendor|Employee) WHERE Active IN \(true, false\) "
                     r"AND DisplayName = '(.*)' MAXRESULTS 1$", sql)
        assert m, sql
        nom = m.group(2).replace("''", "'")
        source = self.fournisseurs if m.group(1) == "Vendor" else self.employes
        return [copy.deepcopy(r) for r in source if r["DisplayName"].casefold() == nom.casefold()]

    async def count(self, sql: str) -> int:
        m = re.match(r"SELECT COUNT\(\*\) FROM (\w+) WHERE CustomerRef = '(\d+)'", sql)
        assert m, sql
        if m.group(1) in self.refus_comptage:
            raise QuickBooksError("QBO refus : Invalid query — count failed")
        return self.comptes.get((m.group(1), m.group(2)), 0)

    async def report(self, name: str, **params: str) -> Dict[str, Any]:
        assert name == "TransactionList" and params.get("start_date") == "2000-01-01"
        if self.erreur_rapport:
            raise self.erreur_rapport
        return copy.deepcopy(self.rapports.get(params["customer"], {"Rows": {}}))

    def _descendants(self, cid: str) -> List[str]:
        out = []
        for r in self.clients.values():
            if str((r.get("ParentRef") or {}).get("value") or "") == cid:
                out.append(r["Id"])
                out.extend(self._descendants(r["Id"]))
        return out

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
        noms_pris = [a["DisplayName"] for a in self.clients.values() if a["Id"] != row["Id"]]
        noms_pris += [v["DisplayName"] for v in self.fournisseurs + self.employes]
        if any(n.casefold() == nom.casefold() for n in noms_pris):
            raise QuickBooksError(
                "QBO refus : Duplicate Name Exists Error — QBO POST /customer failed: 400"
            )
        row.update({k: v for k, v in champs.items() if k not in ("DisplayName", "Active")})
        row["DisplayName"] = nom
        if "Active" in champs:
            row["Active"] = champs["Active"]
            if champs["Active"] is False:
                for d in self._descendants(row["Id"]):
                    sous = self.clients[d]
                    if sous["Active"]:
                        sous["Active"] = False
                        sous["DisplayName"] = f"{sous['DisplayName']} (supprimé)"
        row["SyncToken"] = str(int(row["SyncToken"]) + 1)
        return copy.deepcopy(row)


@pytest.fixture
def qb(monkeypatch) -> _FauxQbo:
    faux = _FauxQbo()
    monkeypatch.setattr(qbo_mod, "get_qbo", lambda scope="construction": faux)
    return faux


def _post(client, headers, cid: str, corps: Dict[str, Any], **params: Any):
    return client.post(
        f"/api/v1/qbo/customers/{cid}/modifier", json=corps, headers=headers, params=params
    )


def test_fiche_meme_inactive_et_sous_clients(client, auth_headers, qb):
    r = client.get("/api/v1/qbo/customers/247", headers=auth_headers)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["Active"] is False and b["DisplayName"] == "3165 holt inc (supprimé)"
    assert b["SyncToken"] == "2" and b["sous_clients"] == [] and b["compagnie"] == "construction"
    assert b["liens_kratos"]["utilise_par_kratos"] is False

    b = client.get("/api/v1/qbo/customers/53", headers=auth_headers).json()
    assert [s["Id"] for s in b["sous_clients"]] == ["94"]
    assert b["sous_clients"][0]["Active"] is False and b["BalanceWithJobs"] == -1750.65

    b = client.get("/api/v1/qbo/customers/300", headers=auth_headers).json()
    assert b["IsProject"] is True and b["ParentRef"]["value"] == "209"

    assert client.get("/api/v1/qbo/customers/999", headers=auth_headers).status_code == 404
    assert client.get("/api/v1/qbo/customers/abc", headers=auth_headers).status_code == 422
    assert (
        client.get(
            "/api/v1/qbo/customers/53", params={"compagnie": "x; drop"}, headers=auth_headers
        ).status_code
        == 422
    )


def test_acces_reserve_admin(client, employee_headers, qb):
    assert client.get("/api/v1/qbo/customers/247", headers=employee_headers).status_code == 403
    assert (
        client.get("/api/v1/qbo/customers/178/transactions", headers=employee_headers).status_code
        == 403
    )
    assert _post(client, employee_headers, "227", {"actif": False}).status_code == 403
    assert qb.mises_a_jour == []


def test_inventaire_des_transactions(client, auth_headers, qb):
    r = client.get("/api/v1/qbo/customers/178/transactions", headers=auth_headers)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["transactions_par_type"]["factures"] == 1
    assert b["transactions_par_type"]["paiements"] == 1
    assert b["transactions_par_type"]["temps"] == 0
    assert b["nb_transactions"] == 2 and b["vide"] is False
    assert b["liens_kratos"]["utilise_par_kratos"] is False
    f = b["transactions"][0]
    assert f["type"] == "Facture" and f["id"] == "5127" and f["numero"] == "5127"
    assert f["montant"] == 24387.94 and f["date"] == "2026-09-30"
    assert b["transactions"][1]["montant"] == -24387.95
    # Le format réel des colonnes voyage avec l'inventaire (diagnostic).
    assert [c.split("|")[-1] for c in b["colonnes_rapport"]] == [
        "tx_date", "txn_type", "doc_num", "name", "memo", "account_name", "subt_nat_amount",
    ]

    # Fiche sans rien : « vide ».
    b = client.get("/api/v1/qbo/customers/227/transactions", headers=auth_headers).json()
    assert b["vide"] is True and b["transactions"] == [] and b["notes"] == []

    # Un comptage refusé est signalé sans bloquer, mais « vide » n'est
    # plus affirmé : l'inventaire est incomplet.
    qb.refus_comptage.add("TimeActivity")
    b = client.get("/api/v1/qbo/customers/227/transactions", headers=auth_headers).json()
    assert b["vide"] is None and b["transactions_par_type"]["temps"] is None and b["notes"]

    # Tout refusé (quota Intuit, panne) : jamais « vide », les motifs listés.
    qb.refus_comptage = {e for e, _ in modif.TYPES_TRANSACTIONS}
    qb.erreur_rapport = QuickBooksError("QBO refus : ThrottleExceeded — trop d'appels")
    b = client.get("/api/v1/qbo/customers/227/transactions", headers=auth_headers).json()
    assert b["vide"] is None and len(b["notes"]) == 8
    assert "ThrottleExceeded" in b["notes"][-1]

    # Un parent avec sous-clients n'est jamais « vide ».
    qb.refus_comptage = set()
    qb.erreur_rapport = None
    b = client.get("/api/v1/qbo/customers/53/transactions", headers=auth_headers).json()
    assert b["vide"] is False and [s["Id"] for s in b["sous_clients"]] == ["94"]


def test_nom_deja_porte_409_l_api_ne_fusionne_pas(client, auth_headers, qb):
    r = _post(client, auth_headers, "247", {"nom": "3165 HOLT inc"})
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["fiche"]["Id"] == "233" and "fusion" in d["message"].lower()

    # Le nom d'une fiche INACTIVE compte aussi (QuickBooks l'exige).
    r = _post(client, auth_headers, "227", {"nom": "3165 holt inc (supprimé)"})
    assert r.status_code == 409 and r.json()["detail"]["fiche"]["Id"] == "247"
    assert "inactive" in r.json()["detail"]["message"]

    # Un fournisseur ou un employé porte le nom : même refus, nommé.
    r = _post(client, auth_headers, "227", {"nom": "cuisine quévillon"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["fiche"] == {
        "type": "fournisseur", "Id": "V-1", "DisplayName": "Cuisine Quévillon", "Active": True,
    }
    r = _post(client, auth_headers, "227", {"nom": "Steven Giguère"})
    assert r.status_code == 409 and r.json()["detail"]["fiche"]["type"] == "employé"

    # Réactiver « … (supprimé) » reprendrait un nom déjà porté → même refus.
    r = _post(client, auth_headers, "247", {"actif": True})
    assert r.status_code == 409 and r.json()["detail"]["fiche"]["Id"] == "233"

    assert _post(client, auth_headers, "53", {"nom": "8900 Saint-Hubert Inc.:ancien"}).status_code == 422
    assert _post(client, auth_headers, "53", {"nom": "   "}).status_code == 422
    # Champ inconnu (faute de frappe d'un agent) : refusé, pas ignoré.
    r = _post(client, auth_headers, "53", {"active": False})
    assert r.status_code == 422, r.text
    assert qb.mises_a_jour == []


def test_renommer_et_reactiver_dans_le_meme_appel(client, auth_headers, qb):
    # Le nettoyage classique : la copie inactive reprend un nom libre.
    r = _post(client, auth_headers, "247", {"nom": "3165 Holt Construction", "actif": True})
    assert r.status_code == 200, r.text
    b = r.json()
    assert qb.mises_a_jour == [
        {"Id": "247", "SyncToken": "2", "sparse": True,
         "DisplayName": "3165 Holt Construction", "Active": True}
    ]
    assert b["apres"]["Active"] is True and b["apres"]["DisplayName"] == "3165 Holt Construction"
    assert [f["champ"] for f in b["changements"]] == ["nom", "actif"]

    # Le nom vérifié à la réactivation est le NOUVEAU nom.
    qb.clients["247"].update({"DisplayName": "3165 holt inc (supprimé)", "Active": False})
    r = _post(client, auth_headers, "247", {"nom": "3165 holt inc", "actif": True})
    assert r.status_code == 409 and r.json()["detail"]["fiche"]["Id"] == "233"


def test_simuler_puis_deplacer_un_sous_client(client, auth_headers, qb):
    r = _post(client, auth_headers, "108", {"parent_id": "209", "simuler": True})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["simule"] is True and b["apres"] is None
    assert b["changements"] == [
        {"champ": "parent", "de": None, "a": "209", "nom_parent": "9520-8955 Québec Inc. (Millen)"}
    ]
    assert b["corps"] == {"ParentRef": {"value": "209"}, "Job": True}
    assert qb.mises_a_jour == []

    r = _post(client, auth_headers, "108", {"parent_id": "209"})
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
    b = _post(client, auth_headers, "108", {"parent_id": "209"}).json()
    assert b["changements"] == [] and "Rien" in b["note"] and len(qb.mises_a_jour) == 1

    # Déplacer ET cocher « facturer avec le parent » dans le même appel :
    # le ParentRef envoyé est le NOUVEAU parent.
    r = _post(client, auth_headers, "420", {"parent_id": "209", "facturer_avec_parent": True,
                                            "simuler": True})
    assert r.status_code == 200, r.text
    assert r.json()["corps"] == {"ParentRef": {"value": "209"}, "Job": True, "BillWithParent": True}
    r = _post(client, auth_headers, "289", {"parent_id": "209", "facturer_avec_parent": True})
    assert r.status_code == 200, r.text
    assert qb.mises_a_jour[-1] == {
        "Id": "289", "SyncToken": "2", "sparse": True,
        "ParentRef": {"value": "209"}, "Job": True, "BillWithParent": True,
    }
    assert [f["champ"] for f in r.json()["changements"]] == ["parent", "facturer_avec_parent"]


def test_parent_refuse_422(client, auth_headers, qb):
    def _essai(cid: str, parent: str) -> int:
        return _post(client, auth_headers, cid, {"parent_id": parent}).status_code

    assert _essai("108", "999") == 422  # introuvable
    assert _essai("108", "108") == 422  # soi-même
    assert _essai("209", "110") == 422  # son propre sous-client
    assert _essai("108", "94") == 422  # parent inactif
    assert _essai("108", "300") == 422  # un projet QuickBooks n'a pas de sous-clients
    assert _essai("110", "") == 422  # retirer le parent : pas par l'API
    # Cinq niveaux au plus : X (avec son enfant Y) sous le niveau 3 en
    # ferait six ; sous le niveau 2, cinq ; une feuille sous le niveau 3
    # est au cinquième niveau, permis.
    assert _essai("410", "403") == 422
    assert qb.mises_a_jour == []
    assert _essai("410", "402") == 200 and qb.mises_a_jour[-1]["ParentRef"] == {"value": "402"}
    assert _essai("420", "403") == 200 and qb.mises_a_jour[-1]["ParentRef"] == {"value": "403"}
    # Un projet QuickBooks se déplace (comme move_subcustomer).
    assert _essai("300", "208") == 200


def test_desactiver_garde_fous_puis_fiche_vide(client, auth_headers, qb):
    r = _post(client, auth_headers, "53", {"actif": False})
    assert r.status_code == 409 and "solde" in r.json()["detail"]["message"].lower()

    r = _post(client, auth_headers, "209", {"actif": False})
    assert r.status_code == 409, r.text
    assert [s["Id"] for s in r.json()["detail"]["sous_clients"]] == ["110", "300"]
    assert qb.mises_a_jour == []

    r = _post(client, auth_headers, "227", {"actif": False})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["changements"] == [{"champ": "actif", "de": True, "a": False}]
    assert b["apres"]["Active"] is False and "sous_clients_desactives" not in b
    assert b["apres"]["DisplayName"] == "Projet — MGV Développement inc. (supprimé)"
    assert qb.mises_a_jour[-1]["Active"] is False

    # Forcer malgré le solde : la demande part, QuickBooks tranche.
    r = _post(client, auth_headers, "53", {"actif": False, "forcer": True})
    assert r.status_code == 200, r.text
    assert r.json()["avertissements"] and qb.mises_a_jour[-1]["Active"] is False
    assert r.json()["changements"] == [{"champ": "actif", "de": True, "a": False}]

    # Forcer malgré des sous-clients actifs : QuickBooks les rend inactifs
    # avec le parent, et la réponse le dit.
    r = _post(client, auth_headers, "209", {"actif": False, "forcer": True})
    assert r.status_code == 200, r.text
    b = r.json()
    assert [s["Id"] for s in b["sous_clients_desactives"]] == ["110", "300"]
    assert all(not s["Active"] for s in b["sous_clients_desactives"])
    assert b["apres"]["Active"] is False

    # Le suffixe que QuickBooks ajoutera existe déjà : averti, pas bloqué.
    r = _post(client, auth_headers, "233", {"actif": False, "simuler": True})
    assert r.status_code == 200 and any("suffixe" in a for a in r.json()["avertissements"])


def test_liens_kratos_proteges(client, auth_headers, run, qb):
    async def _seed() -> None:
        async with TestSessionLocal() as s:
            cl = Client(name="Parent X (Kratos)", qbo_customer_id="410")
            s.add(cl)
            await s.flush()
            s.add(Project(name="Chantier Holt (Kratos)", client_id=cl.id, qbo_job_id="289"))
            await s.commit()

    run(_seed())

    b = client.get("/api/v1/qbo/customers/410", headers=auth_headers).json()
    liens = b["liens_kratos"]
    assert liens["utilise_par_kratos"] is True
    assert [c["nom"] for c in liens["clients"]] == ["Parent X (Kratos)"]
    assert liens["projets"] == [] and liens["factures_mensuelles"] == 0
    b = client.get("/api/v1/qbo/customers/289/transactions", headers=auth_headers).json()
    assert [p["nom"] for p in b["liens_kratos"]["projets"]] == ["Chantier Holt (Kratos)"]

    # Rendre inactive une fiche que Kratos utilise : refusé sauf forcer.
    r = _post(client, auth_headers, "410", {"actif": False})
    assert r.status_code == 409, r.text
    assert "Kratos" in r.json()["detail"]["message"]
    assert r.json()["detail"]["liens_kratos"]["clients"][0]["nom"] == "Parent X (Kratos)"
    assert qb.mises_a_jour == []
    r = _post(client, auth_headers, "410", {"actif": False, "forcer": True})
    assert r.status_code == 200, r.text
    assert any("Kratos" in a for a in r.json()["avertissements"])
    assert [s["Id"] for s in r.json()["sous_clients_desactives"]] == ["411"]

    # Renommer ou déplacer : permis, avec avertissement.
    r = _post(client, auth_headers, "289", {"parent_id": "209", "simuler": True})
    assert r.status_code == 200 and any("projets" in a for a in r.json()["avertissements"])
    r = _post(client, auth_headers, "410", {"nom": "Parent X renommé", "simuler": True})
    assert r.status_code == 200 and any("Kratos relie" in a for a in r.json()["avertissements"])


def test_renommer_facturer_avec_parent_et_rien_a_changer(client, auth_headers, qb):
    r = _post(client, auth_headers, "53", {"nom": "  8900 Saint-Hubert inc. (ancien)  "})
    assert r.status_code == 200, r.text
    assert r.json()["apres"]["DisplayName"] == "8900 Saint-Hubert inc. (ancien)"
    assert qb.mises_a_jour[-1]["DisplayName"] == "8900 Saint-Hubert inc. (ancien)"

    assert _post(client, auth_headers, "233", {"facturer_avec_parent": True}).status_code == 422
    assert _post(client, auth_headers, "300", {"facturer_avec_parent": True}).status_code == 422
    assert len(qb.mises_a_jour) == 1

    r = _post(client, auth_headers, "289", {"facturer_avec_parent": True})
    assert r.status_code == 200, r.text
    assert qb.mises_a_jour[-1] == {
        "Id": "289", "SyncToken": "2", "sparse": True,
        "BillWithParent": True, "ParentRef": {"value": "208"}, "Job": True,
    }
    assert r.json()["apres"]["BillWithParent"] is True

    # Rien à changer : même nom (espaces près), même état, même réglage.
    for cid, corps in (
        ("233", {"nom": "3165 holt inc"}),
        ("208", {"nom": "8900 St Hubert Inc."}),
        ("233", {"actif": True}),
        ("289", {"facturer_avec_parent": True}),
    ):
        b = _post(client, auth_headers, cid, corps).json()
        assert b["changements"] == [] and "Rien" in b["note"], (cid, corps, b)
        assert b["apres"] == b["avant"]
    assert len(qb.mises_a_jour) == 2


def test_quickbooks_refuse_ou_absent(client, auth_headers, qb):
    # Doublon de nom que le garde-fou n'a pas vu (fiche créée entre la
    # lecture et l'écriture) : 502 avec le motif d'Intuit.
    qb.clients["233"]["DisplayName"] = "Nom neuf"
    qb.clients["233"]["FullyQualifiedName"] = "Nom neuf"

    async def _tous_sans_233():
        return [copy.deepcopy(c) for c in qb.clients.values() if c["Id"] != "233"]

    qb.all_customers_any = _tous_sans_233  # type: ignore[method-assign]
    r = _post(client, auth_headers, "227", {"nom": "nom NEUF"})
    assert r.status_code == 502, r.text
    assert "Duplicate Name Exists" in r.json()["detail"]["message"]

    # Jeton expiré à la lecture : 503 et où reconnecter, rien d'écrit.
    qb.erreur_lecture = QuickBooksReconnexionRequise("invalid_grant")
    del qb.all_customers_any  # type: ignore[attr-defined]
    for r in (
        client.get("/api/v1/qbo/customers/247", headers=auth_headers),
        client.get("/api/v1/qbo/customers/247/transactions", headers=auth_headers),
        _post(client, auth_headers, "227", {"actif": False}),
    ):
        assert r.status_code == 503, r.text
        assert "reconnexion" in r.json()["detail"]["message"]
        assert qbo_mod.ou_reconnecter("construction") in r.json()["detail"]["message"]
    assert len(qb.mises_a_jour) == 1

    # Compagnie sans connexion QuickBooks (staging, inc non branchée) :
    # 503 explicite, pas une erreur 500.
    qb.erreur_lecture = RuntimeError("QuickBooks client is not configured")
    r = client.get("/api/v1/qbo/customers/247", params={"compagnie": "inc:7"}, headers=auth_headers)
    assert r.status_code == 503, r.text
    assert "inc:7" in r.json()["detail"]["message"] and "pas connecté" in r.json()["detail"]["message"]


def test_journal_automatique_des_ecritures(client, auth_headers, run, admin_id, qb):
    r = _post(client, auth_headers, "227", {"actif": False})
    assert r.status_code == 200, r.text

    async def _rows() -> List[AuditLog]:
        async with TestSessionLocal() as s:
            return list(
                (
                    await s.execute(
                        select(AuditLog).where(
                            AuditLog.action == "api.post",
                            AuditLog.entity_type == "qbo.customers.modifier",
                            AuditLog.entity_id == 227,
                        )
                    )
                ).scalars().all()
            )

    rows = run(_rows())
    assert rows, "aucune ligne d'audit pour la modification"
    assert rows[-1].user_id == admin_id
    details = json.loads(rows[-1].details_json or "{}")
    assert details.get("statut") == 200 and "/api/v1/qbo/customers/227/modifier" in details.get("chemin", "")


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

    # Un refus garde son détail structuré à travers l'outil d'action.
    res = _rpc(
        client,
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "kratos_action",
                    "arguments": {"methode": "POST",
                                  "chemin": "/api/v1/qbo/customers/247/modifier",
                                  "corps": {"actif": True}}}},
        key=cle,
    ).json()["result"]["structuredContent"]
    assert res["statut"] == 409 and res["reponse"]["detail"]["fiche"]["Id"] == "233"


def test_client_quickbooks_count_et_mise_a_jour_sparse(run):
    qbo = QuickBooksClient()
    appels: List[tuple] = []
    reponses: Dict[str, Any] = {"count": {"QueryResponse": {"totalCount": 3}}}

    async def _request(method, path, *, json_body=None, params=None):
        appels.append((method, path, json_body, params))
        if path == "/query" and params["query"].startswith("SELECT COUNT"):
            return reponses["count"]
        if path == "/query":
            if "Id = '999'" in params["query"]:
                return {"QueryResponse": {}}
            return {"QueryResponse": {"Customer": [{"Id": "247", "SyncToken": "7",
                                                     "DisplayName": "x", "Active": False}]}}
        assert method == "POST" and path == "/customer"
        return {"Customer": {**json_body, "DisplayName": "3165 holt inc"}}

    qbo._request = _request  # type: ignore[method-assign]
    assert run(qbo.count("SELECT COUNT(*) FROM Invoice WHERE CustomerRef = '247'")) == 3
    reponses["count"] = {"QueryResponse": {}}  # aucun objet : QB omet totalCount
    assert run(qbo.count("SELECT COUNT(*) FROM Invoice WHERE CustomerRef = '247'")) == 0

    maj = run(qbo.update_customer_fields("247", Active=True, ParentRef=None))
    assert maj["DisplayName"] == "3165 holt inc"
    assert appels[-1][2] == {"Id": "247", "SyncToken": "7", "sparse": True, "Active": True}
    assert appels[-1][3] == {"minorversion": "70"}
    assert "Active IN (true, false)" in appels[-2][3]["query"]

    with pytest.raises(QuickBooksError, match="introuvable"):
        run(qbo.update_customer_fields("999", Active=True))


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
                             {"value": "n/a"}]},
            ]
        },
    }
    lignes = modif.lignes_rapport(rapport)
    assert [(l["type"], l["id"], l["montant"], l["date"]) for l in lignes] == [
        ("Invoice", "9", 10.5, "2026-01-02"),
        ("Payment", "10", None, "2026-01-03"),
    ]
    assert modif.lignes_rapport({}) == []


def test_lignes_rapport_format_reel_compagnie_en_francais():
    """Le rapport réel d'une compagnie en français : ``ColType`` porte le
    TYPE de donnée (Date / String / Money), pas la clé ; titres en
    français ; montants « 1 350,00 $ » et négatifs entre parenthèses ;
    parfois un ``MetaData`` ColKey. Avant le 2026-11-04 toutes ces
    lignes sortaient à null (fiche 270 : 7 lignes vides)."""
    rapport = {
        "Columns": {
            "Column": [
                {"ColTitle": "Date", "ColType": "Date"},
                {"ColTitle": "Type de transaction", "ColType": "String"},
                {"ColTitle": "N°", "ColType": "String"},
                {"ColTitle": "Comptabilisation", "ColType": "String"},
                {"ColTitle": "Nom", "ColType": "String"},
                {"ColTitle": "Note/Description", "ColType": "String"},
                {"ColTitle": "Compte", "ColType": "String"},
                {"ColTitle": "Fractionnement", "ColType": "String",
                 "MetaData": [{"Name": "ColKey", "Value": "other_account"}]},
                {"ColTitle": "Montant", "ColType": "Money"},
            ]
        },
        "Rows": {
            "Row": [
                {"type": "Data", "ColData": [
                    {"value": "2026-09-30"}, {"value": "Facture", "id": "5127"},
                    {"value": "5127"}, {"value": "Oui"},
                    {"value": "710, Rue Legendre Est", "id": "270"},
                    {"value": "Rénovation"}, {"value": "Comptes clients"},
                    {"value": "-Fractionné-"}, {"value": "24 387,94 $"},
                ]},
                {"type": "Data", "ColData": [
                    {"value": "2026-10-14"}, {"value": "Paiement", "id": "5301"},
                    {"value": ""}, {"value": "Oui"},
                    {"value": "710, Rue Legendre Est", "id": "270"},
                    {"value": ""}, {"value": "Comptes clients"},
                    {"value": "Banque"}, {"value": "(1 350,00 $)"},
                ]},
                {"type": "Data", "ColData": [
                    {"value": "2026-10-20"}, {"value": "Note de crédit", "id": "5400"},
                    {"value": "NC-1"}, {"value": "Oui"}, {"value": "710, Rue Legendre Est"},
                    {"value": ""}, {"value": "Comptes clients"}, {"value": ""},
                    {"value": "1,350.00"},
                ]},
            ]
        },
    }
    assert modif.colonnes_rapport(rapport) == [
        "Date|Date|tx_date", "Type de transaction|String|txn_type", "N°|String|doc_num",
        "Comptabilisation|String|comptabilisation", "Nom|String|name",
        "Note/Description|String|memo", "Compte|String|account_name",
        "Fractionnement|String|other_account", "Montant|Money|subt_nat_amount",
    ]
    lignes = modif.lignes_rapport(rapport)
    assert [(l["date"], l["type"], l["id"], l["numero"], l["nom"], l["compte"], l["montant"])
            for l in lignes] == [
        ("2026-09-30", "Facture", "5127", "5127", "710, Rue Legendre Est",
         "Comptes clients", 24387.94),
        ("2026-10-14", "Paiement", "5301", "", "710, Rue Legendre Est",
         "Comptes clients", -1350.0),
        ("2026-10-20", "Note de crédit", "5400", "NC-1", "710, Rue Legendre Est",
         "Comptes clients", 1350.0),
    ]
    assert lignes[0]["memo"] == "Rénovation"

    # Grand livre en Débit / Crédit, sans colonne Montant.
    gl = {
        "Columns": {"Column": [
            {"ColTitle": "Date", "ColType": "Date"}, {"ColTitle": "Type", "ColType": "String"},
            {"ColTitle": "Débit", "ColType": "Money"}, {"ColTitle": "Crédit", "ColType": "Money"},
        ]},
        "Rows": {"Row": [
            {"type": "Data", "ColData": [{"value": "2026-01-05"}, {"value": "Facture", "id": "1"},
                                          {"value": "100,00"}, {"value": ""}]},
            {"type": "Data", "ColData": [{"value": "2026-01-06"}, {"value": "Paiement", "id": "2"},
                                          {"value": ""}, {"value": "40,50"}]},
        ]},
    }
    assert [(l["id"], l["montant"]) for l in modif.lignes_rapport(gl)] == [("1", 100.0), ("2", -40.5)]

    # Sans colonnes du tout : les lignes existent, sans champs reconnus.
    sans = {"Rows": {"Row": [{"type": "Data", "ColData": [{"value": "x"}]}]}}
    assert modif.lignes_rapport(sans) == [
        {"date": None, "type": None, "id": None, "numero": None, "nom": None,
         "memo": None, "compte": None, "montant": None}
    ]
    assert modif.colonnes_rapport(sans) == []


def test_profondeur_et_ancetres_bornes_sur_une_boucle():
    par_id = {
        "A": {"Id": "A", "ParentRef": {"value": "B"}},
        "B": {"Id": "B", "ParentRef": {"value": "A"}},
    }
    assert modif._ancetres(par_id, "A") == ["B"]
    assert modif._profondeur(par_id, "A") == 1
