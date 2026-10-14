"""Smoke API — page Achat prêteur B (Phil 2026-10-12).

- une fiche neuve est pré-remplie depuis Paramètres (retenue 100 %,
  3 déboursés) ;
- le calcul expose ``achat_preteur_b`` (vue cashflow) et le PDF se
  génère ;
- PATCH d'un des trois champs → recalcul automatique (avance au
  notaire, fonds de roulement) ;
- en stratégie traditionnelle, ``achat_preteur_b`` est absent.
"""
from __future__ import annotations

import json


def _creer(run) -> int:
    # Même mécanique que les autres smoke du chantier : la fiche est
    # créée directement en base (la création passe par l'extraction).
    from app.models.lead_analysis import LeadAnalysis
    from tests.smoke.conftest import TestSessionLocal

    async def _create():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="1 rue du Prêteur B",
                city="Montréal",
                asking_price=1_000_000,
                nb_logements=10,
                typology_json=json.dumps({"3.5": 10}),
                revenus_bruts=120_000,
                taxes_municipales=10_000,
                taxes_scolaires=800,
                assurances=4_000,
                energie=0,
                depenses_autres=0,
                loyers_projetes_json=json.dumps({"3.5": 1500}),
                travaux_estimes=500_000,
                taux_interet_refi_pct=4.0,
                tga_pct=4.0,
                duree_projet_annees=2,
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    return run(_create())


def test_page_achat_preteur_b(client, auth_headers, run):
    h = auth_headers
    fid = _creer(run)
    base = f"/api/v1/lead-analyses/{fid}"

    # Choisir la stratégie remet les coches « finançable » à zéro : on
    # pose les coches dans un second PATCH (travaux seulement).
    r = client.patch(
        base, headers=h,
        json={"strategie_acquisition": "preteur_b", "mdf_preteur_b_pct": 20},
    )
    assert r.status_code == 200, r.text
    r = client.patch(
        base, headers=h,
        json={"frais_demarrage_financables_json": json.dumps(["frais_travaux"])},
    )
    assert r.status_code == 200, r.text
    r = client.post(f"{base}/run-financial-analysis", headers=h)
    assert r.status_code == 200, r.text
    res = r.json()["analysis_results"]
    # Intrants vides complétés depuis Paramètres et ÉCRITS sur la fiche
    # (aucun repli caché) : retenue 100 %, 3 déboursés.
    fiche = client.get(base, headers=h).json()
    assert float(fiche["retenue_travaux_pct"]) == 100.0
    assert int(fiche["nb_deboursements_travaux"]) == 3
    a = res["achat_preteur_b"]
    assert a["pret_total"] == 1_200_000.0
    assert a["retenue"] == 500_000.0
    assert a["avance_notaire"] == 700_000.0
    assert a["mdf_notaire"] == 300_000.0
    assert a["nb_deboursements"] == 3
    # Échéancier : notaire, 1er déboursé, 3 tranches, refi ; capital non
    # saisi → point bas à 0.
    assert [e["etape"] for e in a["echeancier"]] == [
        "notaire", "deboursement_1", "tranche_1", "tranche_2", "tranche_3", "refi",
    ]
    assert a["capital_saisi"] is False and a["capital"] == a["besoin_max"]
    assert abs(a["point_bas"]["solde"]) < 0.05
    assert abs(a["ecart"]) < 0.05
    # La trace porte la section 6b.
    titres = [s["titre"] for s in res["details_calculs"]]
    assert any(t.startswith("6b · Achat prêteur B") for t in titres)

    # PATCH d'un intrant de la page Achat → recalcul automatique.
    r = client.patch(
        base, headers=h,
        json={"retenue_travaux_pct": 80, "nb_deboursements_travaux": 4},
    )
    assert r.status_code == 200, r.text
    res2 = json.loads(r.json()["analysis_results_json"])
    a2 = res2["achat_preteur_b"]
    assert a2["avance_notaire"] == 800_000.0
    assert a2["manque_notaire"] == 0.0
    assert a2["nb_deboursements"] == 4
    assert len(a2["echeancier"]) == 2 + 4 + 1
    # Montant demandé aux investisseurs = capital du TRI (même colonne).
    r = client.patch(base, headers=h, json={"tri_capital_injecte": 610_000})
    assert r.status_code == 200, r.text
    a3 = json.loads(r.json()["analysis_results_json"])["achat_preteur_b"]
    assert a3["capital"] == 610_000.0 and a3["capital_saisi"] is True
    assert a3["solde_fin"] == round(610_000.0 - a3["cash_definitif"], 2)
    assert a3["manque"] == round(max(0.0, a3["besoin_max"] - 610_000.0), 2)
    tri = client.get(f"{base}/tri-inputs", headers=h).json()
    assert float(tri["inputs"]["capital"]) == 610_000.0

    # PDF = reflet (génération OK avec la nouvelle section).
    r = client.get(f"{base}/pdf", headers=h)
    assert r.status_code == 200, r.text[:200]
    assert r.content[:4] == b"%PDF"
    # Vérification visuelle hors CI : KRATOS_DUMP_PDF=<chemin> écrit le PDF.
    import os

    if os.environ.get("KRATOS_DUMP_PDF"):
        with open(os.environ["KRATOS_DUMP_PDF"], "wb") as f:
            f.write(r.content)

    # Stratégie traditionnelle : pas de vue prêteur B.
    r = client.patch(base, headers=h, json={"strategie_acquisition": "traditionnel"})
    assert r.status_code == 200, r.text
    assert json.loads(r.json()["analysis_results_json"])["achat_preteur_b"] is None
