"""Reçus QuickBooks → Drive : pièces sans dépense classées dans leur mois,
puis rattachées à une dépense (Steven 2026-10-04 : « mettre les factures dans
le mois, même si le prix ou le fournisseur n'est pas là »).

Bout en bout sur la vraie mémoire (SQLite des smoke tests), avec un Drive et
un QuickBooks simulés en mémoire (aucun réseau) :
1. deux pièces sans dépense nommées « Invoice.pdf », déposées le même jour,
   sont copiées toutes les deux dans « 06 - Juin » (la 2e numérotée « (2) ») ;
   une pièce sans aucune date va dans « Non classé » même hors période ;
2. la 1re est rattachée à une dépense : son fichier est RENOMMÉ avec la
   dépense, pas recopié ;
3. « Annuler cet import » sur ce run rétablit le nom d'origine au lieu de
   mettre le reçu à la corbeille ;
4. la 2e est rattachée mais son fichier est à la corbeille : elle est recopiée ;
5. une autre entreprise qui partage la compagnie QuickBooks ne vole pas le
   fichier brut de la première.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import delete, select

from app.models.qbo_recu_drive import QboRecuDrive
from app.services import drive_api
from app.services import qbo_recus_drive as svc
from tests.smoke.conftest import TestSessionLocal

FOLDER = drive_api.FOLDER_MIME
REALM = "R-SMOKE-RECLASSE"


class FauxDrive:
    def __init__(self) -> None:
        self.fichiers: Dict[str, Dict[str, Any]] = {}
        self.n = 0
        self.corbeille: List[str] = []
        self.televerses: List[str] = []

    def ajouter(self, parent: Optional[str], name: str, mime: str = "application/pdf") -> str:
        self.n += 1
        fid = f"d{self.n}"
        self.fichiers[fid] = {"id": fid, "name": name, "mimeType": mime, "parents": [parent] if parent else [], "trashed": False}
        return fid

    def enfants(self, parent: str) -> List[Dict[str, Any]]:
        return [dict(f) for f in self.fichiers.values() if parent in f["parents"] and not f["trashed"]]

    def noms(self, parent: str) -> List[str]:
        return sorted(f["name"] for f in self.enfants(parent))

    def trouver(self, parent: str, name: str) -> Optional[str]:
        return next((f["id"] for f in self.enfants(parent) if f["name"] == name), None)

    async def list_folder_contents(self, user_id, db, folder_id, *, page_size=100, page_token=None, order_by="folder,name"):
        return {"files": self.enfants(folder_id), "next_page_token": None}

    async def get_file_metadata(self, user_id, db, file_id):
        from app.services.drive_exceptions import DriveNotFoundError

        if file_id not in self.fichiers:
            raise DriveNotFoundError("introuvable")
        return dict(self.fichiers[file_id])

    async def move_file(self, user_id, db, file_id, new_parent_folder_id, old_parent_folder_id=None):
        self.fichiers[file_id]["parents"] = [new_parent_folder_id]
        return dict(self.fichiers[file_id])

    async def rename_file(self, user_id, db, file_id, new_name):
        self.fichiers[file_id]["name"] = new_name
        return dict(self.fichiers[file_id])

    async def trash_file(self, user_id, db, file_id):
        self.fichiers[file_id]["trashed"] = True
        self.corbeille.append(file_id)

    async def create_folder(self, user_id, db, parent_id, name):
        return dict(self.fichiers[self.ajouter(parent_id, name, FOLDER)])

    async def upload_file(self, user_id, db, folder_id, name, content, mime=None):
        fid = self.ajouter(folder_id, name)
        self.televerses.append(name)
        return dict(self.fichiers[fid])


class FauxQBO:
    attachables: List[Dict[str, Any]] = []
    txns: Dict[str, Dict[str, Any]] = {}

    def __init__(self, scope: str = "construction") -> None:
        self.scope = scope
        self.realm_id = REALM

    async def _load_refresh_from_db(self) -> None:
        return None

    @property
    def ready(self) -> bool:
        return True

    async def query_all(self, q: str) -> List[Dict[str, Any]]:
        return [dict(a) for a in FauxQBO.attachables]

    async def get_purchase(self, v: str) -> Dict[str, Any]:
        return FauxQBO.txns[v]

    async def get_bill(self, v: str) -> Dict[str, Any]:
        return FauxQBO.txns[v]

    async def download_attachable(self, att_id: str) -> bytes:
        return b"%PDF-1.4 " + att_id.encode()


def _piece(att_id: str, nom: str, cree: Optional[str], refs: Optional[List[tuple]] = None) -> Dict[str, Any]:
    return {
        "Id": att_id,
        "FileName": nom,
        "ContentType": "application/pdf",
        "MetaData": {"CreateTime": cree} if cree else {},
        "AttachableRef": [{"EntityRef": {"type": t, "value": v}} for t, v in (refs or [])],
    }


@pytest.fixture
def env(monkeypatch, run, db_setup):
    faux = FauxDrive()
    for nom in ("list_folder_contents", "get_file_metadata", "move_file", "rename_file", "trash_file", "create_folder", "upload_file"):
        monkeypatch.setattr(drive_api, nom, getattr(faux, nom))
    import app.integrations.quickbooks as qb
    import app.services.drive_auto_upload_dispatcher as disp

    monkeypatch.setattr(qb, "QuickBooksClient", FauxQBO)

    async def _owner(db, user_id=None):
        return 1

    monkeypatch.setattr(disp, "resolve_drive_owner_user_id", _owner)
    FauxQBO.attachables = []
    FauxQBO.txns = {}
    yield faux

    async def _nettoyer():
        async with TestSessionLocal() as s:
            await s.execute(delete(QboRecuDrive).where(QboRecuDrive.realm_id == REALM))
            await s.commit()

    run(_nettoyer())
    svc.DERNIER_RUN.update(run_id=None, en_cours=False, arret_demande=False)


def _entreprise(eid: int, racine: str) -> Dict[str, Any]:
    return {
        "entreprise_id": eid, "name": f"Inc {eid}", "qbo_scope": "construction", "qbo_realm_id": REALM,
        "drive_folder_id": racine, "qbo_company_name": None,
    }


def _passe(run, faux, e, run_id, depuis=date(2026, 1, 1), jusqua=date(2026, 12, 31)):
    async def _go():
        svc.DERNIER_RUN["run_id"] = run_id
        rapport = svc._nouveau_rapport_entreprise(e)
        async with TestSessionLocal() as s:
            await svc._traiter_entreprise(
                s, e, svc._Drive(1, s, simulation=False), depuis=depuis, jusqua=jusqua,
                simulation=False, declencheur="rattrapage", rapport=rapport,
            )
        return rapport

    return run(_go())


def _lignes(run) -> List[QboRecuDrive]:
    async def _go():
        async with TestSessionLocal() as s:
            return list((await s.execute(select(QboRecuDrive).where(QboRecuDrive.realm_id == REALM))).scalars().all())

    return run(_go())


def test_bruts_mois_rattachement_annulation(env, run) -> None:
    faux = env
    racine = faux.ajouter(None, "Inc 9001", FOLDER)
    factures = faux.ajouter(racine, "Factures", FOLDER)
    an = faux.ajouter(factures, "2026", FOLDER)
    e = _entreprise(9001, racine)

    # 1. Deux « Invoice.pdf » sans dépense, même jour ; une pièce sans aucune date.
    FauxQBO.attachables = [
        _piece("A1", "Invoice.pdf", "2026-06-01T09:00:00-04:00"),
        _piece("A2", "Invoice.pdf", "2026-06-01T15:00:00-04:00"),
        _piece("A3", "scan.pdf", None),
    ]
    r1 = _passe(run, faux, e, "run1", depuis=date(2026, 6, 1), jusqua=date(2026, 6, 30))
    assert r1["erreurs"] == 0, r1["messages"]
    assert r1["copies"] == 3 and r1["sans_depense"] == 2 and r1["non_classes"] == 1 and r1["hors_periode"] == 0
    juin = faux.trouver(an, "06 - Juin")
    assert faux.noms(juin) == ["2026-06-01 Invoice (2).pdf", "2026-06-01 Invoice.pdf"]
    nc = faux.trouver(an, "Non classé")
    assert faux.noms(nc) == ["scan.pdf"]
    brut_a1 = next(l for l in _lignes(run) if l.attachable_id == "A1")
    assert brut_a1.txn_type == "" and brut_a1.date_recu == date(2026, 6, 1)
    fichier_a1 = brut_a1.drive_file_id

    # 2. A1 rattachée à une dépense : renommée, pas recopiée.
    FauxQBO.txns["55"] = {"TxnDate": "2026-06-03", "EntityRef": {"type": "Vendor", "name": "Rona"}, "TotalAmt": 123.45}
    FauxQBO.attachables[0] = _piece("A1", "Invoice.pdf", "2026-06-01T09:00:00-04:00", [("Purchase", "55")])
    televerses_avant = len(faux.televerses)
    r2 = _passe(run, faux, e, "run2")
    assert r2["erreurs"] == 0, r2["messages"]
    assert r2["rattaches"] == 1 and r2["copies"] == 0
    assert len(faux.televerses) == televerses_avant
    assert faux.fichiers[fichier_a1]["name"] == "2026-06-03 Rona 123,45$.pdf"
    lignes = {(l.attachable_id, l.txn_type): l for l in _lignes(run)}
    assert lignes[("A1", "")].statut == "rattache"
    assert lignes[("A1", "Purchase")].drive_file_id == fichier_a1 and lignes[("A1", "Purchase")].run_id == "run2"

    # 3. Annuler run2 : le reçu reprend son nom d'origine, rien à la corbeille.
    async def _annuler():
        async with TestSessionLocal() as s:
            return await svc.annuler_run(s, "run2", user_id=1)

    res = run(_annuler())
    assert res["ok"] and res["fichiers_restaures"] == 1 and res["fichiers_corbeille"] == 0
    assert faux.fichiers[fichier_a1]["name"] == "2026-06-01 Invoice.pdf" and not faux.fichiers[fichier_a1]["trashed"]
    lignes = {(l.attachable_id, l.txn_type): l for l in _lignes(run)}
    assert lignes[("A1", "")].statut == "copie" and ("A1", "Purchase") not in lignes

    # 4. A2 rattachée, mais son fichier brut est à la corbeille : recopiée.
    brut_a2 = lignes[("A2", "")]
    faux.fichiers[brut_a2.drive_file_id]["trashed"] = True
    FauxQBO.txns["56"] = {"TxnDate": "2026-06-04", "EntityRef": {"type": "Vendor", "name": "BMR"}, "TotalAmt": 10}
    FauxQBO.attachables[1] = _piece("A2", "Invoice.pdf", "2026-06-01T15:00:00-04:00", [("Purchase", "56")])
    FauxQBO.attachables[0] = _piece("A1", "Invoice.pdf", "2026-06-01T09:00:00-04:00")
    r4 = _passe(run, faux, e, "run4")
    assert r4["erreurs"] == 0, r4["messages"]
    assert r4["copies"] == 1 and r4["rattaches"] == 0
    assert "2026-06-04 BMR 10,00$.pdf" in faux.noms(juin)

    # 5. Une autre entreprise sur la même compagnie QuickBooks : A1 rattachée
    #    pour elle → copie dans SON Drive, le fichier de 9001 ne bouge pas.
    racine2 = faux.ajouter(None, "Inc 9002", FOLDER)
    e2 = _entreprise(9002, racine2)
    FauxQBO.attachables = [_piece("A1", "Invoice.pdf", "2026-06-01T09:00:00-04:00", [("Purchase", "55")])]
    r5 = _passe(run, faux, e2, "run5")
    assert r5["erreurs"] == 0, r5["messages"]
    assert r5["copies"] == 1 and r5["rattaches"] == 0
    assert faux.fichiers[fichier_a1]["parents"] == [juin]
    assert faux.fichiers[fichier_a1]["name"] == "2026-06-01 Invoice.pdf"


def test_nuit_reclasse_aussi_une_entreprise_sans_quickbooks(env, run, monkeypatch) -> None:
    """Une entreprise avec un Drive mais sans connexion QuickBooks n'a pas de
    copie, mais ses « À classer » sont rangés dans leurs mois chaque nuit."""
    faux = env
    racine = faux.ajouter(None, "Inc 9003", FOLDER)
    an = faux.ajouter(faux.ajouter(racine, "Factures", FOLDER), "2026", FOLDER)
    ac = faux.ajouter(faux.ajouter(an, "Juin", FOLDER), "À classer", FOLDER)
    fid = faux.ajouter(ac, "2026-06-15 ############6000-juin-2026.pdf")
    etat = {
        **_entreprise(9003, racine), "qbo_connectee": False, "prete": False,
    }

    async def _etats(db):
        return [etat]

    monkeypatch.setattr(svc, "entreprises_etat", _etats)

    async def _go():
        async with TestSessionLocal() as s:
            return await svc.executer(s, simulation=False, declencheur="cron", pieces_depuis_jours=2)

    rapport = run(_go())
    assert rapport["non_pretes"] and rapport["non_pretes"][0]["manque"] == ["connexion QuickBooks"]
    assert rapport["totaux"]["reclasses"] == 1
    juin = faux.trouver(an, "06 - Juin")
    assert juin and faux.fichiers[fid]["parents"] == [juin]
    assert ac in faux.corbeille
