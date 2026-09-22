"""Smoke — export CSV des rôles fonciers (page Immeubles MTL).

Demande Phil 2026-09-22 : « J'ai 938 915 propriétés dans Kratos, donne-moi
ce fichier ». Le CSV reprend les mêmes filtres que la page, en flux,
avec les propriétaires déjà identifiés.
"""
from __future__ import annotations

import csv
import io
import json

from app.models.montreal_property_unit import MontrealPropertyUnit

from .conftest import TestSessionLocal


def test_export_csv_roles_fonciers(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            s.add_all([
                MontrealPropertyUnit(
                    matricule="EXP-0001", civique_debut="100",
                    nom_rue="rue Export", municipalite="Montréal",
                    arrondissement="Ville-Marie", nombre_logement=12,
                    annee_construction=1965, code_utilisation="1000",
                    libelle_utilisation="Logement", superficie_terrain=450.5,
                    owners_json=json.dumps([
                        {"name": "GESTION EXPORT INC.", "inscription_date": "2019-04-01"},
                        {"name": "Jean Tremblay", "inscription_date": ""},
                    ]),
                ),
                MontrealPropertyUnit(
                    matricule="EXP-0002", civique_debut="200",
                    nom_rue="rue Export", municipalite="Montréal",
                    nombre_logement=3, code_utilisation="1000",
                ),
                MontrealPropertyUnit(
                    matricule="EXP-0003", civique_debut="5",
                    nom_rue="rue Ailleurs", municipalite="Laval",
                    nombre_logement=40, code_utilisation="1000",
                ),
            ])
            await s.commit()

    run(_seed())
    r = client.get(
        "/api/v1/prospection/mtl-properties/export.csv?min_logements=10&nom_rue_contains=Export",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "roles-fonciers" in r.headers.get("content-disposition", "")
    texte = r.content.decode("utf-8")
    assert texte.startswith("﻿"), "BOM pour Excel"
    lignes = list(csv.reader(io.StringIO(texte.lstrip("﻿")), delimiter=";"))
    entete, corps = lignes[0], [l for l in lignes[1:] if l]
    assert entete[0] == "Matricule" and "Propriétaires" in entete
    matricules = [l[0] for l in corps]
    assert matricules == ["EXP-0001"], "12 logements ET rue Export"
    ligne = dict(zip(entete, corps[0]))
    assert ligne["Adresse"] == "100 rue Export"
    assert ligne["Nombre de logements"] == "12"
    assert ligne["Propriétaires"] == "GESTION EXPORT INC. | Jean Tremblay"
    assert ligne["Inscription des propriétaires"] == "2019-04-01 | "
    assert ligne["Déjà un lead"] == "non"

    # Sans filtre : tout (au moins nos 3 lignes), triées par matricule.
    r2 = client.get(
        "/api/v1/prospection/mtl-properties/export.csv", headers=auth_headers,
    )
    assert r2.status_code == 200
    tout = [
        l[0] for l in csv.reader(
            io.StringIO(r2.content.decode("utf-8").lstrip("﻿")), delimiter=";",
        )
    ][1:]
    exp = [m for m in tout if m.startswith("EXP-")]
    assert exp == ["EXP-0001", "EXP-0002", "EXP-0003"]
    # Sans session : refusé.
    assert client.get("/api/v1/prospection/mtl-properties/export.csv").status_code in (401, 403)
