"""Smoke — TRI projet (Phil 2026-10-08) : à côté du TRI investisseur
(inchangé), le moteur expose le rendement du projet lui-même — même
capital injecté et mêmes croissances, mais tout l'argent disponible
ressort à chaque refinancement (un manque est une injection) et l'équité
entière est liquidée à la sortie, sans partage de parts."""
from __future__ import annotations

from app.services.lead_tri_calc import compute_tri, irr


def _base(**kw) -> dict:
    d = dict(
        prix=1_000_000.0, rpv_achat=0.75, pret_constr=0.0, mdf=250_000.0,
        capital=300_000.0, pct=0.5, loyers2=150_000.0, dep2=50_000.0,
        valeur2=2_500_000.0, rpv_refi=0.85, cr_loyers=0.03, cr_dep=0.03,
    )
    d.update(kw)
    return d


def test_vue_projet_exposee_et_coherente():
    r = compute_tri(**_base())
    h0, h1, h2 = r["horizons_list"]
    assert set(r["tri_projet"].keys()) == {f"an{h0}", f"an{h1}", f"an{h2}"}
    assert set(r["flux_projet"].keys()) == {str(h0), str(h1), str(h2)}
    for h in (h0, h1, h2):
        hd = r["horizons"][str(h)]
        # Le projet ressort TOUT l'argent disponible (pas de cascade).
        assert hd["cash_projet"] == hd["argent_dispo"]
    # Patrimoine du projet = cash sorti cumulé + équité.
    hz = r["horizons"]
    cumul = 0.0
    for h in (h0, h1, h2):
        cumul += hz[str(h)]["cash_projet"]
        assert abs(hz[str(h)]["patrimoine_projet"] - (cumul + hz[str(h)]["equite"])) < 1e-6
    # Flux projet : −capital à l'an 0, argent dispo à chaque refi, équité à la sortie.
    f = r["flux_projet"][str(h2)]
    assert len(f) == h2 + 1 and abs(f[0] + 300_000.0) < 1e-6
    assert abs(f[h0] - hz[str(h0)]["cash_projet"]) < 1e-6
    assert abs(f[h2] - (hz[str(h2)]["cash_projet"] + hz[str(h2)]["equite"])) < 1e-6
    assert abs(r["tri_projet"][f"an{h2}"] - irr(f)) < 1e-12
    assert r["sommaire"]["total_cash_projet_sans_vente"] == sum(
        hz[str(h)]["cash_projet"] for h in (h0, h1, h2)
    )
    # La vue investisseur n'a pas bougé : mêmes clés historiques.
    assert set(r["tri"].keys()) == {"an2", "an7", "an12"}
    assert hz["2"]["cash_investisseur"] <= hz["2"]["cash_projet"]


def test_vue_projet_egale_investisseur_a_100_pct_quand_tout_est_rembourse():
    # À 100 % des parts et capital entièrement remboursé au premier refi,
    # les deux vues coïncident (cash = argent dispo, parts = équité).
    r = compute_tri(**_base(pct=1.0))
    h0 = r["horizons_list"][0]
    assert r["horizons"][str(h0)]["argent_dispo"] >= 300_000.0
    for k in r["tri"]:
        assert abs(r["tri"][k] - r["tri_projet"][k]) < 1e-9
    # À 50 % des parts, le projet rapporte plus que la part de l'investisseur.
    r50 = compute_tri(**_base(pct=0.5))
    assert r50["tri_projet"]["an12"] > r50["tri"]["an12"]


def test_manque_au_refi_est_une_injection_dans_la_vue_projet():
    # Refi trop faible pour rembourser la dette : l'investisseur ne reçoit
    # rien (vue inchangée), le projet doit remettre de l'argent (flux négatif).
    r = compute_tri(**_base(valeur2=900_000.0, rpv_refi=0.5))
    h0 = r["horizons_list"][0]
    hd = r["horizons"][str(h0)]
    assert hd["argent_dispo"] < 0
    assert hd["cash_investisseur"] == 0.0
    assert hd["cash_projet"] < 0
    assert r["flux_projet"][str(h0)][h0] < hd["equite"]


def test_api_tri_renvoie_la_vue_projet(client, auth_headers, run):
    import json
    from app.models.lead_analysis import LeadAnalysis
    from tests.smoke.conftest import TestSessionLocal

    async def _create():
        async with TestSessionLocal() as s:
            rec = LeadAnalysis(
                address="12 rue du TRI projet", city="Montréal", asking_price=1_000_000,
                nb_logements=8, typology_json=json.dumps({"4.5": 8}), revenus_bruts=96_000,
                taxes_municipales=10_000, taxes_scolaires=800, assurances=4_000, energie=0,
                depenses_autres=0, loyers_projetes_json=json.dumps({"4.5": 1400}),
                taux_interet_refi_pct=4.0, tga_pct=4.0, duree_projet_annees=2,
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec.id

    fid = run(_create())
    base = f"/api/v1/lead-analyses/{fid}"
    assert client.post(f"{base}/run-financial-analysis", headers=auth_headers).status_code == 200
    inp = client.get(f"{base}/tri-inputs", headers=auth_headers).json()["inputs"]
    inp["capital"] = 400_000.0
    r = client.post(f"{base}/tri", headers=auth_headers, json=inp)
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d["tri_projet"].keys()) == set(d["tri"].keys())
    for h in d["horizons_list"]:
        assert "cash_projet" in d["horizons"][str(h)]
        assert "patrimoine_projet" in d["horizons"][str(h)]
    assert len(d["flux_projet"][str(d["horizons_list"][-1])]) == d["horizons_list"][-1] + 1
