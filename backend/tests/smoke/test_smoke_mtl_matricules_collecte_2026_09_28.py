"""Smoke — collecte en lot des propriétaires (Phil 2026-09-28) :
``GET /prospection/mtl-properties/matricules`` renvoie, avec les MÊMES
filtres que la page, les matricules à faire consulter par l'extension
(sans propriétaire connu par défaut), le total du filtre et le nombre
déjà connus."""
from __future__ import annotations

import json

from app.models.montreal_property_unit import MontrealPropertyUnit

from tests.smoke.conftest import TestSessionLocal


def test_matricules_a_collecter(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            s.add_all([
                MontrealPropertyUnit(
                    matricule="COL-0001", civique_debut="1", nom_rue="rue Lot",
                    municipalite="Montréal", arrondissement="Rosemont",
                    nombre_logement=12, code_utilisation="1000",
                ),
                MontrealPropertyUnit(
                    matricule="COL-0002", civique_debut="2", nom_rue="rue Lot",
                    municipalite="Montréal", arrondissement="Rosemont",
                    nombre_logement=18, code_utilisation="1000",
                    owners_json=json.dumps([{"name": "DÉJÀ CONNU INC."}]),
                ),
                MontrealPropertyUnit(
                    matricule="COL-0003", civique_debut="3", nom_rue="rue Lot",
                    municipalite="Montréal", arrondissement="Rosemont",
                    nombre_logement=24, code_utilisation="1000",
                    owners_json="[]",
                ),
                MontrealPropertyUnit(
                    matricule="COL-0004", civique_debut="4", nom_rue="rue Lot",
                    municipalite="Montréal", arrondissement="Villeray",
                    nombre_logement=30, code_utilisation="1000",
                ),
            ])
            await s.commit()

    run(_seed())
    base = "/api/v1/prospection/mtl-properties/matricules"
    # 12 à 24 logements, Rosemont : 3 unités, 1 déjà connue, 2 à collecter
    # (« [] » = aucun propriétaire connu).
    r = client.get(
        f"{base}?min_logements=12&max_logements=24&arrondissement=Rosemont&nom_rue_contains=Lot",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total"] == 3 and d["deja_connus"] == 1
    assert d["matricules"] == ["COL-0001", "COL-0003"]
    assert d["tronque"] is False

    # Sans le filtre « sans propriétaire » : tout le filtre.
    r = client.get(
        f"{base}?min_logements=12&max_logements=24&arrondissement=Rosemont&nom_rue_contains=Lot&sans_proprietaire=false",
        headers=auth_headers,
    )
    assert r.json()["matricules"] == ["COL-0001", "COL-0002", "COL-0003"]

    # Plafond respecté et signalé.
    r = client.get(
        f"{base}?min_logements=12&nom_rue_contains=Lot&limite=1", headers=auth_headers,
    )
    assert r.json()["matricules"] == ["COL-0001"] and r.json()["tronque"] is True

    assert client.get(base).status_code in (401, 403)
