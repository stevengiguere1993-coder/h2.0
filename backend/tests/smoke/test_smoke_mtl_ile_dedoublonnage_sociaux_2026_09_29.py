"""Smoke — île de Montréal (Phil 2026-09-28 : « 24 029 de 8 logements et
plus ? », filtre arrondissement, exclure les logements sociaux, année de
construction, « propriétaire depuis combien de temps »).

* fusion des jumelles provinciales (« 66023-9939-11-8086-8 ») avec les
  lignes du fichier de la Ville (« 9939-11-8086-8-000-0000 ») ;
* arrondissement lu dans les codes NO_ARROND_ILE_CUM du fichier ;
* ré-import qui conserve les propriétaires collectés ;
* marquage des logements sociaux (fichier de la Ville + propriétaires) et
  filtre ``exclure_sociaux`` ;
* « propriétaire depuis N ans ».
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.endpoints.mtl_properties import _annees_depuis
from app.integrations.roles_evaluation.montreal import (
    ARRONDISSEMENT_CODES,
    _row_to_dict,
    nom_arrondissement,
)
from app.integrations.roles_evaluation.upsert_commun import colonnes_upsert
from app.models.montreal_property_unit import MontrealPropertyUnit
from app.models.prospection_lead import ProspectionLead
from app.models.user import User
from app.services.logements_sociaux import (
    categorie_proprietaire_social,
    charger_projets,
    marquer_logements_sociaux,
    normaliser_rue,
    normaliser_secteur,
)
from app.services.mtl_dedoublonnage import fusionner_jumelles

from tests.smoke.conftest import TestSessionLocal


def _role_admin(run, admin_id: int, role: str) -> None:
    """Les endpoints admin/data exigent le rôle « owner » ; l'admin des
    tests est « admin » → on le promeut le temps du test, puis on restaure."""

    async def _set():
        async with TestSessionLocal() as s:
            await s.execute(update(User).where(User.id == admin_id).values(role=role))
            await s.commit()

    run(_set())


# ─────────────────────────── jumelles ───────────────────────────

def test_fusion_des_jumelles_provinciales(client, auth_headers, run, admin_id):
    async def _seed():
        async with TestSessionLocal() as s:
            s.add_all([
                # Ligne Ville (référence) sans propriétaire.
                MontrealPropertyUnit(
                    matricule="9939-11-8086-8-000-0000", region="mtl-island",
                    municipalite="Montréal", civique_debut="1550",
                    nom_rue="rue Saint-Antoine Ouest  (MTL)", nombre_logement=12,
                ),
                # Jumelle provinciale AVEC propriétaire + arrondissement → reportés.
                MontrealPropertyUnit(
                    matricule="66023-9939-11-8086-8", region="quebec",
                    municipalite="Montréal", nombre_logement=12,
                    owners_json=json.dumps([{"name": "JUMELLE INC.", "inscription_date": "2015-01-01"}]),
                    arrondissement="Ville-Marie",
                ),
                # Jumelle avec suffixes (condo) — clé exacte.
                MontrealPropertyUnit(
                    matricule="1111-22-3333-4-001-0002", region="mtl-island",
                    municipalite="Westmount", nombre_logement=9,
                ),
                MontrealPropertyUnit(
                    matricule="66032-1111-22-3333-4-001-0002", region="quebec",
                    municipalite="Montréal-Est", nombre_logement=9,
                ),
                # Provinciale de l'île SANS jumelle → gardée.
                MontrealPropertyUnit(
                    matricule="66023-0000-00-0000-0", region="quebec",
                    municipalite="Montréal", nombre_logement=8,
                ),
                # Laval → jamais touchée.
                MontrealPropertyUnit(
                    matricule="65005-4444-55-6666-7", region="quebec",
                    municipalite="Laval", nombre_logement=10,
                ),
            ])
            s.add(ProspectionLead(name="Lead jumelle", matricule="66023-9939-11-8086-8"))
            await s.commit()

    run(_seed())
    _role_admin(run, admin_id, "owner")
    try:
        _scenario_fusion(client, auth_headers, run)
    finally:
        _role_admin(run, admin_id, "admin")


def _scenario_fusion(client, auth_headers, run) -> None:
    r = client.post(
        "/api/v1/admin/data/mtl-roles/dedupe?dry_run=true", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["dry_run"] is True
    assert d["jumelles"] == 2 and d["jumelles_8_plus"] == 2
    assert d["avec_proprietaires"] == 1 and d["leads_a_rattacher"] == 1
    assert d["provinciales_sans_jumelle"] == 1

    async def _fusion():
        async with TestSessionLocal() as s:
            res = await fusionner_jumelles(s)
            await s.commit()
            return res

    res = run(_fusion())
    assert res["supprimees"] == 2
    assert res["proprietaires_reportes"] == 1
    assert res["arrondissements_reportes"] == 1
    assert res["leads_rattaches"] == 1

    async def _apres():
        async with TestSessionLocal() as s:
            mats = set((await s.execute(select(MontrealPropertyUnit.matricule))).scalars().all())
            ville = await s.get(MontrealPropertyUnit, "9939-11-8086-8-000-0000")
            lead = (
                await s.execute(select(ProspectionLead).where(ProspectionLead.name == "Lead jumelle"))
            ).scalar_one()
            return mats, ville.owners_json, ville.arrondissement, lead.matricule

    mats, owners, arr, lead_mat = run(_apres())
    assert "66023-9939-11-8086-8" not in mats
    assert "66032-1111-22-3333-4-001-0002" not in mats
    assert {"9939-11-8086-8-000-0000", "1111-22-3333-4-001-0002",
            "66023-0000-00-0000-0", "65005-4444-55-6666-7"} <= mats
    assert "JUMELLE INC." in (owners or "") and arr == "Ville-Marie"
    assert lead_mat == "9939-11-8086-8-000-0000"

    # Rejouer = rien à faire (idempotent).
    r = client.post(
        "/api/v1/admin/data/mtl-roles/dedupe?dry_run=true", headers=auth_headers
    )
    assert r.json()["jumelles"] == 0


# ─────────────────────────── arrondissements ───────────────────────────

def test_arrondissement_depuis_les_codes_du_fichier():
    assert len(ARRONDISSEMENT_CODES) == 19
    assert nom_arrondissement("REM19", "50") == "Ville-Marie"
    assert nom_arrondissement("REM21", "Montréal") == "Le Plateau-Mont-Royal"
    assert nom_arrondissement("REM34", "50") == "Côte-des-Neiges–Notre-Dame-de-Grâce"
    # Ville liée : pas d'arrondissement ; code inconnu : None.
    assert nom_arrondissement("REM99", "29") is None
    assert nom_arrondissement("REM77", "50") is None
    row = _row_to_dict({
        "MATRICULE83": "9939-11-8086-8-000-0000", "CIVIQUE_DEBUT": "1550",
        "NOM_RUE": "rue Saint-Antoine Ouest  (MTL)", "MUNICIPALITE": "50",
        "NOMBRE_LOGEMENT": "12", "NO_ARROND_ILE_CUM": "REM19",
    })
    assert row["arrondissement"] == "Ville-Marie"


def test_reimport_conserve_les_proprietaires_collectes():
    stmt = pg_insert(MontrealPropertyUnit).values([
        {"matricule": "X-1", "nom_rue": "rue Test", "arrondissement": None}
    ])
    cols = colonnes_upsert(stmt)
    assert "owners_json" not in cols and "owners_fetched_at" not in cols
    assert "logement_social" not in cols and "matricule" not in cols
    assert "nom_rue" in cols and "nombre_logement" in cols
    assert "coalesce" in str(cols["arrondissement"]).lower()


# ─────────────────────────── logements sociaux ───────────────────────────

_CSV = (
    "OBJECTID;IdGeom;Projetnom;phase;nlog;nbchambre;unites_typ;type;an_program;"
    "nomrue;arrond;villelie;qr2008;loghlm_fam;loghlm_pa;loghlm_aut;xnad83_ts;"
    "ynad83_ts;Long_x;Latitud_y\n"
    "1;1;Saint-Sulpice;;150;0;logement;HLM;1971;Louvain;Ahuntsic-Cartierville;;5;148;0;2;1;1;-73.6;45.5\n"
    "2;2;Coop du Boulevard;;12;0;logement;Coop;1990;Pie IX;Mercier–Hochelaga-Maisonneuve;;1;0;0;0;1;1;-73.5;45.5\n"
    "3;3;Villa CSL;;24;0;logement;OBNL;2001;Kildare;;Côte Saint-Luc;1;0;0;0;1;1;-73.6;45.4\n"
)


def test_normalisation_rues_et_secteurs():
    assert normaliser_rue("rue de Louvain Ouest  (MTL)") == "louvain"
    assert normaliser_rue("Louvain") == "louvain"
    assert normaliser_rue("boulevard Pie-IX  (MTL)") == normaliser_rue("Pie IX") == "pie ix"
    assert normaliser_rue("20e Avenue  (PAT)") == normaliser_rue("20e avenue") == "20e"
    assert normaliser_rue("avenue du Mont-Royal Est  (MTL)") == "mont royal"
    assert normaliser_rue("chemin de la Côte-Sainte-Catherine") == normaliser_rue("de la Côte-Sainte-Catherine")
    assert normaliser_secteur("Côte-des-Neiges–Notre-Dame-de-Grâce") == "cote des neiges notre dame de grace"
    assert normaliser_secteur("Côte Saint-Luc") == normaliser_secteur("Côte-Saint-Luc")
    projets = charger_projets(_CSV)
    assert projets[("ahuntsic cartierville", "louvain", 150)] == ("HLM", "Saint-Sulpice")
    assert projets[("cote saint luc", "kildare", 24)] == ("OBNL", "Villa CSL")


def test_categorie_proprietaire_social():
    assert categorie_proprietaire_social("OFFICE MUNICIPAL D'HABITATION DE MONTRÉAL") == "Office d'habitation"
    assert categorie_proprietaire_social("SOCIÉTÉ D'HABITATION ET DE DÉVELOPPEMENT DE MONTRÉAL") == "SHDM"
    assert categorie_proprietaire_social("COOPÉRATIVE D'HABITATION LE SOLEIL") == "Coop"
    assert categorie_proprietaire_social("LES HABITATIONS COMMUNAUTAIRES DU SUD-OUEST") == "OBNL"
    assert categorie_proprietaire_social("GESTION PRIVÉE INC.") is None
    assert categorie_proprietaire_social("COOP FÉDÉRÉE (AGRICOLE)") is None
    assert categorie_proprietaire_social(None) is None


def test_marquage_et_filtre_exclure_sociaux(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            base = dict(region="mtl-island", annee_construction=2099, code_utilisation="1000")
            s.add_all([
                MontrealPropertyUnit(  # HLM : arrondissement + rue + 150 → marqué
                    matricule="SOC-1", municipalite="Montréal", arrondissement="Ahuntsic-Cartierville",
                    nom_rue="rue de Louvain Ouest  (MTL)", nombre_logement=150, **base,
                ),
                MontrealPropertyUnit(  # coop 12 logements sur Pie-IX → marqué
                    matricule="SOC-2", municipalite="Montréal", arrondissement="Mercier–Hochelaga-Maisonneuve",
                    nom_rue="boulevard Pie-IX  (MTL)", nombre_logement=12, **base,
                ),
                MontrealPropertyUnit(  # même rue, 16 logements → privé, pas marqué
                    matricule="SOC-3", municipalite="Montréal", arrondissement="Mercier–Hochelaga-Maisonneuve",
                    nom_rue="boulevard Pie-IX  (MTL)", nombre_logement=16, **base,
                ),
                MontrealPropertyUnit(  # Montréal SANS arrondissement → ignoré (compté)
                    matricule="SOC-4", municipalite="Montréal", arrondissement=None,
                    nom_rue="rue de Louvain Ouest  (MTL)", nombre_logement=150, **base,
                ),
                MontrealPropertyUnit(  # ville liée : clé = municipalité
                    matricule="SOC-5", municipalite="Côte-Saint-Luc", arrondissement=None,
                    nom_rue="avenue Kildare  (CSL)", nombre_logement=24, **base,
                ),
                MontrealPropertyUnit(  # propriétaire = OMHM → marqué
                    matricule="SOC-6", municipalite="Montréal", arrondissement="Rosemont–La Petite-Patrie",
                    nom_rue="rue Test  (MTL)", nombre_logement=40,
                    owners_json=json.dumps([{"name": "OFFICE MUNICIPAL D'HABITATION DE MONTRÉAL"}]), **base,
                ),
                MontrealPropertyUnit(  # propriétaire privé → pas marqué
                    matricule="SOC-7", municipalite="Montréal", arrondissement="Rosemont–La Petite-Patrie",
                    nom_rue="rue Test  (MTL)", nombre_logement=40,
                    owners_json=json.dumps([{"name": "GESTION PRIVÉE INC.", "inscription_date": "2017-03-15"}]), **base,
                ),
            ])
            await s.commit()

    run(_seed())

    async def _marquer():
        async with TestSessionLocal() as s:
            res = await marquer_logements_sociaux(s, texte_csv=_CSV)
            await s.commit()
            return res

    res = run(_marquer())
    assert res["projets"] == 3
    assert res["marquees_fichier"] == 3 and res["marquees_proprietaire"] == 1
    assert res["montreal_sans_arrondissement"] == 1
    assert res["par_type"] == {"HLM": 1, "Coop": 1, "OBNL": 1}

    def _liste(exclure: bool) -> dict:
        url = "/api/v1/prospection/mtl-properties?min_annee=2099&max_annee=2099&sort_by=matricule_asc"
        if exclure:
            url += "&exclure_sociaux=true"
        r = client.get(url, headers=auth_headers)
        assert r.status_code == 200, r.text
        return {p["matricule"]: p for p in r.json()["properties"]}

    tous = _liste(False)
    assert set(tous) == {f"SOC-{i}" for i in range(1, 8)}
    assert tous["SOC-1"]["logement_social"] == "HLM · Saint-Sulpice"
    assert tous["SOC-2"]["logement_social"] == "Coop · Coop du Boulevard"
    assert tous["SOC-5"]["logement_social"] == "OBNL · Villa CSL"
    assert tous["SOC-6"]["logement_social"] == "Office d'habitation · propriétaire"
    assert tous["SOC-3"]["logement_social"] is None
    # « propriétaire depuis N ans » (SOC-7 inscrit le 2017-03-15).
    attendu = date.today().year - 2017 - ((date.today().month, date.today().day) < (3, 15))
    assert tous["SOC-7"]["proprietaire_depuis_annees"] == attendu
    assert tous["SOC-6"]["proprietaire_depuis_annees"] is None

    sans = _liste(True)
    assert set(sans) == {"SOC-3", "SOC-4", "SOC-7"}

    # Export CSV : mêmes filtres, colonnes « Propriétaire depuis (ans) » et
    # « Logement social ».
    r = client.get(
        "/api/v1/prospection/mtl-properties/export.csv?min_annee=2099&max_annee=2099&exclure_sociaux=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    lignes = [l for l in r.text.lstrip("﻿").splitlines() if l.strip()]
    assert "Propriétaire depuis (ans)" in lignes[0] and "Logement social" in lignes[0]
    assert len(lignes) == 4  # en-tête + 3 lignes non sociales
    assert any(l.startswith("SOC-7") and f";{attendu};" in l for l in lignes[1:])

    # Collecte en lot : le filtre s'applique aussi aux matricules envoyés.
    r = client.get(
        "/api/v1/prospection/mtl-properties/matricules?min_annee=2099&max_annee=2099&exclure_sociaux=true&sans_proprietaire=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert sorted(r.json()["matricules"]) == ["SOC-3", "SOC-4"]


def test_annees_depuis():
    y = date.today().year
    assert _annees_depuis(f"{y - 3}-01-01") == 3
    assert _annees_depuis(f"01/01/{y - 3}") == 3
    assert _annees_depuis(f"1er janvier {y - 3}") == 3
    assert _annees_depuis(f"{y + 1}-01-01") == 0
    assert _annees_depuis("n'importe quoi") is None
    assert _annees_depuis(None) is None
