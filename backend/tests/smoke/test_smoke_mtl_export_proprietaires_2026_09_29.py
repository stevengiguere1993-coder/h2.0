"""Smoke — export des Rôles fonciers : adresse postale, statut, téléphone et
NEQ des propriétaires collectés (Phil 2026-09-28 : « le nom du propriétaire
ainsi que l'adresse » ; l'export ne sortait que les noms et les dates)."""
from __future__ import annotations

import csv
import io
import json

from app.models.montreal_property_unit import MontrealPropertyUnit

from tests.smoke.conftest import TestSessionLocal


def test_export_details_proprietaires(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            s.add(
                MontrealPropertyUnit(
                    matricule="EXP-OWN-1", civique_debut="2420",
                    nom_rue="boulevard Pie-IX  (MTL)", municipalite="Montréal",
                    region="mtl-island", nombre_logement=8, annee_construction=2095,
                    code_utilisation="1000",
                    owners_json=json.dumps([
                        {
                            "name": "PANICCIA, ISABELLA",
                            "statut": "Personne physique",
                            "postal_address": "12276 60E AVENUE, MONTREAL QUEBEC, H1C 1P3",
                            "inscription_date": "2008-06-02",
                            "phone": "514-555-0101",
                        },
                        {
                            "name": "GESTION TEST INC.",
                            "statut": "Personne morale",
                            "postal_address": "1 RUE TEST, MONTREAL",
                            "req_neq": "1170000000",
                        },
                    ]),
                )
            )
            await s.commit()

    run(_seed())
    r = client.get(
        "/api/v1/prospection/mtl-properties/export.csv?min_annee=2095&max_annee=2095",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    lignes = list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff")), delimiter=";"))
    assert len(lignes) == 1
    l = lignes[0]
    assert l["Propriétaires"] == "PANICCIA, ISABELLA | GESTION TEST INC."
    assert l["Adresse postale des propriétaires"] == (
        "12276 60E AVENUE, MONTREAL QUEBEC, H1C 1P3 | 1 RUE TEST, MONTREAL"
    )
    assert l["Statut des propriétaires"] == "Personne physique | Personne morale"
    assert l["Téléphone des propriétaires"] == "514-555-0101 | "
    assert l["NEQ des propriétaires"] == " | 1170000000"
