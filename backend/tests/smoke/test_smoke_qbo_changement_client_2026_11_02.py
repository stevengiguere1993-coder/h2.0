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
        self.reactivations: List[str] = []

    def _ajouter(self, nom: str, parent: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
        for r in self.customers.values():
            if r["DisplayName"].lower() == nom.lower():  # actif ou non
                raise QuickBooksError("Duplicate Name Exists Error (6240)")
        return super()._ajouter(nom, parent, **extra)

    async def find_customer_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        trouves = [
            r for r in self.customers.values()
            if not r.get("ParentRef") and self._actif(r)
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

    # Comme QuickBooks : les requêtes ne renvoient que les clients ACTIFS,
    # sauf « Active IN (true, false) ».
    @staticmethod
    def _actif(r: Dict[str, Any]) -> bool:
        return r.get("Active") is not False

    async def query_all(self, sql: str) -> List[Dict[str, Any]]:
        assert "FROM Customer" in sql
        tous = "Active IN" in sql
        return [dict(r) for r in self.customers.values() if tous or self._actif(r)]

    async def all_customers_any(self) -> List[Dict[str, Any]]:
        return await self.query_all("SELECT * FROM Customer WHERE Active IN (true, false)")

    async def get_customer(self, cid: str) -> Optional[Dict[str, Any]]:
        r = self.customers.get(str(cid))
        return dict(r) if r and self._actif(r) else None

    async def get_customer_any(self, cid: str) -> Optional[Dict[str, Any]]:
        r = self.customers.get(str(cid))
        return dict(r) if r else None

    async def find_customer_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        for r in self.customers.values():
            if r["DisplayName"].lower() == name.lower() and self._actif(r):
                return dict(r)
        return None

    async def find_subcustomers(self, parent_customer_id: str) -> List[Dict[str, Any]]:
        return [
            dict(r) for r in self.customers.values()
            if (r.get("ParentRef") or {}).get("value") == str(parent_customer_id) and self._actif(r)
        ]

    async def set_customer_active(self, cid: str, active: bool) -> Optional[Dict[str, Any]]:
        r = self.customers.get(str(cid))
        if r is None:
            return None
        r["Active"] = bool(active)
        self.reactivations.append(cid) if active else None
        return dict(r)


@pytest.fixture()
def qb(client, monkeypatch) -> _QbCompagnie:
    """``client`` : crée le schéma de test."""
    fake = _QbCompagnie()
    monkeypatch.setattr("app.integrations.quickbooks.get_qbo", lambda scope="construction": fake)
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", TestSessionLocal)
    return fake


def _suffixe() -> str:
    # Lettres seulement : un suffixe tout en chiffres ferait passer un nom
    # de personne pour un nom de compagnie (numéro d'entreprise).
    return "".join(chr(ord("a") + int(c, 16) % 26) for c in uuid.uuid4().hex[:8])


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


# ── Retour de Steven après la mise en prod : la fiche du Groupe était
# reliée au client QB #179, qui n'est pas « Groupe 1660 Saint-Clément
# inc. » (une autre compagnie du même propriétaire, même courriel). ──


def _relier_fiche(run, client_id: int, qb_id: str) -> None:
    async def _go() -> None:
        async with TestSessionLocal() as s:
            c = await s.get(Client, client_id)
            c.qbo_customer_id = qb_id
            await s.commit()

    run(_go())


def test_fiche_reliee_a_une_autre_compagnie_le_groupe_est_cree(run, qb):
    x = _suffixe()
    courriel = f"philippe-{x}@example.com"
    ids = _seed(
        run, qb, adresse=f"1660 Rue Saint-Clément {x}", ancien=f"MGV Développement inc. {x}",
        nouveau=f"Groupe 1660 Saint-Clément inc. {x}", courriel=f"mgv-{x}@example.com",
    )
    meuser = qb._ajouter(f"Immobilier Meuser 1 inc. {x}", PrimaryEmailAddr={"Address": courriel})
    # État laissé par la première version : fiche reliée à #179 (Meuser),
    # sous-client déplacé sous lui.
    _relier_fiche(run, ids["nouveau_client"], meuser["Id"])
    qb.customers[ids["sous"]]["ParentRef"] = {"value": meuser["Id"]}

    res = _synchro(run, ids["project_id"])

    groupe = qb.customers[res["parent_customer_id"]]
    assert groupe["DisplayName"] == f"Groupe 1660 Saint-Clément inc. {x}"
    assert res["parent_customer_id"] != meuser["Id"]
    assert res["action"] == "deplace" and res["qbo_job_id"] == ids["sous"]
    assert qb.customers[ids["sous"]]["ParentRef"]["value"] == groupe["Id"]
    assert qb.customers[meuser["Id"]]["DisplayName"] == f"Immobilier Meuser 1 inc. {x}"
    assert _lire(run, Client, ids["nouveau_client"]).qbo_customer_id == groupe["Id"]


def test_client_inactif_au_bon_nom_est_reactive_pas_recree(run, qb):
    x = _suffixe()
    ids = _seed(
        run, qb, adresse=f"12 rue Ontario {x}", ancien=f"Ancienne cie inc. {x}",
        nouveau=f"Groupe Ontario inc. {x}", courriel=f"o-{x}@example.com",
    )
    inactif = qb._ajouter(f"Groupe Ontario inc. {x}", Active=False)
    _relier_fiche(run, ids["nouveau_client"], inactif["Id"])
    nb = len(qb.customers)

    res = _synchro(run, ids["project_id"])

    assert res["parent_customer_id"] == inactif["Id"]
    assert qb.customers[inactif["Id"]]["Active"] is True
    assert inactif["Id"] in qb.reactivations
    assert len(qb.customers) == nb
    assert qb.customers[ids["sous"]]["ParentRef"]["value"] == inactif["Id"]


def test_nom_avec_accents_differents_est_le_meme_client(run, qb):
    x = _suffixe()
    ids = _seed(
        run, qb, adresse=f"3 rue Hébert {x}", ancien=f"Vieille cie inc. {x}",
        nouveau=f"Groupe Saint-Clément inc. {x}", courriel=f"h-{x}@example.com",
    )
    sans_accent = qb._ajouter(f"Groupe Saint-Clement inc {x}")
    nb = len(qb.customers)

    res = _synchro(run, ids["project_id"])

    assert res["parent_customer_id"] == sans_accent["Id"]
    assert len(qb.customers) == nb


def test_personne_renommee_garde_son_client_qb(run, qb):
    """« Tremblay Jean » dans QB, « Jean Tremblay » dans Kratos : même
    personne, le lien tient (rien n'est créé)."""
    x = _suffixe()
    qb_jean = qb._ajouter(f"Tremblay Jean {x}")
    sous = qb._ajouter(f"8 rue Panet {x}", qb_jean["Id"])

    async def _go() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            c = Client(name=f"Jean Tremblay {x}", qbo_customer_id=qb_jean["Id"])
            s.add(c)
            await s.flush()
            p = Project(name="Cuisine", address=f"8 rue Panet {x}", client_id=c.id,
                        kind="construction", qbo_job_id=sous["Id"])
            s.add(p)
            await s.commit()
            return {"project_id": p.id}

    ids = run(_go())
    nb = len(qb.customers)
    res = _synchro(run, ids["project_id"])
    assert res["action"] == "deja_lie"
    assert res["parent_customer_id"] == qb_jean["Id"]
    assert len(qb.customers) == nb


def test_facture_ne_cree_pas_de_second_sous_client(run, qb):
    """Hors synchro du projet (facture, coût, heures), un client mère qui
    n'est pas celui mémorisé sur la fiche ne déplace rien et ne crée pas
    de second sous-client : le sous-client existant sert."""
    from app.services.qbo_project_resolve import resolve_project_customer_id

    x = _suffixe()
    ids = _seed(
        run, qb, adresse=f"40 rue Notre-Dame {x}", ancien=f"Un inc. {x}",
        nouveau=f"Deux inc. {x}", courriel=f"f-{x}@example.com",
    )
    autre = qb._ajouter(f"Deux inc. {x}")
    nb = len(qb.customers)

    async def _go() -> str:
        async with TestSessionLocal() as s:
            p = await s.get(Project, ids["project_id"])
            jid = await resolve_project_customer_id(qb, s, p, autre["Id"])
            await s.commit()
            return jid

    assert run(_go()) == ids["sous"]
    assert len(qb.customers) == nb
    assert qb.deplacements == []
