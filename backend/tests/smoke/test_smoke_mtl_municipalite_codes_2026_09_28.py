"""Smoke — rôle de Montréal : codes de municipalité du fichier de la Ville
(« 50 » = Montréal) convertis en noms à l'import, et filtre « Île de
Montréal » tolérant aux codes déjà en base (Phil 2026-09-28 : « seulement
300 immeubles de 8 logements ou plus sur toute l'île ? »)."""
from __future__ import annotations

from app.integrations.roles_evaluation.montreal import (
    MUNICIPALITE_CODES,
    _row_to_dict,
    nom_municipalite,
)
from app.models.montreal_property_unit import MontrealPropertyUnit

from tests.smoke.conftest import TestSessionLocal


def test_codes_convertis_en_noms():
    assert nom_municipalite("50") == "Montréal"
    assert nom_municipalite("29") == "Westmount"
    assert nom_municipalite("2") == "Baie-D'Urfé"
    assert nom_municipalite("Montréal") == "Montréal"
    assert nom_municipalite("") is None and nom_municipalite(None) is None
    assert len(MUNICIPALITE_CODES) == 16
    row = _row_to_dict({
        "MATRICULE83": "9939-11-8086-8-000-0000", "CIVIQUE_DEBUT": " 1550",
        "NOM_RUE": "rue Saint-Antoine Ouest  (MTL)", "MUNICIPALITE": "50",
        "NOMBRE_LOGEMENT": "12", "ANNEE_CONSTRUCTION": "1885",
        "CODE_UTILISATION": "1000",
    })
    assert row["municipalite"] == "Montréal"
    assert row["nombre_logement"] == 12 and row["region"] == "mtl-island"


def test_filtre_ile_de_montreal_tolere_les_codes(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            s.add_all([
                # Import ancien : code brut, sans région.
                MontrealPropertyUnit(
                    matricule="CODE-50-A", civique_debut="1", nom_rue="rue Code",
                    municipalite="50", nombre_logement=16, code_utilisation="1000",
                ),
                # Import corrigé : nom.
                MontrealPropertyUnit(
                    matricule="CODE-NOM-B", civique_debut="2", nom_rue="rue Code",
                    municipalite="Montréal", nombre_logement=20, code_utilisation="1000",
                ),
                # Hors île.
                MontrealPropertyUnit(
                    matricule="CODE-LAVAL-C", civique_debut="3", nom_rue="rue Code",
                    municipalite="Laval", nombre_logement=30, code_utilisation="1000",
                ),
            ])
            await s.commit()

    run(_seed())
    r = client.get(
        "/api/v1/prospection/mtl-properties?min_logements=8&distance_band=mtl_only&nom_rue_contains=Code",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    mats = sorted(p["matricule"] for p in r.json()["properties"])
    assert mats == ["CODE-50-A", "CODE-NOM-B"]
    assert r.json()["total"] == 2
