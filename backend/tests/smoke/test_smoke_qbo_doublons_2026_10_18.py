"""Smoke — clients en double dans QuickBooks (Steven, 2026-10-18).

Intuit ne fusionne pas de clients par API : la fusion se fait dans
QuickBooks (le doublon renommé au nom exact de la fiche gardée) et Kratos
suit. Ici : regroupement des doublons, compagnies dédoublonnées par realm,
analyse (noms exacts, sous-clients, liens Kratos), « C'est fait » (dans
les deux sens), désactivation d'une fiche vide par l'API, nom Kratos
aligné sur QuickBooks, webhook « Merge » d'Intuit.

Client QuickBooks factice : aucun appel réseau.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import itertools
import json
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, get_password_hash
from app.integrations.quickbooks import QuickBooksError
from app.models.client import Client
from app.models.immobilier import Immeuble
from app.models.qbo_monthly_invoice import QboMonthlyInvoice
from app.models.timesheet import TimesheetCompany
from app.models.user import User
from app.services import qbo_doublons as svc

from .conftest import TestSessionLocal

#: Realms propres à ce fichier (la base SQLite est partagée entre tests).
R_HORIZON = "realm-doublons-horizon"
R_INC = "realm-doublons-inc"


class _FakeQbo:
    """Une compagnie QuickBooks : ``query_all`` ne rend que les clients
    actifs (comme QuickBooks), ``read_customer`` les rend tous."""

    ready = True
    env = "production"
    compteur = itertools.count(9000)

    def __init__(self, realm_id: str) -> None:
        self.realm_id = realm_id
        self.customers: Dict[str, Dict[str, Any]] = {}
        #: (entité, id) → nombre ; entité seule → QuickBooksError.
        self.comptes: Dict[Any, int] = {}
        self.refus: set = set()
        self.desactives: List[str] = []

    def ajouter(self, nom: str, parent: Optional[str] = None, **extra: Any) -> str:
        cid = f"D{next(_FakeQbo.compteur)}"
        row: Dict[str, Any] = {
            "Id": cid,
            "DisplayName": nom,
            "SyncToken": "0",
            "Active": True,
            "MetaData": {"CreateTime": f"2026-01-{len(self.customers) + 1:02d}T10:00:00-05:00"},
        }
        if parent:
            row.update(ParentRef={"value": parent}, Job=True)
        row.update(extra)
        self.customers[cid] = row
        return cid

    def fusionner(self, source: str) -> None:
        """Ce que fait l'écran de QuickBooks : la fiche fusionnée devient
        inactive et prend « (deleted) »."""
        row = self.customers[source]
        row["Active"] = False
        row["DisplayName"] = f"{row['DisplayName']} (deleted)"

    async def _load_refresh_from_db(self) -> None:
        return None

    async def query_all(self, sql: str) -> List[Dict[str, Any]]:
        assert "FROM Customer" in sql
        return [dict(r) for r in self.customers.values() if r.get("Active", True)]

    async def read_customer(self, cid: str) -> Optional[Dict[str, Any]]:
        r = self.customers.get(str(cid))
        return dict(r) if r else None

    async def get_customer(self, cid: str) -> Optional[Dict[str, Any]]:
        r = self.customers.get(str(cid))
        return dict(r) if r and r.get("Active", True) else None

    async def count(self, sql: str) -> int:
        m = re.search(r"FROM (\w+) WHERE CustomerRef = '([^']+)'", sql)
        assert m, sql
        entite, cid = m.group(1), m.group(2)
        if entite in self.refus:
            raise QuickBooksError(f"QBO refus : {entite} non interrogeable — QBO GET /query failed: 400")
        return self.comptes.get((entite, cid), 0)

    async def deactivate_customer(self, cid: str) -> Dict[str, Any]:
        self.desactives.append(cid)
        self.fusionner(cid)
        return dict(self.customers[cid])


@pytest.fixture()
def qb(monkeypatch) -> Dict[str, _FakeQbo]:
    """Horizon (Construction, et les pôles Entreprise et Immobilier sur la
    même compagnie) + le QuickBooks d'une INC."""
    horizon, inc = _FakeQbo(R_HORIZON), _FakeQbo(R_INC)
    par_scope = {"construction": horizon, "entreprise": horizon, "immobilier": horizon, "inc:77": inc}
    monkeypatch.setattr(
        "app.integrations.quickbooks.get_qbo",
        lambda scope="construction": par_scope[scope],
    )

    async def _connexions(_db: Any) -> List[Dict[str, Any]]:
        def c(scope: str, realm: str, nom: Optional[str]) -> Dict[str, Any]:
            return {
                "scope": scope,
                "realm_id": realm,
                "environment": "production",
                "company_name": nom,
                "connectee": True,
                "reconnexion_requise": False,
            }

        return [
            c("construction", R_HORIZON, "Horizon Services Immobiliers inc."),
            c("entreprise", R_HORIZON, "Horizon Services Immobiliers inc."),
            c("immobilier", R_HORIZON, None),
            c("inc:77", R_INC, "9417-1287 Québec inc."),
        ]

    monkeypatch.setattr(svc, "_connexions", _connexions)
    return {"horizon": horizon, "inc": inc}


def _compte(run) -> int:
    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = User(
                email=f"smoke-doublons-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password=get_password_hash("smoke-doublons-x"),
                is_active=True,
                is_admin=True,
                role="owner",
            )
            s.add(u)
            await s.commit()
            return u.id

    return run(_seed())


@pytest.fixture(scope="module")
def owner_headers(client, run) -> Dict[str, str]:
    """La section Comptabilité est réservée aux propriétaires."""
    return {"Authorization": f"Bearer {create_access_token(subject=str(_compte(run)))}"}


def _ajouter(run, *objets: Any) -> List[int]:
    async def _go() -> List[int]:
        async with TestSessionLocal() as s:
            for o in objets:
                s.add(o)
            await s.commit()
            return [o.id for o in objets]

    return run(_go())


def _lire(run, modele: Any, oid: int) -> Any:
    async def _go() -> Any:
        async with TestSessionLocal() as s:
            return await s.get(modele, oid)

    return run(_go())


def _mensuelles(run, realm: str) -> List[QboMonthlyInvoice]:
    async def _go() -> List[QboMonthlyInvoice]:
        async with TestSessionLocal() as s:
            return list(
                (
                    await s.execute(select(QboMonthlyInvoice).where(QboMonthlyInvoice.realm_id == realm))
                ).scalars()
            )

    return run(_go())


def _mensuelle(realm: str, cid: str, mois: date) -> QboMonthlyInvoice:
    now = datetime.now(timezone.utc)
    return QboMonthlyInvoice(
        realm_id=realm, qbo_customer_id=cid, mois=mois, qbo_invoice_id=f"I{cid}",
        created_at=now, updated_at=now,
    )


# ── Regroupement (fonctions pures) ──────────────────────────────────


def _row(cid: str, nom: str, **extra: Any) -> Dict[str, Any]:
    return {"Id": cid, "DisplayName": nom, "Active": True, **extra}


def test_cle_nom_ignore_casse_accents_formes_juridiques_et_ordre():
    assert svc.cle_nom("9520-8955 Québec inc.") == svc.cle_nom("9520-8955 QUEBEC INC")
    assert svc.cle_nom("Tremblay, Jean") == svc.cle_nom("Jean Tremblay")
    assert svc.cle_nom("Les Constructions A&B ltée") == svc.cle_nom("constructions A et B")
    assert svc.numeros("9520-8955 Millen & Legendre", None) == {"9520-8955"}
    assert svc.sans_suffixe_supprime("Millen (deleted)") == "Millen"
    assert svc._compte(1, "notes de crédit") == "1 note de crédit"
    assert svc._compte(3, "factures") == "3 factures"
    assert svc._montant(16115.64) == "16 115,64 $"


def test_regrouper_doublons_probables_et_paires_a_verifier():
    rows = [
        _row("1", "9520-8955 Québec inc.", PrimaryEmailAddr={"Address": "proprio@ex.com"}),
        _row("2", "9520-8955 Millen & Legendre"),
        _row("3", "Millen", PrimaryEmailAddr={"Address": "Proprio@ex.com"}),
        _row("4", "Constructions Gagnon"),
        _row("5", "Construction Gagnon inc."),
        # Chiffres différents : jamais « presque identique ».
        _row("6", "Immeuble 1234 rue Fleury"),
        _row("7", "Immeuble 1236 rue Fleury"),
        # Sous-client du même nom que son parent : pas un doublon.
        _row("8", "Constructions Gagnon", ParentRef={"value": "4"}, Job=True),
        # Un courriel partagé par 5 fiches : celui d'un comptable.
        *[_row(f"c{i}", f"Client {i} comptable", PrimaryEmailAddr={"Address": "compta@ex.com"}) for i in range(5)],
    ]
    groupes, paires = svc.regrouper(rows)
    par_ids = {tuple(sorted(g["ids"])): g["raisons"] for g in groupes}
    assert par_ids[("1", "2")] == ["même numéro d'entreprise (9520-8955)"]
    assert "nom presque identique" in par_ids[("4", "5")]
    assert not any("6" in ids for ids in par_ids)
    assert not any("8" in ids for ids in par_ids)
    # Millen ne partage que le courriel de 9520 : à vérifier, pas probable.
    assert [p["ids"] for p in paires] == [["1", "3"]]
    assert paires[0]["raisons"] == ["même courriel (proprio@ex.com)"]


# ── API ─────────────────────────────────────────────────────────────


def test_compagnies_une_par_realm(client, owner_headers, qb):
    r = client.get("/api/v1/qbo-doublons", headers=owner_headers)
    assert r.status_code == 200, r.text
    comps = {c["realm_id"]: c for c in r.json()["compagnies"]}
    assert set(comps) == {R_HORIZON, R_INC}
    assert comps[R_HORIZON]["scope"] == "construction"
    assert comps[R_HORIZON]["utilisee_par"][:3] == ["Construction", "Gestion d'entreprise", "Immobilier"]
    assert comps[R_INC]["nom"] == "9417-1287 Québec inc."


def test_analyse_noms_exacts_sous_clients_et_liens_kratos(client, run, owner_headers, qb):
    h = qb["horizon"]
    a = h.ajouter("Gagnon Rénovation inc.", PrimaryEmailAddr={"Address": "gagnon@ex.com"})
    b = h.ajouter("Gagnon Renovation", BalanceWithJobs=120.5)
    h.ajouter("29 rue Besner", a, IsProject=True)
    t = h.ajouter("Tremblay, Jean")
    cl_lie, cl_nom, cl_tremblay = _ajouter(
        run,
        Client(name="Gagnon Rénovation inc.", qbo_customer_id=a),
        Client(name="Gagnon Renovation"),
        Client(name="Jean Tremblay", qbo_customer_id=t),
    )
    (imm,) = _ajouter(run, Immeuble(name="Le Gagnon", address="1 rue Test", qbo_customer_id=b))

    r = client.get("/api/v1/qbo-doublons/analyse", params={"scope": "construction"}, headers=owner_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    g = next(g for g in body["groupes"] if {f["id"] for f in g["fiches"]} == {a, b})
    assert g["raisons"] == ["même nom"]
    assert g["suggestion"] == a  # la plus ancienne
    fa, fb = g["fiches"]
    assert fa["nom"] == "Gagnon Rénovation inc."
    assert fa["sous_clients"] == [{"id": fa["sous_clients"][0]["id"], "nom": "29 rue Besner", "projet": True}]
    assert f"nameId={a}&deeplinkcompanyid={R_HORIZON}" in fa["lien_qb"]
    assert {k["id"] for k in fa["kratos"]} == {cl_lie}
    assert {(k["type"], k["id"]) for k in fb["kratos"]} == {("client", cl_nom), ("immeuble", imm)}
    assert fb["solde"] == 120.5
    ecart = next(n for n in body["noms_kratos"] if n["client_id"] == cl_tremblay)
    assert ecart["nom_quickbooks"] == "Tremblay, Jean"

    # « Prendre le nom QuickBooks ».
    r = client.post(f"/api/v1/qbo-doublons/clients-kratos/{cl_tremblay}/nom-quickbooks", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert _lire(run, Client, cl_tremblay).name == "Tremblay, Jean"


def test_paire_choisie_a_la_main(client, owner_headers, qb):
    h = qb["horizon"]
    x = h.ajouter("9520-8955 Québec inc. (manuel)")
    y = h.ajouter("Millen (manuel)")
    r = client.get(
        "/api/v1/qbo-doublons/paire", params={"scope": "construction", "ids": f"{y},{x}"}, headers=owner_headers
    )
    assert r.status_code == 200, r.text
    g = r.json()
    assert [f["id"] for f in g["fiches"]] == [x, y]
    assert g["raisons"] == ["choisis à la main"]


def test_fusion_faite_kratos_suit_la_fiche_gardee(client, run, owner_headers, qb):
    h = qb["horizon"]
    garde = h.ajouter("9520-8955 Québec inc.")
    doublon = h.ajouter("Millen 9085")
    cl, cl_nom = _ajouter(
        run,
        Client(name="Millen 9085", qbo_customer_id=doublon),
        Client(name="millen 9085 "),
    )
    (imm,) = _ajouter(run, Immeuble(name="9085 Millen", address="9085 av. Millen", qbo_customer_id=doublon))
    (comp,) = _ajouter(run, TimesheetCompany(label="Millen 9085"))
    oct_, nov = date(2026, 10, 1), date(2026, 11, 1)
    _ajouter(
        run,
        _mensuelle(R_HORIZON, doublon, oct_),
        _mensuelle(R_HORIZON, doublon, nov),
        _mensuelle(R_HORIZON, garde, nov),
    )
    corps = {"scope": "construction", "source_id": doublon, "cible_id": garde, "nom_source": "Millen 9085"}

    # Pas encore fusionnée dans QuickBooks : rien ne bouge.
    r = client.post("/api/v1/qbo-doublons/fusion", json=corps, headers=owner_headers)
    assert r.status_code == 409, r.text
    assert "toujours active" in r.json()["detail"]
    assert _lire(run, Client, cl).qbo_customer_id == doublon

    h.fusionner(doublon)
    r = client.post("/api/v1/qbo-doublons/fusion", json=corps, headers=owner_headers)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["sens_inverse"] is False
    assert sorted(res["clients_kratos"]) == ["9520-8955 Québec inc.", "9520-8955 Québec inc."]
    assert res["immeubles"] == ["9085 Millen"]
    assert res["compagnies_feuille_de_temps"] == ["Millen 9085"]
    assert res["factures_mensuelles"] == 2
    assert any("2 fiches clients" in a for a in res["avertissements"])
    for cid in (cl, cl_nom):
        c = _lire(run, Client, cid)
        assert (c.qbo_customer_id, c.name) == (garde, "9520-8955 Québec inc.")
    i = _lire(run, Immeuble, imm)
    assert (i.qbo_customer_id, i.qbo_customer_name) == (garde, "9520-8955 Québec inc.")
    assert _lire(run, TimesheetCompany, comp).qbo_customer_id == garde
    # Octobre passe sous la fiche gardée ; en novembre elle avait déjà sa facture.
    assert sorted((m.qbo_customer_id, m.mois) for m in _mensuelles(run, R_HORIZON)) == [
        (garde, oct_),
        (garde, nov),
    ]

    # Rejouer ne change rien.
    r = client.post("/api/v1/qbo-doublons/fusion", json=corps, headers=owner_headers)
    assert r.status_code == 200, r.text
    assert r.json()["clients_kratos"] == []


def test_fusion_faite_dans_l_autre_sens(client, run, owner_headers, qb):
    i = qb["inc"]
    voulu = i.ajouter("Locations Côté inc.")
    autre = i.ajouter("Locations Coté")
    i.fusionner(voulu)  # renommée dans l'autre sens : c'est « autre » qui reste
    r = client.post(
        "/api/v1/qbo-doublons/fusion",
        json={"scope": "inc:77", "source_id": autre, "cible_id": voulu},
        headers=owner_headers,
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["sens_inverse"] is True
    assert (res["source"]["id"], res["cible"]["id"]) == (voulu, autre)
    assert res["source"]["nom"] == "Locations Côté inc."


def test_desactiver_seulement_une_fiche_vide(client, run, owner_headers, qb):
    h = qb["horizon"]
    garde = h.ajouter("Plomberie Roy inc.")
    plein = h.ajouter("Plomberie Roy")
    vide = h.ajouter("Plomberie Roy enr")
    h.comptes[("Invoice", plein)] = 3
    (comp,) = _ajouter(run, TimesheetCompany(label="Plomberie Roy enr", qbo_customer_id=vide))

    r = client.get("/api/v1/qbo-doublons/apercu", params={"scope": "construction", "id": plein}, headers=owner_headers)
    assert r.status_code == 200, r.text
    assert r.json()["vide"] is False and r.json()["compteurs"]["factures"] == 3

    r = client.post(
        "/api/v1/qbo-doublons/desactiver",
        json={"scope": "construction", "source_id": plein, "cible_id": garde},
        headers=owner_headers,
    )
    assert r.status_code == 409, r.text
    assert "3 factures" in r.json()["detail"]
    assert h.desactives == []

    # Une transaction que QuickBooks ne laisse pas compter : pas « vide ».
    h.refus.add("RefundReceipt")
    r = client.get("/api/v1/qbo-doublons/apercu", params={"scope": "construction", "id": vide}, headers=owner_headers)
    assert r.json()["vide"] is False and r.json()["inconnus"] == ["remboursements"]
    h.refus.clear()

    r = client.post(
        "/api/v1/qbo-doublons/desactiver",
        json={"scope": "construction", "source_id": vide, "cible_id": garde},
        headers=owner_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["desactivee"] is True
    assert h.desactives == [vide]
    assert _lire(run, TimesheetCompany, comp).qbo_customer_id == garde


def test_compagnie_inconnue_ou_non_connectee(client, owner_headers, qb):
    r = client.get("/api/v1/qbo-doublons/analyse", params={"scope": "nimporte"}, headers=owner_headers)
    assert r.status_code == 404
    qb["inc"].ready = False
    try:
        r = client.get("/api/v1/qbo-doublons/analyse", params={"scope": "inc:77"}, headers=owner_headers)
        assert r.status_code == 503
        assert "Connecter QuickBooks" in r.json()["detail"]
    finally:
        qb["inc"].ready = True


def test_webhook_merge_intuit_suivi(client, run, monkeypatch, qb):
    """Fusion faite dans QuickBooks sans passer par Kratos : le webhook
    « Merge » d'Intuit (id gardé, deletedId disparu) suffit."""
    from app.api.v1.endpoints import qbo_webhook

    i = qb["inc"]
    garde = i.ajouter("Toitures Lavoie inc.")
    doublon = i.ajouter("Toitures Lavoie")
    i.fusionner(doublon)
    _ajouter(run, _mensuelle(R_INC, doublon, date(2026, 10, 1)))

    vus: List[Any] = []
    reel = qbo_webhook._suivre_fusions_clients

    async def _suivre(fusions):
        vus.extend(fusions)
        await reel(fusions)

    monkeypatch.setattr(qbo_webhook, "_suivre_fusions_clients", _suivre)
    monkeypatch.setattr(qbo_webhook, "AsyncSessionLocal", TestSessionLocal)
    monkeypatch.setattr(qbo_webhook.settings, "qbo_webhook_verifier_token", "jeton-doublons")
    monkeypatch.setattr(qbo_webhook.settings, "qbo_realm_id", R_HORIZON)

    corps = json.dumps(
        {
            "eventNotifications": [
                {
                    "realmId": R_INC,
                    "dataChangeEvent": {
                        "entities": [
                            {"name": "Customer", "id": garde, "deletedId": doublon, "operation": "Merge"}
                        ]
                    },
                }
            ]
        }
    ).encode()
    signature = base64.b64encode(hmac.new(b"jeton-doublons", corps, hashlib.sha256).digest()).decode()

    # Le realm de l'INC est connu par sa ligne qbo_connections.
    from app.models.qbo_connection import QboConnection

    _ajouter(run, QboConnection(scope="inc:77", refresh_token="x", realm_id=R_INC))
    try:
        r = client.post(
            "/api/v1/qbo/webhook",
            content=corps,
            headers={"intuit-signature": signature, "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text
        run(asyncio.sleep(0.2))
        assert vus == [(R_INC, doublon, garde)]
        assert [(m.qbo_customer_id) for m in _mensuelles(run, R_INC)] == [garde]
    finally:
        async def _menage():
            async with TestSessionLocal() as s:
                for c in (await s.execute(select(QboConnection).where(QboConnection.scope == "inc:77"))).scalars():
                    await s.delete(c)
                await s.commit()

        run(_menage())
