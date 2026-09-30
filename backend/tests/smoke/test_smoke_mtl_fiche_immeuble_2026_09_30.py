"""Smoke — Rôles fonciers (Phil 2026-09-30) : filtre « propriétaire
collecté » et données de la fiche d'immeuble (adresse postale du
propriétaire, statut, téléphone, NEQ, arrondissement, date de
vérification) renvoyées par la liste."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.models.montreal_property_unit import MontrealPropertyUnit

from tests.smoke.conftest import TestSessionLocal


def test_filtre_collecte_et_fiche(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            base = dict(region="mtl-island", municipalite="Montréal",
                        annee_construction=2092, nombre_logement=13,
                        code_utilisation="1000", libelle_utilisation="Logement")
            s.add_all([
                MontrealPropertyUnit(
                    matricule="FIC-1", civique_debut="2420", civique_fin="2420",
                    nom_rue="rue de la Fiche-Test  (MTL)",
                    arrondissement="Mercier–Hochelaga-Maisonneuve",
                    categorie_uef="Régulier",
                    owners_fetched_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
                    owners_json=json.dumps([
                        {"name": "PANICCIA, ISABELLA", "statut": "Personne physique",
                         "postal_address": "12276 60E AVENUE, MONTREAL QUEBEC, H1C 1P3",
                         "inscription_date": "2019-05-31", "phone": "514-555-0101"},
                        {"name": "GESTION TEST INC.", "req_neq": "1170000000"},
                    ]),
                    **base,
                ),
                MontrealPropertyUnit(matricule="FIC-2", owners_json="[]", **base),
                MontrealPropertyUnit(matricule="FIC-3", **base),
            ])
            await s.commit()

    run(_seed())
    q = "/api/v1/prospection/mtl-properties?min_annee=2092&max_annee=2092"

    def _mats(extra: str = "") -> list:
        r = client.get(q + extra, headers=auth_headers)
        assert r.status_code == 200, r.text
        return sorted(p["matricule"] for p in r.json()["properties"])

    assert _mats() == ["FIC-1", "FIC-2", "FIC-3"]
    assert _mats("&proprietaire_collecte=oui") == ["FIC-1"]
    assert _mats("&proprietaire_collecte=non") == ["FIC-2", "FIC-3"]
    assert client.get(q + "&proprietaire_collecte=peut-etre", headers=auth_headers).status_code == 422

    r = client.get(q + "&proprietaire_collecte=oui", headers=auth_headers)
    p = r.json()["properties"][0]
    assert p["arrondissement"] == "Mercier–Hochelaga-Maisonneuve"
    assert p["region"] == "mtl-island" and p["civique_fin"] == "2420"
    assert p["categorie_uef"] == "Régulier"
    assert p["owners_fetched_at"].startswith("2026-09-29")
    assert p["owners"][0] == {
        "name": "PANICCIA, ISABELLA",
        "statut": "Personne physique",
        "postal_address": "12276 60E AVENUE, MONTREAL QUEBEC, H1C 1P3",
        "inscription_date": "2019-05-31",
        "phone": "514-555-0101",
        "neq": None,
        "conditions": None,
    }
    assert p["owners"][1]["neq"] == "1170000000"
    assert p["owners"][1]["postal_address"] is None

    # Même filtre sur l'export.
    r = client.get(
        "/api/v1/prospection/mtl-properties/export.csv?min_annee=2092&max_annee=2092&proprietaire_collecte=oui",
        headers=auth_headers,
    )
    lignes = [l for l in r.text.lstrip("\ufeff").splitlines() if l.strip()]
    assert len(lignes) == 2 and lignes[1].startswith("FIC-1")
