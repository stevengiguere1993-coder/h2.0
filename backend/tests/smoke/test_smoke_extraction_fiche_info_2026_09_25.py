"""Smoke — Phil 2026-09-25 : « l'extracteur remplit uniquement les
paramètres de la fiche info, s'il n'y a rien il met rien ; le calculateur
prend uniquement ces informations, il ne peut pas être modifié dans le
backend ».

1. « Autres dépenses » n'est plus extrait (aucune couche IA, aucune
   ré-extraction) : c'est une saisie manuelle de la fiche info.
2. Le calcul n'a plus de nombre de repli : un intrant vide est comblé
   depuis Paramètres → Analyse et ÉCRIT sur la fiche avant le calcul.
"""
from __future__ import annotations

import json

from app.api.v1.endpoints import lead_analyses as ep
from app.models.lead_analysis import LeadAnalysis
from app.services import lead_extraction as ex
from app.services import lead_extraction_groq as gq

from tests.smoke.conftest import TestSessionLocal


def test_autres_depenses_hors_extraction():
    # Mapping extraction → fiche : le champ est ignoré même si l'IA le renvoie.
    out = ep._map_extracted_to_lead({"asking_price": 1_000_000, "depenses_autres": 40_346})
    assert out.get("asking_price") == 1_000_000
    assert "depenses_autres" not in out
    # Trace par couche (local / Gemini) : plus suivi.
    assert "depenses_autres" not in ex._PER_SOURCE_TRACKED
    assert "depenses_autres" not in ex._NUMERIC_FIELDS
    assert ex._build_per_source({"depenses_autres": 1}, {"depenses_autres": 2}) == {}
    # Consignes aux LLM : le champ n'est plus demandé.
    assert "depenses_autres" not in ex.SCHEMA_GUIDE
    assert "depenses_autres" not in json.dumps(gq.SAVE_LEAD_FIELDS_TOOL) if hasattr(gq, "SAVE_LEAD_FIELDS_TOOL") else True
    assert "depenses_autres" not in gq._PATCHABLE_FIELDS
    assert "depenses_autres" not in ep._PATCHABLE_FIELDS
    # Les champs de la fiche info restent extraits.
    for champ in ("address", "city", "postal_code", "type_batiment", "asking_price",
                  "annee_construction", "nb_logements", "nb_stationnements",
                  "revenus_bruts", "evaluation_municipale", "taxes_municipales",
                  "taxes_scolaires", "assurances", "energie", "superficie_terrain",
                  "superficie_batiment", "courtier_nom", "courtier_contact"):
        assert ep._map_extracted_to_lead({champ: "x" if champ in ("address", "city", "postal_code", "type_batiment", "courtier_nom", "courtier_contact") else 7}).get(champ) is not None, champ


def test_calcul_sans_repli_dans_le_code(client, auth_headers, run):
    """Fiche avec des intrants VIDES (TGA, taux, durée, horizon, prêt
    résidentiel…) : le calcul les comble depuis Paramètres, les écrit sur
    la fiche et les journalise — aucun 4.0 / 25 / 5 caché dans le code."""

    async def _create():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="1 rue Sans-Repli",
                city="Montréal",
                asking_price=1_000_000,
                nb_logements=10,
                typology_json=json.dumps({"3.5": 10}),
                revenus_bruts=100_000,
                taxes_municipales=10_000,
                taxes_scolaires=800,
                assurances=4_000,
                energie=0,
                loyers_projetes_json=json.dumps({"3.5": 1200}),
                # Tout le reste VIDE volontairement.
                tga_pct=None,
                taux_interet_achat_pct=None,
                taux_interet_refi_pct=None,
                duree_projet_annees=None,
                mdf_preteur_b_pct=None,
                taux_interet_preteur_b_projet_pct=None,
                ajout_wifi=None,
                projection_horizon_annees=None,
                ltv_residentiel_pct=None,
                amort_residentiel_annees=None,
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    aid = run(_create())
    r = client.post(
        f"/api/v1/lead-analyses/{aid}/run-financial-analysis", headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    async def _lire():
        async with TestSessionLocal() as s:
            return await s.get(LeadAnalysis, aid)

    rec = run(_lire())
    # Comblés depuis Paramètres (défauts seedés) et ÉCRITS sur la fiche.
    assert rec.tga_pct == 4.0
    assert rec.taux_interet_achat_pct == 4.0
    assert rec.taux_interet_refi_pct == 3.75
    assert rec.duree_projet_annees == 2
    assert rec.mdf_preteur_b_pct == 25.0
    assert rec.taux_interet_preteur_b_projet_pct == 8.0
    assert rec.ajout_wifi is True
    assert rec.projection_horizon_annees == 5
    assert rec.ltv_residentiel_pct == 80.0
    assert rec.amort_residentiel_annees == 25
    assert float(rec.tri_croissance_loyers) == 0.03
    assert float(rec.tri_croissance_depenses) == 0.03
    res = json.loads(rec.analysis_results_json)
    completes = set(res["intrants_completes_depuis_parametres"])
    # (TGA, taux achat et durée ont aussi un défaut de modèle appliqué à la
    # création — déjà visibles sur la fiche ; les autres sont comblés ici.)
    assert {"projection_horizon_annees", "ltv_residentiel_pct",
            "amort_residentiel_annees", "tri_croissance_loyers",
            "tri_croissance_depenses"} <= completes
    # Et le calcul a bien utilisé CES valeurs (TGA 4 %).
    achat = res["scenarios"]["achat"]
    assert abs(achat["valeur_eco_tga"] - achat["revenus_net"] / 0.04) < 0.01
    # « Autres dépenses » vide = 0 dans le calcul, rien d'inventé.
    assert achat["depenses"]["autres"] == 0

    # Deuxième calcul : rien à combler, valeurs identiques.
    r2 = client.post(
        f"/api/v1/lead-analyses/{aid}/run-financial-analysis", headers=auth_headers,
    )
    assert r2.status_code == 200
    rec2 = run(_lire())
    assert json.loads(rec2.analysis_results_json)["intrants_completes_depuis_parametres"] == []
