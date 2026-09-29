"""Smoke — Rôles fonciers : filtre « propriétaire depuis au moins N ans »
(Phil 2026-09-29 : « disons minimum 5 ans ? »). La date d'inscription au
rôle n'existe que sur la fiche montreal.ca : seules les unités dont le
propriétaire a été collecté peuvent passer le filtre."""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.endpoints.mtl_properties import date_inscription_min
from app.integrations.roles_evaluation.upsert_commun import colonnes_upsert
from app.models.montreal_property_unit import MontrealPropertyUnit

from tests.smoke.conftest import TestSessionLocal


def _owners(*dates):
    return json.dumps(
        [{"name": f"PROPRIO {i}", "inscription_date": d} for i, d in enumerate(dates)]
    )


def test_date_inscription_min_et_upsert():
    assert date_inscription_min(
        [{"inscription_date": "2021-01-01"}, {"inscription_date": "2012-06-01"}]
    ) == date(2012, 6, 1)
    assert date_inscription_min([{"name": "X"}]) is None
    assert date_inscription_min(None) is None
    stmt = pg_insert(MontrealPropertyUnit).values([{"matricule": "X-2"}])
    assert "proprietaire_depuis" not in colonnes_upsert(stmt)


def test_filtre_proprietaire_depuis(client, auth_headers, run):
    y = date.today().year

    async def _seed():
        async with TestSessionLocal() as s:
            base = dict(region="mtl-island", municipalite="Montréal",
                        annee_construction=2097, nombre_logement=10, code_utilisation="1000")
            s.add_all([
                # Collecté AVANT la colonne : rattrapé à la volée.
                MontrealPropertyUnit(matricule="DEP-1", owners_json=_owners("2010-05-01"), **base),
                # Deux propriétaires : la plus ancienne date compte.
                MontrealPropertyUnit(matricule="DEP-2", owners_json=_owners(f"{y - 1}-01-01", f"{y - 8}-01-01"), **base),
                # Acheté il y a 2 ans.
                MontrealPropertyUnit(matricule="DEP-3", owners_json=_owners(f"{y - 2}-01-01"), **base),
                # Propriétaire pas encore collecté.
                MontrealPropertyUnit(matricule="DEP-4", **base),
            ])
            await s.commit()

    run(_seed())

    def _liste(qs: str) -> dict:
        r = client.get(
            f"/api/v1/prospection/mtl-properties?min_annee=2097&max_annee=2097&{qs}",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        return {p["matricule"]: p for p in r.json()["properties"]}

    assert set(_liste("")) == {"DEP-1", "DEP-2", "DEP-3", "DEP-4"}
    res = _liste("proprietaire_min_annees=5")
    assert set(res) == {"DEP-1", "DEP-2"}
    assert res["DEP-2"]["proprietaire_depuis_annees"] == 8
    assert set(_liste("proprietaire_min_annees=1")) == {"DEP-1", "DEP-2", "DEP-3"}

    async def _dates():
        async with TestSessionLocal() as s:
            u = await s.get(MontrealPropertyUnit, "DEP-1")
            return u.proprietaire_depuis

    assert run(_dates()) == date(2010, 5, 1)

    # Même filtre pour l'export et la collecte en lot.
    r = client.get(
        "/api/v1/prospection/mtl-properties/export.csv?min_annee=2097&max_annee=2097&proprietaire_min_annees=5",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    lignes = [l for l in r.text.lstrip("﻿").splitlines() if l.strip()]
    assert len(lignes) == 3
