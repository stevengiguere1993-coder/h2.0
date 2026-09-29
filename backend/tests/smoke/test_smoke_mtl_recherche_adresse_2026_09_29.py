"""Smoke — Rôles fonciers, recherche par adresse (Phil 2026-09-29 :
« filtrer par numéro d'adresse, rue… disons 1660 » ; « j'essaie d'acheter
le 2420 Pie-IX de 8 logements et je ne le trouve pas ») + auto-configuration
de l'extension (« Échec envoi : Backend URL non configurée »)."""
from __future__ import annotations

from app.integrations.roles_evaluation.montreal import make_search_key
from app.models.montreal_property_unit import MontrealPropertyUnit

from tests.smoke.conftest import TestSessionLocal

_PIE = "boulevard Pie-IX  (MTL+MTN+SLN)"
_CLEMENT = "rue Saint-Clément  (MTL)"


def _unite(mat, debut, fin, rue, nb):
    return MontrealPropertyUnit(
        matricule=mat, civique_debut=debut, civique_fin=fin, nom_rue=rue,
        search_key=make_search_key(debut, rue), nombre_logement=nb,
        annee_construction=2098, region="mtl-island", municipalite="Montréal",
        code_utilisation="1000",
    )


def test_recherche_par_numero_civique_et_rue(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            s.add_all([
                _unite("ADR-1", "2420", "2420", _PIE, 8),
                _unite("ADR-2", "2402", "2406", _PIE, 3),
                _unite("ADR-3", "1660", "1672", _CLEMENT, 12),
                _unite("ADR-4", "12A", None, "rue Test  (MTL)", 4),
            ])
            await s.commit()

    run(_seed())

    def _mats(qs: str) -> set:
        r = client.get(
            f"/api/v1/prospection/mtl-properties?min_annee=2098&max_annee=2098&{qs}",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        return {p["matricule"] for p in r.json()["properties"]}

    assert _mats("numero_civique=2420") == {"ADR-1"}
    assert _mats("numero_civique=2404") == {"ADR-2"}  # dans la plage 2402-2406
    assert _mats("numero_civique=1665") == {"ADR-3"}  # dans la plage 1660-1672
    assert _mats("numero_civique=1660") == {"ADR-3"}
    # Rue tolérante : espace au lieu du tiret, abréviation, sans accent.
    assert _mats("nom_rue_contains=pie ix") == {"ADR-1", "ADR-2"}
    assert _mats("nom_rue_contains=Pie-IX") == {"ADR-1", "ADR-2"}
    assert _mats("nom_rue_contains=St-Clement") == {"ADR-3"}
    assert _mats("nom_rue_contains=saint clément") == {"ADR-3"}
    # Adresse complète dans le champ rue.
    assert _mats("nom_rue_contains=2420 pie-ix") == {"ADR-1"}
    assert _mats("nom_rue_contains=1665, St-Clément") == {"ADR-3"}
    # Numéro non numérique en base : pas d'erreur.
    r = client.get(
        "/api/v1/prospection/mtl-properties?numero_civique=12&min_annee=2098",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    # Même filtre sur l'export et la collecte en lot.
    r = client.get(
        "/api/v1/prospection/mtl-properties/matricules?min_annee=2098&max_annee=2098&numero_civique=2420",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["matricules"] == ["ADR-1"]


def test_configuration_extension(client, auth_headers):
    r = client.get("/api/v1/extension/config", headers=auth_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == {"backend_url", "api_key"}
    assert d["backend_url"].startswith("http")
    # Réservé aux utilisateurs connectés.
    assert client.get("/api/v1/extension/config").status_code == 401
