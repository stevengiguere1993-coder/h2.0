"""Smoke — sous-clients QuickBooks à convertir en PROJET (Steven, 2026-10-14).

Intuit ne crée pas de projet QuickBooks par API sans palier Silver ; la
conversion se fait dans QuickBooks (extension Chrome ou à la main) et
Kratos la CONSTATE par l'API (``Customer.IsProject``). Ici : le sous-client
créé pour un projet entre dans la liste, la vérification le raye une fois
converti (même si QuickBooks a changé son id), l'extension lit la liste et
rend compte, ignorer / reprendre, ajout des projets existants.

Client QuickBooks factice : aucun appel réseau.
"""
from __future__ import annotations

import itertools
import uuid
from typing import Any, Dict, List, Optional

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.client import Client
from app.models.project import Project
from app.models.user import User
from app.services import qbo_projets_conversion as svc
from app.services.bon_project import ensure_project_qbo_job

from .conftest import TestSessionLocal

CLE_EXTENSION = "cle-extension-smoke"


class _FakeQbo:
    """Compagnie Construction : clients et sous-clients par Id ; la
    conversion en projet (faite dans l'écran de QB) remplace le
    sous-client par un nouvel objet IsProject, comme QuickBooks."""

    ready = True
    realm_id = "9130"
    #: Ids uniques d'un test à l'autre (la base SQLite est partagée : un
    #: id repris par une autre compagnie factice ferait croire à un lien).
    compteur = itertools.count(100)

    def __init__(self) -> None:
        self.customers: Dict[str, Dict[str, Any]] = {}

    def _ajouter(self, nom: str, parent: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
        cid = str(next(_FakeQbo.compteur))
        row: Dict[str, Any] = {"Id": cid, "DisplayName": nom, "SyncToken": "0", "Active": True}
        if parent:
            pnom = self.customers[parent]["DisplayName"]
            row.update(
                FullyQualifiedName=f"{pnom}:{nom}",
                ParentRef={"value": parent},
                Job=True,
                BillWithParent=True,
            )
        else:
            row["FullyQualifiedName"] = nom
        row.update(extra)
        self.customers[cid] = row
        return row

    def convertir(self, cid: str) -> str:
        """Conversion dans l'écran Projets de QB : l'ancien sous-client
        disparaît, un projet (IsProject) du même nom le remplace."""
        old = self.customers.pop(cid)
        row = self._ajouter(old["DisplayName"], old["ParentRef"]["value"], IsProject=True)
        return row["Id"]

    async def _load_refresh_from_db(self) -> None:
        return None

    async def query_all(self, sql: str) -> List[Dict[str, Any]]:
        assert "FROM Customer" in sql
        return [dict(r) for r in self.customers.values()]

    async def get_customer(self, cid: str) -> Optional[Dict[str, Any]]:
        r = self.customers.get(str(cid))
        return dict(r) if r else None

    async def find_customer_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        for r in self.customers.values():
            if r["DisplayName"] == name:
                return dict(r)
        return None

    async def ensure_customer(self, *, display_name: str, **_: Any) -> Dict[str, Any]:
        return (await self.find_customer_by_name(display_name)) or self._ajouter(display_name)

    async def find_subcustomers(self, parent_customer_id: str) -> List[Dict[str, Any]]:
        return [
            dict(r)
            for r in self.customers.values()
            if (r.get("ParentRef") or {}).get("value") == str(parent_customer_id)
        ]

    async def ensure_project(
        self, *, parent_customer_id: str, project_name: str, start_date: Any = None
    ) -> Dict[str, Any]:
        for r in await self.find_subcustomers(parent_customer_id):
            if r["DisplayName"] == project_name:
                return r
        return self._ajouter(project_name, str(parent_customer_id))


def _compte(run, role: str) -> int:
    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = User(
                email=f"smoke-conv-{role}-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password=get_password_hash("smoke-conv-x"),
                is_active=True,
                is_admin=role in ("owner", "admin"),
                role=role,
            )
            s.add(u)
            await s.commit()
            return u.id

    return run(_seed())


def _entetes(user_id: int) -> Dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=str(user_id))}"}


@pytest.fixture(scope="module")
def owner_headers(client, run) -> Dict[str, str]:
    """La section Comptabilité est réservée aux propriétaires."""
    return _entetes(_compte(run, "owner"))


@pytest.fixture()
def fake_qbo(monkeypatch) -> _FakeQbo:
    fake = _FakeQbo()
    # get_qbo est importé LOCALEMENT dans les services : patcher la source suffit.
    monkeypatch.setattr("app.integrations.quickbooks.get_qbo", lambda scope="construction": fake)
    return fake


@pytest.fixture()
def cle_extension(monkeypatch) -> Dict[str, str]:
    monkeypatch.setattr("app.api.v1.endpoints.extension.EXTENSION_API_KEY", CLE_EXTENSION)
    return {"X-Extension-Key": CLE_EXTENSION}


def _projet(run, *, nom: str, adresse: Optional[str], client_nom: str, **extra: Any) -> Dict[str, int]:
    async def _seed() -> Dict[str, int]:
        async with TestSessionLocal() as s:
            c = Client(name=client_nom, email=f"{uuid.uuid4().hex[:6]}@example.com")
            s.add(c)
            await s.flush()
            p = Project(name=nom, address=adresse, client_id=c.id, kind="construction", **extra)
            s.add(p)
            await s.commit()
            return {"client_id": c.id, "project_id": p.id}

    return run(_seed())


def _lier(run, project_id: int) -> Dict[str, Any]:
    """Comme push_project_qbo_job_now : crée le sous-client QB du projet."""

    async def _go() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            p = await s.get(Project, project_id)
            res = await ensure_project_qbo_job(s, p)
            await s.commit()
            return res

    return run(_go())


def _etat(run, project_id: int) -> Dict[str, Any]:
    async def _go() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            p = await s.get(Project, project_id)
            return {
                "qbo_job_id": p.qbo_job_id,
                "qbo_job_name": p.qbo_job_name,
                "etat": p.qbo_conversion_etat,
                "detail": p.qbo_conversion_detail,
                "le": p.qbo_conversion_le,
            }

    return run(_go())


# ── Tests ───────────────────────────────────────────────────────────


def test_sous_client_cree_entre_dans_la_liste(client, run, owner_headers, fake_qbo):
    ids = _projet(run, nom="Toiture", adresse="29 rue Besner", client_nom="Jean Tremblay")
    res = _lier(run, ids["project_id"])
    assert res["action"] == "cree"
    e = _etat(run, ids["project_id"])
    assert e["etat"] == svc.A_CONVERTIR
    assert e["qbo_job_name"] == "29 rue Besner"
    assert fake_qbo.customers[e["qbo_job_id"]]["ParentRef"]

    r = client.get("/api/v1/qbo-conversions", headers=owner_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    ligne = next(l for l in body["a_convertir"] if l["project_id"] == ids["project_id"])
    assert ligne["sous_client"] == "29 rue Besner"
    assert ligne["client"] == "Jean Tremblay"
    assert ligne["sous_client_complet"] == "Jean Tremblay:29 rue Besner"
    assert body["quickbooks"]["lien_projets"].endswith("/app/projects")

    # Relancer la liaison (lien déjà valide) ne change rien.
    assert _lier(run, ids["project_id"])["action"] == "deja_lie"
    assert _etat(run, ids["project_id"])["etat"] == svc.A_CONVERTIR


def test_sous_client_deja_projet_est_note_converti(client, run, owner_headers, fake_qbo):
    """Le projet QB existe déjà (créé à la main dans QB) : adopté, et
    rien à convertir."""
    ids = _projet(run, nom="Cuisine", adresse="12 rue Dupuis", client_nom="Marie Côté")
    parent = fake_qbo._ajouter("Marie Côté")
    fake_qbo._ajouter("12 rue Dupuis", parent["Id"], IsProject=True)
    res = _lier(run, ids["project_id"])
    assert res["action"] == "adopte"
    assert _etat(run, ids["project_id"])["etat"] == svc.CONVERTIE


def test_verifier_constate_la_conversion_meme_si_l_id_change(client, run, owner_headers, fake_qbo):
    ids = _projet(run, nom="Rénovation", adresse="1616 rue Saint-Alexandre", client_nom="Paul Roy")
    _lier(run, ids["project_id"])
    ancien = _etat(run, ids["project_id"])["qbo_job_id"]

    # Pas encore converti : rien ne bouge.
    r = client.post("/api/v1/qbo-conversions/verifier", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert ids["project_id"] in r.json()["restantes"]
    assert _etat(run, ids["project_id"])["etat"] == svc.A_CONVERTIR

    # Conversion dans l'écran de QB : nouvel id, IsProject.
    nouveau = fake_qbo.convertir(ancien)
    r = client.post("/api/v1/qbo-conversions/verifier", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert ids["project_id"] in r.json()["converties"]
    e = _etat(run, ids["project_id"])
    assert e["etat"] == svc.CONVERTIE
    assert e["qbo_job_id"] == nouveau
    assert e["le"] is not None

    body = client.get("/api/v1/qbo-conversions", headers=owner_headers).json()
    assert ids["project_id"] not in [l["project_id"] for l in body["a_convertir"]]
    assert ids["project_id"] in [l["project_id"] for l in body["converties"]]


def test_verifier_ne_cree_rien_quand_le_sous_client_a_disparu(client, run, owner_headers, fake_qbo):
    ids = _projet(run, nom="Garage", adresse="8 rue Lavoie", client_nom="Luc Gagnon")
    _lier(run, ids["project_id"])
    jid = _etat(run, ids["project_id"])["qbo_job_id"]
    fake_qbo.customers.pop(jid)  # supprimé dans QB, sans projet à la place
    nb = len(fake_qbo.customers)
    r = client.post("/api/v1/qbo-conversions/verifier", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert len(fake_qbo.customers) == nb  # une vérification ne crée rien
    e = _etat(run, ids["project_id"])
    assert e["etat"] == svc.A_CONVERTIR
    assert "introuvable" in (e["detail"] or "")


def test_extension_lit_la_liste_et_rend_compte(client, run, owner_headers, fake_qbo, cle_extension):
    ids = _projet(run, nom="Balcon", adresse="45 rue Papineau", client_nom="Anne Lemay")
    _lier(run, ids["project_id"])

    assert client.post("/api/v1/extension/qbo-conversions").status_code == 401

    r = client.post("/api/v1/extension/qbo-conversions", headers=cle_extension)
    assert r.status_code == 200, r.text
    body = r.json()
    item = next(i for i in body["items"] if i["project_id"] == ids["project_id"])
    assert item["nom"] == "45 rue Papineau"
    assert item["client"] == "Anne Lemay"
    assert body["lien_projets"].endswith("/app/projects")

    # L'extension dit « fait » mais QB ne montre pas de projet : on ne
    # croit que l'API — la ligne reste, avec le compte rendu.
    r = client.post(
        "/api/v1/extension/qbo-conversions/resultat",
        headers=cle_extension,
        json={"resultats": [{"project_id": ids["project_id"], "ok": True, "detail": "conversion faite"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["converties"] == []
    e = _etat(run, ids["project_id"])
    assert e["etat"] == svc.A_CONVERTIR
    assert "extension" in (e["detail"] or "") and "conversion faite" in (e["detail"] or "")

    # Cette fois QB a bien le projet.
    fake_qbo.convertir(e["qbo_job_id"])
    r = client.post(
        "/api/v1/extension/qbo-conversions/resultat",
        headers=cle_extension,
        json={"resultats": [{"project_id": ids["project_id"], "ok": True}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["converties"] == [ids["project_id"]]
    assert _etat(run, ids["project_id"])["etat"] == svc.CONVERTIE
    assert ids["project_id"] not in [
        i["project_id"]
        for i in client.post("/api/v1/extension/qbo-conversions", headers=cle_extension).json()["items"]
    ]


def test_ignorer_et_reprendre(client, run, owner_headers, fake_qbo):
    ids = _projet(run, nom="Clôture", adresse="3 rue Hamel", client_nom="Éric Blais")
    _lier(run, ids["project_id"])
    pid = ids["project_id"]

    r = client.post(f"/api/v1/qbo-conversions/{pid}/ignorer", headers=owner_headers)
    assert r.status_code == 200, r.text
    body = client.get("/api/v1/qbo-conversions", headers=owner_headers).json()
    assert pid in [l["project_id"] for l in body["ignorees"]]
    assert pid not in [l["project_id"] for l in body["a_convertir"]]
    # Ignoré : l'extension ne le voit plus, une re-liaison ne le remet pas.
    assert _lier(run, pid)["action"] == "deja_lie"
    assert _etat(run, pid)["etat"] == svc.IGNOREE

    r = client.post(f"/api/v1/qbo-conversions/{pid}/reprendre", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert _etat(run, pid)["etat"] == svc.A_CONVERTIR

    assert client.post("/api/v1/qbo-conversions/999999/ignorer", headers=owner_headers).status_code == 404


def test_ajouter_les_projets_existants(client, run, owner_headers, fake_qbo):
    """Projets d'avant cette fonction (état vide) : seuls ceux dont le
    sous-client QB n'est pas encore un projet entrent dans la liste."""
    parent = fake_qbo._ajouter("Client Historique")
    sous = fake_qbo._ajouter("100 rue Ancienne", parent["Id"])
    proj = fake_qbo._ajouter("200 rue Convertie", parent["Id"], IsProject=True)
    a = _projet(run, nom="Ancien", adresse="100 rue Ancienne", client_nom="Client Historique", qbo_job_id=sous["Id"])
    b = _projet(run, nom="Converti", adresse="200 rue Convertie", client_nom="Client Historique", qbo_job_id=proj["Id"])
    c = _projet(run, nom="Sans lien", adresse="300 rue Vide", client_nom="Client Historique")
    assert _etat(run, a["project_id"])["etat"] is None

    r = client.post("/api/v1/qbo-conversions/ajouter-existants", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert r.json()["ajoutes"] >= 1 and r.json()["deja_converties"] >= 1
    assert _etat(run, a["project_id"])["etat"] == svc.A_CONVERTIR
    assert _etat(run, a["project_id"])["qbo_job_name"] == "100 rue Ancienne"
    assert _etat(run, b["project_id"])["etat"] == svc.CONVERTIE
    assert _etat(run, c["project_id"])["etat"] is None


def test_sans_quickbooks_la_verification_le_dit(client, run, owner_headers, fake_qbo):
    fake_qbo.ready = False
    ids = _projet(run, nom="Hors ligne", adresse="1 rue Nulle", client_nom="Zoé Nadeau")

    async def _marquer() -> None:
        async with TestSessionLocal() as s:
            p = await s.get(Project, ids["project_id"])
            svc.demander(p)
            await s.commit()

    run(_marquer())
    r = client.post("/api/v1/qbo-conversions/verifier", headers=owner_headers)
    assert r.status_code == 409, r.text
    assert "QuickBooks" in r.json()["detail"]

    # Le cron, lui, ne lève pas : il dit pourquoi il a sauté.
    async def _cron() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            return await svc.verifier_pour_cron(s)

    assert "skipped" in run(_cron())


def test_section_reservee_aux_proprietaires(client, run, fake_qbo):
    employe = _entetes(_compte(run, "employee"))
    assert client.get("/api/v1/qbo-conversions", headers=employe).status_code in (401, 403)
