"""Smoke — Phil 2026-10-08 (3451 Adam) : « quand je change le montant de
travaux, rien ne se produit ». Une valeur forcée dans le tableau des
frais de démarrage (override `frais_travaux`) masquait le champ
« Travaux estimés » de la fiche. Règle : travaux, développement et
négociation ne viennent QUE de la fiche ; un override sur ces clés est
reporté dans le champ puis retiré."""
from __future__ import annotations

import json

from app.models.lead_analysis import LeadAnalysis

from tests.smoke.conftest import TestSessionLocal


def _creer(run, **kw) -> int:
    base = dict(
        address="3451 Adam (test)", city="Montréal", asking_price=2_500_000, nb_logements=9,
        typology_json=json.dumps({"4.5": 9}), revenus_bruts=118_401, taxes_municipales=11_436,
        taxes_scolaires=831, assurances=14_117, energie=0, depenses_autres=481,
        loyers_projetes_json=json.dumps({"4.5": 1_450}), taux_interet_refi_pct=4.0, tga_pct=4.0,
        duree_projet_annees=2, travaux_estimes=200_000, frais_developpement=200_000,
        frais_negociations=40_000,
    )
    base.update(kw)

    async def _c():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(**base)
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    return run(_c())


def _travaux_calcules(d: dict) -> float:
    res = d["analysis_results"] if "analysis_results" in d else json.loads(d["analysis_results_json"])
    return float(res["frais_demarrage"]["frais_travaux"])


def test_changer_les_travaux_change_le_calcul_malgre_un_ancien_override(client, auth_headers, run):
    # Ancien override « frais_travaux = 200 000 » saisi dans le tableau des frais.
    fid = _creer(run, frais_demarrage_overrides_json=json.dumps({"frais_travaux": 200_000, "inspection": 4_000}))
    base = f"/api/v1/lead-analyses/{fid}"
    r = client.post(f"{base}/run-financial-analysis", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert _travaux_calcules(r.json()) == 200_000.0
    # L'override sur un poste de la fiche n'est PAS appliqué : 230 000 passe.
    r = client.patch(base, headers=auth_headers, json={"travaux_estimes": 230_000})
    assert r.status_code == 200, r.text
    d = r.json()
    assert not d.get("recalc_error")
    assert _travaux_calcules(d) == 230_000.0
    # L'override a été retiré du JSON, l'inspection (vrai override) reste.
    ov = json.loads(d["frais_demarrage_overrides_json"])
    assert "frais_travaux" not in ov and ov["inspection"] == 4_000
    assert float(json.loads(d["analysis_results_json"])["frais_demarrage"]["inspection"]) == 4_000.0


def test_override_saisi_dans_le_tableau_devient_le_champ_de_la_fiche(client, auth_headers, run):
    fid = _creer(run)
    base = f"/api/v1/lead-analyses/{fid}"
    assert client.post(f"{base}/run-financial-analysis", headers=auth_headers).status_code == 200
    # Un client (ancienne version de la fiche) force travaux + négociation via le tableau.
    r = client.patch(
        base, headers=auth_headers,
        json={"frais_demarrage_overrides_json": json.dumps({"frais_travaux": 250_000, "frais_negociations": 55_000})},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["travaux_estimes"] == 250_000 and d["frais_negociations"] == 55_000
    assert d["frais_demarrage_overrides_json"] in (None, "{}")
    assert not d.get("recalc_error")
    fd = json.loads(d["analysis_results_json"])["frais_demarrage"]
    assert float(fd["frais_travaux"]) == 250_000.0 and float(fd["frais_negociations"]) == 55_000.0
