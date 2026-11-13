"""Documents Drive d'un immeuble : repérage du dossier et classement.

Sans réseau ni base : on vérifie le score d'un nom de dossier contre
l'adresse (vrais noms du Drive d'Horizon), le choix « certain », le
classement des documents par nom puis par dossier, et le parcours par
niveaux contre un Drive simulé.
"""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services import drive_api  # noqa: E402
from app.services import immeuble_drive as svc  # noqa: E402
from app.services.immeuble_drive import DossierCandidat  # noqa: E402

FOLDER = drive_api.FOLDER_MIME


def test_score_vrais_noms():
    assert svc.score_dossier("1 - 1660 Saint-Clément", ["1660 Saint-Clément"]) > 0
    assert svc.score_dossier("1-5 rue Elgin Granby", ["1 - 5 Elgin"], "Granby") > 0
    assert svc.score_dossier("44 Kennedy Sud Sherbrooke", ["44, Rue Kennedy Sud"]) > 0
    # Le numéro seul ne suffit pas, la rue seule non plus.
    assert svc.score_dossier("1 - Taxes", ["1 - 5 Elgin"]) == 0
    assert svc.score_dossier("409-417 Boivin Granby", ["1 - 5 Elgin"], "Granby") == 0
    assert svc.score_dossier("45 Kennedy", ["44, Rue Kennedy Sud"]) == 0
    # « Rue », « Saint » ne sont pas distinctifs.
    assert svc.score_dossier("1660 rue Saint-Denis", ["1660 Saint-Clément"]) == 0


def test_deux_adresses_et_numeros_voisins():
    assert svc.score_dossier("976 Place Sapinière", ["957-978, Place Sapinière"]) == 0
    assert svc.score_dossier("957-978 Place Sapinière Valcourt", ["976, Place Sapinière"]) == 0
    assert svc.score_dossier(
        "710 Legendre", ["9085, Avenue Millen", "710, Rue Legendre Est"]
    ) > 0


def test_choisir_certain_et_proprietaire():
    candidats = [
        DossierCandidat(id="a", nom="1-5 rue Elgin Granby", entreprise_id=2),
        DossierCandidat(id="b", nom="44 Kennedy Sud Sherbrooke", entreprise_id=2),
        DossierCandidat(id="c", nom="1 - Immeuble", entreprise_id=21),
    ]
    classes, certain = svc.choisir(candidats, ["1 - 5 Elgin"], "Granby", {2})
    assert certain is not None and certain.id == "a"
    assert certain.sous_proprietaire is True
    assert [c.id for c in classes] == ["a"]
    # Dossier déjà relié à un autre immeuble : jamais proposé d'office.
    _, certain = svc.choisir(candidats, ["1 - 5 Elgin"], "Granby", {2}, {"a"})
    assert certain is None


def test_choisir_egalite_pas_certain():
    candidats = [
        DossierCandidat(id="x", nom="1660 Saint-Clément"),
        DossierCandidat(id="y", nom="1660 Saint-Clément (copie)"),
    ]
    classes, certain = svc.choisir(candidats, ["1660 Saint-Clément"], None, set())
    assert len(classes) == 2 and certain is None
    # Sous la compagnie propriétaire, il l'emporte.
    candidats[0].entreprise_id = 21
    _, certain = svc.choisir(candidats, ["1660 Saint-Clément"], None, {21})
    assert certain is not None and certain.id == "x"


def test_classer_documents():
    c = svc.classer_document
    assert c("Certificat de localisation - Rapport (1) 9085 Millen.pdf", "6 - Achat") == "certificat_localisation"
    assert c("Compte de taxes 2025.pdf", "1 - Taxes") == "taxes_municipales"
    assert c("2025.pdf", "1 - Taxes/Municipales") == "taxes_municipales"
    assert c("Taxes 2025.pdf", "1 - Taxes/Taxes scolaires") == "taxes_scolaires"
    assert c("CSS des Sommets 2025-2026.pdf", "1 - Taxes") == "taxes_scolaires"
    assert c("Police 2025.pdf", "2 - Assurances") == "assurance"
    assert c("Renouvellement.pdf", "2 - Assurances/2025") == "assurance"
    assert c("Rapport d_evaluation 9085 Millen.pdf", "") == "evaluation"
    assert c("Copie-conforme-authentique-Acte-de-pret.pdf", "") == "financement"
    assert c("Projet acte de vente.pdf", "") == "achat"
    assert c("Bail 3100A.pdf", "4 - Gestion locative") == "gestion_locative"
    assert c("Facture mars.pdf", "5 - Opérations (Hydro, internet, etc.)") == "operations"
    assert c("photo.jpg", "Divers") == "autres"


def test_annee_et_rangement():
    assert svc.annee_document("Taxes 2024-2025.pdf") == 2025
    assert svc.annee_document("facture.pdf", "1 - Taxes/2023") == 2023
    assert svc.annee_document("29128171.pdf") is None
    cats = svc.ranger(
        [
            {"id": "1", "name": "Taxes 2023.pdf", "_chemin": "1 - Taxes"},
            {"id": "2", "name": "Taxes 2025.pdf", "_chemin": "1 - Taxes"},
            {"id": "3", "name": "Bail.pdf", "_chemin": ""},
        ]
    )
    cles = [c["cle"] for c in cats]
    # Les quatre documents clés toujours présents, en tête ; vides cachés sinon.
    assert cles[:4] == [
        "certificat_localisation",
        "taxes_municipales",
        "taxes_scolaires",
        "assurance",
    ]
    assert "evaluation" not in cles and "gestion_locative" in cles
    taxes = next(c for c in cats if c["cle"] == "taxes_municipales")
    assert [d["id"] for d in taxes["documents"]] == ["2", "1"]


class _Requete:
    def __init__(self, res):
        self.res = res

    def execute(self):
        return self.res


class _DriveFaux:
    """files().list() sur un arbre en mémoire ; comprend « 'x' in parents »."""

    def __init__(self, arbre: dict[str, list[dict[str, Any]]]):
        self.arbre = arbre
        self.appels = 0

    def files(self):
        return self

    def list(self, q: str, **_kw):
        import re

        self.appels += 1
        parents = re.findall(r"'([^']+)' in parents", q)
        out = []
        for p in parents:
            for f in self.arbre.get(p, []):
                if "mimeType = '" + FOLDER + "'" in q and f.get("mimeType") != FOLDER:
                    continue
                out.append({**f, "parents": [p]})
        return _Requete({"files": out})


def test_parcourir_par_niveaux(monkeypatch):
    arbre = {
        "racine": [
            {"id": "t", "name": "1 - Taxes", "mimeType": FOLDER},
            {"id": "a", "name": "2 - Assurances", "mimeType": FOLDER},
            {"id": "f0", "name": "Certificat de localisation.pdf", "mimeType": "application/pdf"},
        ],
        "t": [
            {"id": "t25", "name": "2025", "mimeType": FOLDER},
        ],
        "t25": [{"id": "f1", "name": "Compte.pdf", "mimeType": "application/pdf"}],
        "a": [{"id": "f2", "name": "Police.pdf", "mimeType": "application/pdf"}],
    }
    faux = _DriveFaux(arbre)

    async def _service(db, user_id):
        return faux

    monkeypatch.setattr(svc, "_service", _service)
    parcours = asyncio.run(svc.parcourir(SimpleNamespace(), 1, "racine"))
    par_id = {f["id"]: f["_chemin"] for f in parcours.fichiers}
    assert par_id == {"f0": "", "f1": "1 - Taxes/2025", "f2": "2 - Assurances"}
    # Une requête par niveau (racine, puis Taxes + Assurances, puis 2025, puis vide).
    assert faux.appels <= 4
    cats = {c["cle"]: c for c in svc.ranger(parcours.fichiers)}
    assert cats["taxes_municipales"]["documents"][0]["annee"] == 2025
    assert cats["assurance"]["nombre"] == 1
    assert cats["certificat_localisation"]["nombre"] == 1
