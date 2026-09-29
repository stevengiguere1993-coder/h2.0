"""Smoke — Rôles fonciers : « Exclure les résidences pour aînés » (codes
d'utilisation 1541 / 1543 / 1549) sur la liste et la collecte en lot (Phil
2026-09-29 : « des maisons pour personnes retraitées, ça ne m'intéresse
pas »)."""
from __future__ import annotations

from app.models.montreal_property_unit import MontrealPropertyUnit

from tests.smoke.conftest import TestSessionLocal


def test_exclure_residences_aines(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            base = dict(region="mtl-island", municipalite="Montréal",
                        annee_construction=2093, nombre_logement=120)
            s.add_all([
                MontrealPropertyUnit(matricule="AIN-1", code_utilisation="1000",
                                     libelle_utilisation="Logement", **base),
                MontrealPropertyUnit(matricule="AIN-2", code_utilisation="1543",
                                     libelle_utilisation="Maison pour personnes retraitées autonomes", **base),
                MontrealPropertyUnit(matricule="AIN-3", code_utilisation="1541",
                                     libelle_utilisation="Maison pour personnes retraitées non autonomes (inclus les CHLSD)", **base),
                MontrealPropertyUnit(matricule="AIN-4", code_utilisation=None, **base),
            ])
            await s.commit()

    run(_seed())
    q = "/api/v1/prospection/mtl-properties?min_annee=2093&max_annee=2093"
    r = client.get(q, headers=auth_headers)
    assert r.json()["total"] == 4
    r = client.get(q + "&exclure_residences_aines=true", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert sorted(p["matricule"] for p in r.json()["properties"]) == ["AIN-1", "AIN-4"]
    r = client.get(
        "/api/v1/prospection/mtl-properties/matricules?min_annee=2093&max_annee=2093"
        "&exclure_residences_aines=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert sorted(r.json()["matricules"]) == ["AIN-1", "AIN-4"]
