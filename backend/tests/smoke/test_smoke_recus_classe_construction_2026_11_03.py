"""Smoke — classe « Construction » sur les reçus de chantier déjà dans
QuickBooks (2026-11-03).

Steven : « on a le client et le projet, et la classe doit être
Construction sur tous les reçus qui sont entrés par le volet construction
de Kratos ». Le reçu 8077 (Planchers Économiques, projet 1616
Saint-Alexandre) avait été saisi directement dans QB le 16 octobre avec la
classe « 1616 Saint-Alexandre, Longueuil », puis importé dans Kratos : le
push Kratos → QB pose « Construction » depuis le 17 octobre, mais rien ne
corrigeait les reçus déjà dans QB.

Couvre (QuickBooks simulé en mémoire, aucun appel réseau) :
1. classe « adresse du chantier » → « Construction », le reste intact ;
2. déjà « Construction » → aucune écriture ;
3. la ligne d'un autre client n'est pas touchée ;
4. ligne sans client mais classée au chantier → sous-client du projet posé ;
5. transaction à une ligne que QB n'identifie pas → projet de l'achat ;
6. un Bill (facture fournisseur) se corrige comme une Purchase ;
7. QB injoignable → rien, sans erreur ;
8. filet : rattrapage de tout l'historique une seule fois (une écriture
   par transaction même si plusieurs achats la partagent), puis les
   achats récents ;
9. reçu « client seul » (sans projet) : la ligne du client mère prend
   « Construction », le client est posé s'il manque, un reçu shop n'est
   pas relu.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import delete, text

import app.services.achat_qbo_classe as classe
from app.core.config import settings
from app.integrations.quickbooks import QuickBooksError
from app.models.achat import Achat
from app.models.client import Client
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from tests.smoke.conftest import TestSessionLocal

CONSTRUCTION = "77"
ADRESSE = "1616 Saint-Alexandre, Longueuil"


class FauxQB:
    """Purchases et Bills en mémoire, classes trouvées par nom."""

    def __init__(self) -> None:
        self.ready = True
        self.purchases: Dict[str, Dict[str, Any]] = {}
        self.bills: Dict[str, Dict[str, Any]] = {}
        self.ecritures: List[tuple[str, Dict[str, Any]]] = []
        self.lectures: List[str] = []
        self.classes = {"Construction": {"Id": CONSTRUCTION, "Name": "Construction"}}

    async def _load_refresh_from_db(self) -> None:
        return None

    async def ensure_class(self, *, name: str) -> Optional[Dict[str, Any]]:
        return self.classes.get(name)

    async def get_purchase(self, pid: str) -> Dict[str, Any]:
        self.lectures.append(f"purchase:{pid}")
        if pid not in self.purchases:
            raise QuickBooksError("Object Not Found (610)")
        return copy.deepcopy(self.purchases[pid])

    async def get_bill(self, bid: str) -> Dict[str, Any]:
        self.lectures.append(f"bill:{bid}")
        if bid not in self.bills:
            raise QuickBooksError("Object Not Found (610)")
        return copy.deepcopy(self.bills[bid])

    async def update_purchase(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.ecritures.append(("purchase", copy.deepcopy(payload)))
        self.purchases[str(payload["Id"])] = copy.deepcopy(payload)
        return copy.deepcopy(payload)

    async def update_bill(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.ecritures.append(("bill", copy.deepcopy(payload)))
        self.bills[str(payload["Id"])] = copy.deepcopy(payload)
        return copy.deepcopy(payload)


def _ligne(
    *, montant: float = 1492.18, client: Optional[str] = "J-179",
    classe_id: Optional[str] = "9", classe_nom: Optional[str] = ADRESSE,
    description: str = "Vinyle 4.5mm spc 312",
) -> Dict[str, Any]:
    detail: Dict[str, Any] = {
        "AccountRef": {"value": "88", "name": "Matériaux pour le projet - Réno"},
        "TaxCodeRef": {"value": "5"},
        "BillableStatus": "NotBillable",
    }
    if client:
        detail["CustomerRef"] = {"value": client, "name": "Jean-Francois Croteau:1616"}
    if classe_id:
        detail["ClassRef"] = {"value": classe_id, "name": classe_nom}
    return {
        "Id": "1", "LineNum": 1, "Amount": montant, "Description": description,
        "DetailType": "AccountBasedExpenseLineDetail",
        "AccountBasedExpenseLineDetail": detail,
    }


def _purchase(pid: str, lignes: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "Id": pid, "SyncToken": "3", "DocNumber": "8077", "TxnDate": "2026-10-14",
        "PaymentType": "CreditCard", "AccountRef": {"value": "8022"},
        "EntityRef": {"value": "111", "type": "Vendor"}, "TotalAmt": 1715.63,
        "PrivateNote": "salquote_8077", "Line": lignes,
        "MetaData": {"CreateTime": "2026-10-16T09:40:00-04:00"},
    }


@pytest.fixture()
def faux_qb(monkeypatch, run, db_setup):
    faux = FauxQB()
    monkeypatch.setattr(classe, "get_qbo", lambda *a, **k: faux)
    monkeypatch.setattr(settings, "qbo_achat_class_name", "Construction")
    crees: Dict[str, list[int]] = {
        "achats": [], "projets": [], "fournisseurs": [], "clients": [],
    }
    faux.crees = crees  # type: ignore[attr-defined]

    async def _table() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS applied_backfills ("
                    "key VARCHAR(120) PRIMARY KEY, "
                    "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            await s.execute(
                text("DELETE FROM applied_backfills WHERE key = :k"),
                {"k": classe.CLE_RATTRAPAGE},
            )
            await s.commit()

    run(_table())
    yield faux

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            if crees["achats"]:
                await s.execute(delete(Achat).where(Achat.id.in_(crees["achats"])))
            if crees["projets"]:
                await s.execute(delete(Project).where(Project.id.in_(crees["projets"])))
            if crees["fournisseurs"]:
                await s.execute(
                    delete(Fournisseur).where(Fournisseur.id.in_(crees["fournisseurs"]))
                )
            if crees["clients"]:
                await s.execute(delete(Client).where(Client.id.in_(crees["clients"])))
            await s.execute(
                text("DELETE FROM applied_backfills WHERE key = :k"),
                {"k": classe.CLE_RATTRAPAGE},
            )
            await s.commit()

    run(_nettoyer())


def _seed(
    run, faux: FauxQB, *, qbo_job_id: Optional[str] = "J-179",
    adresse: str = ADRESSE, qbo_purchase_id: Optional[str] = "5199",
    qbo_bill_id: Optional[str] = None,
) -> tuple[int, int]:
    """(projet_id, achat_id) : un chantier et son reçu importé de QB."""

    async def _go() -> tuple[int, int]:
        async with TestSessionLocal() as s:
            f = Fournisseur(name=f"Planchers Économiques {uuid.uuid4().hex[:6]}")
            s.add(f)
            await s.flush()
            p = Project(
                name=f"Projet renovation_complete {uuid.uuid4().hex[:6]}",
                address=adresse, qbo_job_id=qbo_job_id,
            )
            s.add(p)
            await s.flush()
            a = Achat(
                fournisseur_id=f.id, project_id=p.id, kind="material",
                description="Vinyle 4.5mm spc 312", amount=1715.63,
                status="paid", payment_method="cc_steven",
                supplier_invoice_number="8077", qbo_doc_number="8077",
                qbo_purchase_id=qbo_purchase_id, qbo_bill_id=qbo_bill_id,
            )
            s.add(a)
            await s.commit()
            faux.crees["fournisseurs"].append(f.id)  # type: ignore[attr-defined]
            faux.crees["projets"].append(p.id)  # type: ignore[attr-defined]
            faux.crees["achats"].append(a.id)  # type: ignore[attr-defined]
            return int(p.id), int(a.id)

    return run(_go())


def _seed_client(
    run, faux: FauxQB, *, qbo_customer_id: Optional[str] = "C-55",
    qbo_purchase_id: Optional[str] = "5300", is_shop: bool = False,
) -> tuple[Optional[int], int]:
    """(client_id, achat_id) : un reçu « client seul » (sans projet) déjà
    dans QB — ou un reçu shop (ni client ni projet) si ``is_shop``."""

    async def _go() -> tuple[Optional[int], int]:
        async with TestSessionLocal() as s:
            f = Fournisseur(name=f"Rona {uuid.uuid4().hex[:6]}")
            s.add(f)
            await s.flush()
            cl: Optional[Client] = None
            if not is_shop:
                cl = Client(
                    name=f"Jean-Francois Croteau {uuid.uuid4().hex[:6]}",
                    qbo_customer_id=qbo_customer_id,
                )
                s.add(cl)
                await s.flush()
            a = Achat(
                fournisseur_id=f.id, client_id=(cl.id if cl else None),
                is_shop=is_shop, kind="material", description="Fournitures",
                amount=250.0, status="paid", payment_method="cc_steven",
                supplier_invoice_number="9001", qbo_doc_number="9001",
                qbo_purchase_id=qbo_purchase_id,
            )
            s.add(a)
            await s.commit()
            faux.crees["fournisseurs"].append(f.id)  # type: ignore[attr-defined]
            if cl:
                faux.crees["clients"].append(cl.id)  # type: ignore[attr-defined]
            faux.crees["achats"].append(a.id)  # type: ignore[attr-defined]
            return (int(cl.id) if cl else None), int(a.id)

    return run(_go())


def _reclasser(run, aid: int) -> Dict[str, Any]:
    async def _go() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            res = await classe.reclasser_classe_qb_achat(s, aid)
            await s.commit()
            return res

    return run(_go())


def _detail(payload: Dict[str, Any], i: int = 0) -> Dict[str, Any]:
    return payload["Line"][i]["AccountBasedExpenseLineDetail"]


# ── 1. Adresse du chantier → Construction, le reste intact ────────────


def test_classe_adresse_devient_construction(faux_qb, run):
    _pid, aid = _seed(run, faux_qb)
    faux_qb.purchases["5199"] = _purchase("5199", [_ligne()])

    res = _reclasser(run, aid)

    assert res == {"ok": True, "kind": "purchase", "qbo_id": "5199", "lignes": 1}
    assert len(faux_qb.ecritures) == 1
    kind, envoye = faux_qb.ecritures[0]
    assert kind == "purchase"
    d = _detail(envoye)
    assert d["ClassRef"] == {"value": CONSTRUCTION, "name": "Construction"}
    # Client : Projet, catégorie, montant, taxe, description : inchangés.
    assert d["CustomerRef"]["value"] == "J-179"
    assert d["AccountRef"]["name"] == "Matériaux pour le projet - Réno"
    assert d["TaxCodeRef"] == {"value": "5"}
    assert envoye["Line"][0]["Amount"] == 1492.18
    assert envoye["Line"][0]["Description"] == "Vinyle 4.5mm spc 312"
    assert envoye["Id"] == "5199" and envoye["SyncToken"] == "3"
    assert envoye["AccountRef"] == {"value": "8022"}
    assert "sparse" not in envoye


# ── 2. Déjà Construction → rien ───────────────────────────────────────


def test_deja_construction_aucune_ecriture(faux_qb, run):
    _pid, aid = _seed(run, faux_qb)
    faux_qb.purchases["5199"] = _purchase(
        "5199", [_ligne(classe_id=CONSTRUCTION, classe_nom="Construction")]
    )

    res = _reclasser(run, aid)

    assert res["unchanged"] is True
    assert faux_qb.ecritures == []


# ── 3. La ligne d'un autre client n'est pas touchée ───────────────────


def test_ligne_autre_client_intacte(faux_qb, run):
    _pid, aid = _seed(run, faux_qb)
    autre = _ligne(
        montant=200.0, client="C-IMMO", classe_id="12", classe_nom="Immobilier",
        description="Part immobilier",
    )
    autre["Id"] = "2"
    faux_qb.purchases["5199"] = _purchase("5199", [_ligne(), autre])

    res = _reclasser(run, aid)

    assert res["lignes"] == 1
    _kind, envoye = faux_qb.ecritures[0]
    assert _detail(envoye, 0)["ClassRef"]["value"] == CONSTRUCTION
    assert _detail(envoye, 1)["ClassRef"] == {"value": "12", "name": "Immobilier"}
    assert _detail(envoye, 1)["CustomerRef"]["value"] == "C-IMMO"


# ── 4. Sans client mais classée au chantier → sous-client posé ────────


def test_sans_client_prend_le_sous_client_du_projet(faux_qb, run):
    _pid, aid = _seed(run, faux_qb)
    ligne = _ligne(client=None)
    del ligne["AccountBasedExpenseLineDetail"]["BillableStatus"]
    faux_qb.purchases["5199"] = _purchase("5199", [ligne])

    res = _reclasser(run, aid)

    assert res["lignes"] == 1
    d = _detail(faux_qb.ecritures[0][1])
    assert d["ClassRef"]["value"] == CONSTRUCTION
    assert d["CustomerRef"] == {"value": "J-179"}
    assert d["BillableStatus"] == "NotBillable"


# ── 5. Une ligne que QB n'identifie pas → projet de l'achat ───────────


def test_une_ligne_inconnue_prend_le_projet_de_l_achat(faux_qb, run):
    _pid, aid = _seed(run, faux_qb)
    faux_qb.purchases["5199"] = _purchase(
        "5199", [_ligne(client="J-ANCIEN", classe_id="4", classe_nom="Divers")]
    )

    res = _reclasser(run, aid)

    assert res["lignes"] == 1
    d = _detail(faux_qb.ecritures[0][1])
    assert d["ClassRef"]["value"] == CONSTRUCTION
    # Le client déjà présent n'est pas remplacé.
    assert d["CustomerRef"]["value"] == "J-ANCIEN"


def test_deux_lignes_inconnues_restent_intactes(faux_qb, run):
    """À plusieurs lignes non identifiées, on ne devine pas."""
    _pid, aid = _seed(run, faux_qb)
    l1 = _ligne(client="X-1", classe_id="4", classe_nom="Divers")
    l2 = _ligne(client="X-2", classe_id="4", classe_nom="Divers")
    l2["Id"] = "2"
    faux_qb.purchases["5199"] = _purchase("5199", [l1, l2])

    res = _reclasser(run, aid)

    assert res["unchanged"] is True
    assert faux_qb.ecritures == []


# ── 6. Bill (facture fournisseur) ─────────────────────────────────────


def test_bill_se_corrige_aussi(faux_qb, run):
    _pid, aid = _seed(run, faux_qb, qbo_purchase_id=None, qbo_bill_id="5220")
    bill = _purchase("5220", [_ligne()])
    bill["VendorRef"] = bill.pop("EntityRef")
    faux_qb.bills["5220"] = bill

    res = _reclasser(run, aid)

    assert res["kind"] == "bill" and res["lignes"] == 1
    kind, envoye = faux_qb.ecritures[0]
    assert kind == "bill"
    assert _detail(envoye)["ClassRef"]["value"] == CONSTRUCTION
    assert envoye["VendorRef"] == {"value": "111", "type": "Vendor"}


# ── 7. QB injoignable ─────────────────────────────────────────────────


def test_qb_injoignable_ne_fait_rien(faux_qb, run):
    _pid, aid = _seed(run, faux_qb)
    faux_qb.ready = False

    assert _reclasser(run, aid) == {"skipped": "qbo_not_configured"}
    assert faux_qb.ecritures == []


def test_erreur_qb_renvoyee_sans_lever(faux_qb, run):
    _pid, aid = _seed(run, faux_qb, qbo_purchase_id="absente")

    res = _reclasser(run, aid)

    assert "error" in res
    assert faux_qb.ecritures == []


# ── 8. Filet : rattrapage puis achats récents ─────────────────────────


def test_filet_rattrape_une_fois_puis_les_recents(faux_qb, run):
    pid, aid = _seed(run, faux_qb)
    # Deuxième part du même reçu (fractionné) : même Purchase QB.
    _pid2, aid2 = _seed(run, faux_qb, qbo_job_id="J-180", adresse="158 Rue Maurice")

    async def _partager() -> None:
        async with TestSessionLocal() as s:
            a2 = await s.get(Achat, aid2)
            a2.qbo_purchase_id = "5199"
            await s.commit()

    run(_partager())
    faux_qb.purchases["5199"] = _purchase("5199", [_ligne()])

    res = run(classe.reclasser_achats_lies())

    assert res["rattrapage"] is True
    # (La base de test partagée peut contenir des achats d'autres tests
    # liés à des ids QB fictifs : ils comptent en erreurs, pas ici.)
    assert res["modifies"] == 1
    # Une seule lecture et une seule écriture pour la transaction partagée.
    assert faux_qb.lectures.count("purchase:5199") == 1
    assert len(faux_qb.ecritures) == 1

    # Deuxième passage : plus de rattrapage, seulement les achats récents
    # (les nôtres viennent d'être créés) ; déjà classés → rien à écrire.
    res2 = run(classe.reclasser_achats_lies())

    assert res2["rattrapage"] is False
    assert res2["modifies"] == 0 and res2["inchanges"] >= 1
    assert len(faux_qb.ecritures) == 1


# ── 9. Reçu « client seul » (sans projet) ─────────────────────────────


def test_recu_client_seul_prend_construction_client_garde(faux_qb, run):
    """La ligne du client mère prend « Construction » ; la ligne d'un
    autre client n'est pas touchée."""
    _cid, aid = _seed_client(run, faux_qb)
    mienne = _ligne(montant=250.0, client="C-55", classe_id=None, description="Fournitures")
    autre = _ligne(montant=80.0, client="C-AUTRE", classe_id="4", classe_nom="Divers")
    autre["Id"] = "2"
    faux_qb.purchases["5300"] = _purchase("5300", [mienne, autre])

    res = _reclasser(run, aid)

    assert res == {"ok": True, "kind": "purchase", "qbo_id": "5300", "lignes": 1}
    _kind, envoye = faux_qb.ecritures[0]
    assert _detail(envoye, 0)["ClassRef"] == {"value": CONSTRUCTION, "name": "Construction"}
    assert _detail(envoye, 0)["CustomerRef"]["value"] == "C-55"
    assert _detail(envoye, 1)["ClassRef"] == {"value": "4", "name": "Divers"}
    assert _detail(envoye, 1)["CustomerRef"]["value"] == "C-AUTRE"


def test_recu_client_seul_une_ligne_sans_client_recoit_le_client(faux_qb, run):
    _cid, aid = _seed_client(run, faux_qb)
    ligne = _ligne(montant=250.0, client=None, classe_id=None)
    del ligne["AccountBasedExpenseLineDetail"]["BillableStatus"]
    faux_qb.purchases["5300"] = _purchase("5300", [ligne])

    res = _reclasser(run, aid)

    assert res["lignes"] == 1
    d = _detail(faux_qb.ecritures[0][1])
    assert d["ClassRef"]["value"] == CONSTRUCTION
    assert d["CustomerRef"] == {"value": "C-55"}
    assert d["BillableStatus"] == "NotBillable"


def test_recu_client_seul_deux_lignes_etrangeres_intactes(faux_qb, run):
    """Deux lignes d'autres clients : on ne devine pas."""
    _cid, aid = _seed_client(run, faux_qb)
    l1 = _ligne(client="X-1", classe_id=None)
    l2 = _ligne(client="X-2", classe_id=None)
    l2["Id"] = "2"
    faux_qb.purchases["5300"] = _purchase("5300", [l1, l2])

    assert _reclasser(run, aid)["unchanged"] is True
    assert faux_qb.ecritures == []


def test_recu_shop_non_relu(faux_qb, run):
    """Ni client ni projet : pas relu (un reçu QB sans client peut venir
    d'un autre volet)."""
    _cid, aid = _seed_client(run, faux_qb, is_shop=True)
    faux_qb.purchases["5300"] = _purchase("5300", [_ligne(client=None, classe_id=None)])

    assert _reclasser(run, aid) == {"skipped": "sans_projet_ni_client"}
    assert faux_qb.lectures == [] and faux_qb.ecritures == []


def test_candidats_incluent_les_recus_client_seul(faux_qb, run):
    _cid, aid = _seed_client(run, faux_qb)
    _cid2, aid_shop = _seed_client(run, faux_qb, is_shop=True, qbo_purchase_id="5301")

    async def _go() -> list:
        async with TestSessionLocal() as s:
            return await classe.candidats(s, tous=True)

    liste = run(_go())
    assert (aid, "5300") in liste
    assert all(a != aid_shop for a, _ in liste)
