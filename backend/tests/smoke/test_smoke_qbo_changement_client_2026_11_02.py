"""Smoke — projet changé de client : son sous-client QuickBooks suit
(Steven, 2026-11-02).

« Le client du projet 1660 Saint-Clément a changé dans Kratos. Il ne s'est
pas changé dans QuickBooks. 1660 Saint-Clément devrait maintenant être
sous-client du client mère Groupe 1660 Saint-Clément inc. Le système
devrait vérifier si Groupe 1660 Saint-Clément inc. existe dans QuickBooks
et effectuer le changement. »

Client QuickBooks factice (nom d'affichage unique, repli par courriel
UNIQUE comme le vrai ``ensure_customer``) : aucun appel réseau.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import text

from app.integrations.quickbooks import QuickBooksError
from app.models.client import Client
from app.models.project import Project
from app.services.bon_project import ensure_project_qbo_job

from .conftest import TestSessionLocal
from .test_smoke_qbo_projets_conversion_2026_10_14 import _FakeQbo


class _QbCompagnie(_FakeQbo):
    """Ajoute ce que le vrai client QB fait : courriel, création, nom
    d'affichage unique, déplacement d'un sous-client, désactivation."""

    def __init__(self) -> None:
        super().__init__()
        self.deplacements: List[tuple] = []
        self.refuser_deplacement = False

    def _ajouter(self, nom: str, parent: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
        for r in self.customers.values():
            if r["DisplayName"].lower() == nom.lower():
                raise QuickBooksError("Duplicate Name Exists Error (6240)")
        return super()._ajouter(nom, parent, **extra)

    async def find_customer_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        trouves = [
            r for r in self.customers.values()
            if not r.get("ParentRef")
            and ((r.get("PrimaryEmailAddr") or {}).get("Address") or "").lower() == email.lower()
        ]
        return dict(trouves[0]) if len(trouves) == 1 else None

    async def create_customer(self, *, display_name: str, email: Optional[str] = None, **_: Any) -> Dict[str, Any]:
        extra = {"PrimaryEmailAddr": {"Address": email}} if email else {}
        return dict(self._ajouter(display_name, **extra))

    async def ensure_customer(self, *, display_name: str, email: Optional[str] = None, **kw: Any) -> Dict[str, Any]:
        trouve = await self.find_customer_by_name(display_name)
        if trouve is None and email:
            trouve = await self.find_customer_by_email(email)
        return trouve or await self.create_customer(display_name=display_name, email=email)

    async def move_subcustomer(self, cid: str, parent: str) -> Optional[Dict[str, Any]]:
        if self.refuser_deplacement:
            raise QuickBooksError("Projet : changement de client refusé")
        row = self.customers.get(str(cid))
        if row is None:
            return None
        self.deplacements.append((cid, row["ParentRef"]["value"], parent))
        row["ParentRef"] = {"value": parent}
        row["FullyQualifiedName"] = f"{self.customers[parent]['DisplayName']}:{row['DisplayName']}"
        return dict(row)

    async def deactivate_customer(self, cid: str) -> bool:
        self.customers[str(cid)]["Active"] = False
        return True


@pytest.fixture()
def qb(client, monkeypatch) -> _QbCompagnie:
    """``client`` : crée le schéma de test."""
    fake = _QbCompagnie()
    monkeypatch.setattr("app.integrations.quickbooks.get_qbo", lambda scope="construction": fake)
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", TestSessionLocal)
    return fake


def _suffixe() -> str:
    return uuid.uuid4().hex[:6]


def _seed(run, qb: _QbCompagnie, *, adresse: str, ancien: str, nouveau: str, courriel: str) -> Dict[str, Any]:
    """Projet lié à son sous-client sous l'ANCIEN client, puis client
    changé dans Kratos (comme sur la fiche du projet)."""
    mere = qb._ajouter(ancien, PrimaryEmailAddr={"Address": courriel})
    sous = qb._ajouter(adresse, mere["Id"])

    async def _go() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            c_old = Client(name=ancien, email=courriel, qbo_customer_id=mere["Id"])
            c_new = Client(name=nouveau, email=courriel)
            s.add_all([c_old, c_new])
            await s.flush()
            p = Project(
                name=f"Projet — {ancien}", address=adresse, client_id=c_old.id,
                kind="construction", qbo_job_id=sous["Id"],
            )
            s.add(p)
            await s.flush()
            p.client_id = c_new.id  # changement de client dans Kratos
            await s.commit()
            return {"project_id": p.id, "nouveau_client": c_new.id, "ancien_client": c_old.id}

    ids = run(_go())
    ids.update(mere=mere["Id"], sous=sous["Id"])
    return ids


def _synchro(run, project_id: int) -> Dict[str, Any]:
    async def _go() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            p = await s.get(Project, project_id)
            res = await ensure_project_qbo_job(s, p)
            await s.commit()
            return res

    return run(_go())


def _lire(run, model, pk) -> Any:
    async def _go() -> Any:
        async with TestSessionLocal() as s:
            return await s.get(model, pk)

    return run(_go())


def test_client_change_le_sous_client_est_deplace_et_le_client_mere_cree(run, qb):
    """Cas 1660 Saint-Clément : même courriel pour les deux compagnies, le
    Groupe n'existe pas encore dans QuickBooks."""
    x = _suffixe()
    ids = _seed(
        run, qb, adresse=f"1660 Rue Saint-Clément {x}, Montréal",
        ancien=f"MGV Développement inc. {x}", nouveau=f"Groupe 1660 Saint-Clément inc. {x}",
        courriel=f"proprio-{x}@example.com",
    )
    nb_avant = len(qb.customers)

    res = _synchro(run, ids["project_id"])

    assert res["action"] == "deplace"
    assert res["qbo_job_id"] == ids["sous"]  # même sous-client, historique gardé
    groupe = qb.customers[res["parent_customer_id"]]
    assert groupe["DisplayName"] == f"Groupe 1660 Saint-Clément inc. {x}"  # créé
    assert res["parent_customer_id"] != ids["mere"]  # pas MGV par le courriel
    assert qb.customers[ids["sous"]]["ParentRef"]["value"] == groupe["Id"]
    assert len(qb.customers) == nb_avant + 1  # le Groupe seulement, aucun doublon
    assert qb.customers[ids["mere"]]["DisplayName"] == f"MGV Développement inc. {x}"
    assert _lire(run, Client, ids["nouveau_client"]).qbo_customer_id == groupe["Id"]
    assert _lire(run, Project, ids["project_id"]).qbo_job_id == ids["sous"]

    # Relancer : rien ne bouge.
    assert _synchro(run, ids["project_id"])["action"] == "deja_lie"
    assert len(qb.deplacements) == 1


def test_client_mere_existant_est_reutilise(run, qb):
    x = _suffixe()
    ids = _seed(
        run, qb, adresse=f"22 rue Fortin {x}", ancien=f"Ancien {x}",
        nouveau=f"Nouveau {x}", courriel=f"a-{x}@example.com",
    )
    existant = qb._ajouter(f"Nouveau {x}")
    nb_avant = len(qb.customers)

    res = _synchro(run, ids["project_id"])

    assert res["action"] == "deplace"
    assert res["parent_customer_id"] == existant["Id"]
    assert qb.customers[ids["sous"]]["ParentRef"]["value"] == existant["Id"]
    assert len(qb.customers) == nb_avant


def test_sous_client_deja_cree_sous_le_nouveau_client_est_adopte(run, qb):
    x = _suffixe()
    ids = _seed(
        run, qb, adresse=f"5 rue Vallée {x}", ancien=f"Vieux {x}",
        nouveau=f"Neuf {x}", courriel=f"b-{x}@example.com",
    )
    neuf = qb._ajouter(f"Neuf {x}")
    # Un sous-client au nom exact existe déjà sous le nouveau client
    # (créé à la main) — QB refuse deux noms identiques, d'où l'unité.
    qb.customers[ids["sous"]]["DisplayName"] = f"5 rue Vallée {x} (ancien)"
    deja = qb._ajouter(f"5 rue Vallée {x}", neuf["Id"])

    res = _synchro(run, ids["project_id"])

    assert res["action"] == "adopte"
    assert res["qbo_job_id"] == deja["Id"]
    assert qb.deplacements == []


def test_quickbooks_refuse_le_deplacement_repli_sur_creation(run, qb):
    """Un projet QB ne peut pas changer de client : on retombe sur la
    création d'un sous-client sous le nouveau client (comportement
    d'avant), sans planter."""
    x = _suffixe()
    ids = _seed(
        run, qb, adresse=f"9 rue Roy {x}", ancien=f"Alpha {x}",
        nouveau=f"Beta {x}", courriel=f"c-{x}@example.com",
    )
    qb.refuser_deplacement = True

    res = _synchro(run, ids["project_id"])

    assert res["action"] == "cree"
    assert res["qbo_job_id"] != ids["sous"]
    assert qb.customers[res["qbo_job_id"]]["ParentRef"]["value"] == res["parent_customer_id"]


def test_reparation_1660_doublon_cree_avant_le_correctif(run, qb):
    """Avant le correctif, Kratos avait créé un second sous-client au nom
    dérivé sous le Groupe et laissé l'original sous MGV : la réparation
    ponctuelle déplace l'original, y relie le projet et rend le doublon
    inactif."""
    from app.services import qbo_sous_clients_client_change as filet

    x = _suffixe()
    adresse = f"1660 Rue Saint-Clément, Montréal {x}"
    ids = _seed(
        run, qb, adresse=adresse, ancien=f"MGV Développement inc. {x}",
        nouveau=f"Groupe 1660 Saint-Clément inc. {x}", courriel=f"d-{x}@example.com",
    )
    groupe = qb._ajouter(f"Groupe 1660 Saint-Clément inc. {x}")
    doublon = qb._ajouter(f"{adresse} — Projet — MGV Développement inc. {x}", groupe["Id"])

    async def _etat_avant() -> None:
        async with TestSessionLocal() as s:
            p = await s.get(Project, ids["project_id"])
            p.qbo_job_id = doublon["Id"]
            c = await s.get(Client, ids["nouveau_client"])
            c.qbo_customer_id = groupe["Id"]
            await s.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS applied_backfills ("
                    "key VARCHAR(120) PRIMARY KEY, "
                    "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            await s.execute(
                text("DELETE FROM applied_backfills WHERE key = :k"),
                {"k": filet.CLE_REPARATION_1660},
            )
            await s.commit()

    run(_etat_avant())

    out = run(filet.filet_sous_clients_client_change())

    assert out["reparation_1660"]["originaux"]
    p = _lire(run, Project, ids["project_id"])
    assert p.qbo_job_id == ids["sous"]
    assert qb.customers[ids["sous"]]["ParentRef"]["value"] == groupe["Id"]
    assert qb.customers[doublon["Id"]]["Active"] is False

    # Une seule fois.
    assert "reparation_1660" not in run(filet.filet_sous_clients_client_change())


def test_filet_replace_un_sous_client_reste_sous_l_ancien_client(run, qb):
    from app.services import qbo_sous_clients_client_change as filet

    x = _suffixe()
    ids = _seed(
        run, qb, adresse=f"77 rue Lord {x}", ancien=f"Gamma {x}",
        nouveau=f"Delta {x}", courriel=f"e-{x}@example.com",
    )
    delta = qb._ajouter(f"Delta {x}")

    async def _lien() -> None:
        async with TestSessionLocal() as s:
            c = await s.get(Client, ids["nouveau_client"])
            c.qbo_customer_id = delta["Id"]
            await s.commit()

    run(_lien())

    candidats = run(filet.projets_sous_le_mauvais_client(
        {k: dict(v) for k, v in qb.customers.items()}
    ))
    assert ids["project_id"] in candidats
    run(filet.filet_sous_clients_client_change())
    assert qb.customers[ids["sous"]]["ParentRef"]["value"] == delta["Id"]
    candidats = run(filet.projets_sous_le_mauvais_client(
        {k: dict(v) for k, v in qb.customers.items()}
    ))
    assert ids["project_id"] not in candidats
