"""Reçus QuickBooks → Drive : reclassement des « À classer » dans les mois
(Steven 2026-10-04 : « enlever les sections À classer et mettre les
factures dans le mois, même si le prix ou le fournisseur n'est pas là »).

Drive simulé en mémoire (aucun réseau, aucune base) : on vérifie que
- un fichier dont le nom porte une date va dans le dossier de ce mois,
  sous l'année déjà ouverte (ou via Factures / <autre année>) ;
- un fichier sans date va dans « Non classé » (sous l'année) et y reste ;
- le « À classer » vidé part à la corbeille, « Non classé » non vide reste ;
- la simulation ne touche à rien mais annonce la même chose ;
- une pièce jointe sans dépense liée est classée dans son mois de dépôt.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services import drive_api  # noqa: E402
from app.services import qbo_recus_drive as svc  # noqa: E402

FOLDER = drive_api.FOLDER_MIME


class FauxDrive:
    """Arborescence Drive en mémoire + les cinq appels que le service utilise."""

    def __init__(self) -> None:
        self.fichiers: Dict[str, Dict[str, Any]] = {}
        self.n = 0
        self.corbeille: List[str] = []
        self.renommes: List[tuple] = []
        self.deplacements: List[tuple] = []

    def ajouter(self, parent: Optional[str], name: str, mime: str = "application/pdf") -> str:
        self.n += 1
        fid = f"f{self.n}"
        self.fichiers[fid] = {
            "id": fid, "name": name, "mimeType": mime,
            "parents": [parent] if parent else [], "trashed": False,
        }
        return fid

    def dossier(self, parent: Optional[str], name: str) -> str:
        return self.ajouter(parent, name, FOLDER)

    def enfants(self, parent: str) -> List[Dict[str, Any]]:
        return [dict(f) for f in self.fichiers.values() if parent in f["parents"] and not f["trashed"]]

    def chemin(self, fid: str) -> str:
        f = self.fichiers[fid]
        noms = [f["name"]]
        while f["parents"]:
            f = self.fichiers[f["parents"][0]]
            noms.append(f["name"])
        return " / ".join(reversed(noms))

    def trouver(self, parent: str, name: str) -> Optional[str]:
        return next((f["id"] for f in self.enfants(parent) if f["name"] == name), None)

    # ── API Drive simulée ────────────────────────────────────────────
    async def list_folder_contents(self, user_id, db, folder_id, *, page_size=100, page_token=None, order_by="folder,name"):
        return {"files": self.enfants(folder_id), "next_page_token": None}

    async def move_file(self, user_id, db, file_id, new_parent_folder_id, old_parent_folder_id=None):
        f = self.fichiers[file_id]
        self.deplacements.append((file_id, list(f["parents"]), new_parent_folder_id))
        f["parents"] = [new_parent_folder_id]
        return dict(f)

    async def trash_file(self, user_id, db, file_id):
        self.fichiers[file_id]["trashed"] = True
        self.corbeille.append(file_id)

    async def create_folder(self, user_id, db, parent_id, name):
        return dict(self.fichiers[self.dossier(parent_id, name)])

    async def rename_file(self, user_id, db, file_id, new_name):
        self.fichiers[file_id]["name"] = new_name
        self.renommes.append((file_id, new_name))
        return dict(self.fichiers[file_id])


@pytest.fixture
def faux(monkeypatch) -> FauxDrive:
    d = FauxDrive()
    for nom in ("list_folder_contents", "move_file", "trash_file", "create_folder", "rename_file"):
        monkeypatch.setattr(drive_api, nom, getattr(d, nom))
    return d


def _arbre(faux: FauxDrive) -> Dict[str, str]:
    """Drive d'une inc tel que laissé par l'ancien classement."""
    racine = faux.dossier(None, "1 - MGV Investissements inc")
    factures = faux.dossier(racine, "2 - Factures")
    an = faux.dossier(factures, "2026")
    juin = faux.dossier(an, "Juin")  # sans chiffre devant → à renommer
    ac = faux.dossier(juin, "À classer")
    faux.ajouter(ac, "2026-06-01 facture-A7.pdf")
    faux.ajouter(ac, "2026-06-03 Invoice_52_2026-06-16.pdf")
    faux.ajouter(ac, "2026-06-12 IMG_20260611_062821.jpg", "image/jpeg")
    faux.ajouter(ac, "2025-12-30 vieux.pdf")  # autre année → Factures / 2025 / 12 - Décembre
    faux.ajouter(ac, "sans-date.pdf")  # → 2026 / Non classé
    nc = faux.dossier(an, "Non classé")
    faux.ajouter(nc, "2026-05-02 x.pdf")  # → 05 - Mai (créé)
    faux.ajouter(nc, "nodate.pdf")  # reste
    return {"racine": racine, "factures": factures, "an": an, "juin": juin, "ac": ac, "nc": nc}


def _rapport() -> Dict[str, Any]:
    return svc._nouveau_rapport_entreprise({"entreprise_id": 1, "name": "MGV", "qbo_company_name": None})


def test_reclassement_reel(faux: FauxDrive) -> None:
    ids = _arbre(faux)
    drive = svc._Drive(1, None, simulation=False)
    rapport = _rapport()
    deplaces = asyncio.run(drive.reclasser(ids["racine"], "MGV", rapport))

    assert rapport["erreurs"] == 0, rapport["messages"]
    assert rapport["reclasses"] == 5
    assert rapport["non_classes_deplaces"] == 1
    assert len(rapport["deplacements"]) == 6
    assert len(deplaces) == 6 and all("Reclassé le" in d[2] for d in deplaces)

    # Le mois sans chiffre devant est numéroté ; les fichiers datés de juin y sont.
    assert faux.fichiers[ids["juin"]]["name"] == "06 - Juin"
    noms_juin = sorted(f["name"] for f in faux.enfants(ids["juin"]))
    assert noms_juin == [
        "2026-06-01 facture-A7.pdf",
        "2026-06-03 Invoice_52_2026-06-16.pdf",
        "2026-06-12 IMG_20260611_062821.jpg",
    ]
    # « À classer » vidé → corbeille ; aucun fichier n'est à la corbeille.
    assert ids["ac"] in faux.corbeille
    assert all(faux.fichiers[c]["mimeType"] == FOLDER for c in faux.corbeille)
    # Autre année : Factures / 2025 / 12 - Décembre créé.
    an2025 = faux.trouver(ids["factures"], "2025")
    assert an2025 and faux.trouver(an2025, "12 - Décembre")
    assert faux.trouver(faux.trouver(an2025, "12 - Décembre"), "2025-12-30 vieux.pdf")
    # Sans date : « Non classé » existant réutilisé ; « nodate.pdf » y reste ; non vidé → pas à la corbeille.
    noms_nc = sorted(f["name"] for f in faux.enfants(ids["nc"]))
    assert noms_nc == ["nodate.pdf", "sans-date.pdf"]
    assert ids["nc"] not in faux.corbeille
    # Mai créé sous 2026 pour le fichier daté de « Non classé ».
    mai = faux.trouver(ids["an"], "05 - Mai")
    assert mai and faux.trouver(mai, "2026-05-02 x.pdf")
    assert any(c.endswith("/ 05 - Mai") for c in drive.dossiers_crees)
    assert drive.dossiers_renommes and "« Juin » → « 06 - Juin »" in drive.dossiers_renommes[0]
    # La mémoire reçoit le nouveau dossier de chaque fichier déplacé.
    cibles = {fid: dossier for fid, dossier, _ in deplaces}
    for fid, dossier in cibles.items():
        assert faux.fichiers[fid]["parents"] == [dossier]
    # Le rapport dit d'où vers où.
    de_vers = {(d["fichier"], d["vers"]) for d in rapport["deplacements"]}
    assert ("2026-06-01 facture-A7.pdf", "MGV / 2 - Factures / 2026 / 06 - Juin") in de_vers
    assert ("sans-date.pdf", "MGV / 2 - Factures / 2026 / Non classé") in de_vers
    assert ("2025-12-30 vieux.pdf", "MGV / 2 - Factures / 2025 / 12 - Décembre") in de_vers


def test_reclassement_simulation_ne_touche_a_rien(faux: FauxDrive) -> None:
    ids = _arbre(faux)
    avant = {k: dict(v) for k, v in faux.fichiers.items()}
    drive = svc._Drive(1, None, simulation=True)
    rapport = _rapport()
    deplaces = asyncio.run(drive.reclasser(ids["racine"], "MGV", rapport))

    assert deplaces == []
    assert faux.fichiers == avant
    assert faux.corbeille == [] and faux.renommes == [] and faux.deplacements == []
    assert rapport["reclasses"] == 5 and rapport["non_classes_deplaces"] == 1
    assert len(rapport["deplacements"]) == 6
    assert any("à mettre à la corbeille" in m for m in rapport["infos"])
    assert any(c.endswith("/ 05 - Mai") for c in drive.dossiers_a_creer)
    assert any(c.endswith("/ 2025") for c in drive.dossiers_a_creer)
    assert drive.dossiers_a_renommer and "« Juin »" in drive.dossiers_a_renommer[0]


def test_reclassement_deuxieme_passage_sans_effet(faux: FauxDrive) -> None:
    ids = _arbre(faux)
    asyncio.run(svc._Drive(1, None, simulation=False).reclasser(ids["racine"], "MGV", _rapport()))
    etat = {k: dict(v) for k, v in faux.fichiers.items()}
    rapport = _rapport()
    deplaces = asyncio.run(svc._Drive(1, None, simulation=False).reclasser(ids["racine"], "MGV", rapport))
    assert deplaces == [] and rapport["reclasses"] == 0 and rapport["non_classes_deplaces"] == 0
    assert faux.fichiers == etat


def test_non_classe_vide_part_a_la_corbeille(faux: FauxDrive) -> None:
    racine = faux.dossier(None, "Inc")
    factures = faux.dossier(racine, "Factures")
    an = faux.dossier(factures, "2026")
    nc = faux.dossier(an, "Non classé")
    faux.ajouter(nc, "2026-07-04 reçu.pdf")
    rapport = _rapport()
    asyncio.run(svc._Drive(1, None, simulation=False).reclasser(racine, "Inc", rapport))
    assert rapport["reclasses"] == 1
    juillet = faux.trouver(an, "07 - Juillet")
    assert juillet and faux.trouver(juillet, "2026-07-04 reçu.pdf")
    assert nc in faux.corbeille


def test_sans_factures_ni_annee_rien_ne_bouge(faux: FauxDrive) -> None:
    racine = faux.dossier(None, "Inc")
    faux.ajouter(racine, "2026-06-01 x.pdf")
    rapport = _rapport()
    deplaces = asyncio.run(svc._Drive(1, None, simulation=False).reclasser(racine, "Inc", rapport))
    assert deplaces == [] and faux.deplacements == [] and faux.n == 2


def test_rattacher_renomme_sans_recopier(faux: FauxDrive) -> None:
    racine = faux.dossier(None, "Inc")
    juin = faux.dossier(racine, "06 - Juin")
    juillet = faux.dossier(racine, "07 - Juillet")
    brut = faux.ajouter(juin, "2026-06-01 facture-A7.pdf")
    drive = svc._Drive(1, None, simulation=False)
    # Déjà dans le bon mois : renommé, pas déplacé.
    asyncio.run(drive.rattacher(brut, juin, juin, "2026-06-01 Rona 123,45$.pdf"))
    assert faux.fichiers[brut]["name"] == "2026-06-01 Rona 123,45$.pdf"
    assert faux.deplacements == []
    assert [f["name"] for f in asyncio.run(drive.contenu(juin))] == ["2026-06-01 Rona 123,45$.pdf"]
    # La dépense est datée d'un autre mois : renommé ET déplacé.
    asyncio.run(drive.rattacher(brut, juin, juillet, "2026-07-02 Rona 123,45$.pdf"))
    assert faux.fichiers[brut]["parents"] == [juillet]
    assert asyncio.run(drive.contenu(juin)) == []
    assert [f["name"] for f in asyncio.run(drive.contenu(juillet))] == ["2026-07-02 Rona 123,45$.pdf"]


@pytest.mark.parametrize(
    "nom, attendu",
    [
        ("2026-06-01 facture-A7.pdf", date(2026, 6, 1)),
        ("2026-06-03 Invoice_52_2026-06-16.pdf", date(2026, 6, 3)),
        ("2026-06-15 ############6000-juin-2026.pdf", date(2026, 6, 15)),
        ("IMG_20260611_062821.jpg", date(2026, 6, 11)),
        ("Invoice_52_2026-06-16.pdf", date(2026, 6, 16)),
        ("2026-13-45 bidon.pdf", None),
        ("Facture 12120.pdf", None),
        ("facture-A20.pdf", None),
        ("tel 5141234567.pdf", None),
        ("1999-01-01 trop vieux.pdf", None),
        ("", None),
        (None, None),
    ],
)
def test_date_dans_nom(nom, attendu) -> None:
    assert svc.date_dans_nom(nom) == attendu


def test_cible_sans_depense_va_dans_son_mois() -> None:
    att = {"FileName": "facture-A7.pdf", "MetaData": {"CreateTime": "2026-06-01T10:12:00-07:00"}}
    c = svc.cible_sans_depense(att, ".pdf")
    assert c["date"] == date(2026, 6, 1) and c["date_recu"] == date(2026, 6, 1)
    assert c["nom"] == "2026-06-01 facture-A7.pdf"
    assert c["non_classe"] is False and c["txn_type"] == "" and c["fournisseur"] == "ND"


def test_cible_sans_depense_sans_aucune_date() -> None:
    att = {"FileName": "facture-A7.pdf", "MetaData": {}}
    c = svc.cible_sans_depense(att, ".pdf", aujourdhui=date(2026, 10, 4))
    assert c["non_classe"] is True and c["date_recu"] is None
    assert c["date"] == date(2026, 10, 4)
    assert c["nom"] == "facture-A7.pdf"
