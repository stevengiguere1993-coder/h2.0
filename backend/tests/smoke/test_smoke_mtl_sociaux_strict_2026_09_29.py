"""Smoke — logements sociaux, règle stricte (Phil 2026-09-29 : « quand je
clique sur exclure logements sociaux, ça change rien au nombre ») :
un projet du fichier de la Ville ne marque un immeuble que si UN SEUL
immeuble du rôle a (arrondissement, rue, nombre de logements) ; la partie
« fichier » est recalculée à chaque passage (marquages par propriétaire
gardés) ; la liste dit combien d'unités le filtre retire."""
from __future__ import annotations

from app.models.montreal_property_unit import MontrealPropertyUnit
from app.services.logements_sociaux import marquer_logements_sociaux

from tests.smoke.conftest import TestSessionLocal

_CSV = (
    "OBJECTID;IdGeom;Projetnom;phase;nlog;nbchambre;unites_typ;type;an_program;"
    "nomrue;arrond;villelie;qr2008;loghlm_fam;loghlm_pa;loghlm_aut;xnad83_ts;"
    "ynad83_ts;Long_x;Latitud_y\n"
    "1;1;Coop Verdun;;8;0;logement;Coop;1990;de Verdun;Verdun;;1;0;0;0;1;1;-73.5;45.4\n"
    "2;2;HLM Wellington;;30;0;logement;HLM;1975;Wellington;Verdun;;1;0;0;0;1;1;-73.5;45.4\n"
)


def test_regle_stricte_et_recalcul(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            base = dict(region="mtl-island", municipalite="Montréal", arrondissement="Verdun",
                        annee_construction=2096, code_utilisation="1000")
            s.add_all([
                # Deux 8 logements sur la rue de Verdun : ambigu → aucun marqué.
                MontrealPropertyUnit(matricule="VRD-1", nom_rue="rue de Verdun  (VRD)", nombre_logement=8, **base),
                MontrealPropertyUnit(matricule="VRD-2", nom_rue="rue de Verdun  (VRD)", nombre_logement=8, **base),
                # Un seul 30 logements sur Wellington → marqué.
                MontrealPropertyUnit(matricule="VRD-3", nom_rue="rue Wellington  (VRD)", nombre_logement=30, **base),
                # Ancien marquage « fichier » qui ne correspond plus → retiré.
                MontrealPropertyUnit(matricule="VRD-4", nom_rue="rue Bannantyne  (VRD)", nombre_logement=12,
                                     logement_social="HLM · Ancienne règle", **base),
                # Marquage par propriétaire → gardé.
                MontrealPropertyUnit(matricule="VRD-5", nom_rue="rue Galt  (VRD)", nombre_logement=20,
                                     logement_social="Coop · propriétaire", **base),
            ])
            await s.commit()

    run(_seed())

    async def _marquer():
        async with TestSessionLocal() as s:
            res = await marquer_logements_sociaux(s, texte_csv=_CSV)
            await s.commit()
            return res

    res = run(_marquer())
    assert res["marquees_fichier"] == 1
    assert res["projets_ambigus"] == 1

    def _liste(exclure: bool) -> dict:
        url = "/api/v1/prospection/mtl-properties?min_annee=2096&max_annee=2096"
        if exclure:
            url += "&exclure_sociaux=true"
        r = client.get(url, headers=auth_headers)
        assert r.status_code == 200, r.text
        return r.json()

    tous = _liste(False)
    par_mat = {p["matricule"]: p for p in tous["properties"]}
    assert par_mat["VRD-3"]["logement_social"] == "HLM · HLM Wellington"
    assert par_mat["VRD-1"]["logement_social"] is None
    assert par_mat["VRD-2"]["logement_social"] is None
    assert par_mat["VRD-4"]["logement_social"] is None  # recalculé
    assert par_mat["VRD-5"]["logement_social"] == "Coop · propriétaire"
    assert tous["sociaux_exclus"] is None  # case décochée

    sans = _liste(True)
    assert {p["matricule"] for p in sans["properties"]} == {"VRD-1", "VRD-2", "VRD-4"}
    assert sans["total"] == 3
    assert sans["sociaux_exclus"] == 2

    # Rejouer donne le même résultat.
    res2 = run(_marquer())
    assert res2["marquees_fichier"] == 1


def test_copie_embarquee_si_telechargement_bloque(run):
    """Le 2026-09-29, donnees.montreal.ca a répondu 403 au serveur : le
    marquage doit retomber sur la copie embarquée au lieu d'échouer."""
    from app.services import logements_sociaux as ls

    async def _go():
        return await ls.charger_texte_csv(url="http://127.0.0.1:9/bloque.csv")

    texte, source = run(_go())
    assert source.startswith("copie")
    assert len(ls.charger_projets(texte)) > 1500
