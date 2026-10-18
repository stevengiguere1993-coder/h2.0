"""Smoke — Hypothèque CONJOINTE entre plusieurs immeubles (Steven
2026-10-06 : « le 710 Legendre et le 9085 Millen ont une hypothèque
conjointe, mais ici le calcul est en 2 shots »).

- une hypothèque peut couvrir plusieurs immeubles, chacun avec sa PART
  en % (total 100, immeuble principal inclus) ;
- chaque immeuble ne porte que sa part (fiche, financials, P&L,
  prévisionnel, équité investisseur) — la dette n'est plus comptée deux
  fois, et aucun des deux immeubles n'affiche une dette à 0 ;
- validation de la répartition, modification, retour à une hypothèque
  simple, ré-attachement quand l'immeuble principal sort de la liste ;
- cliquet IA + liste MCP « hypotheques ».
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.entreprise import Entreprise
from app.models.immobilier import (
    HypothequeImmeuble,
    Immeuble,
    ImmeubleOwnership,
)
from app.services.hypotheque_calc import paiement_mensuel_calcule
from tests.smoke.conftest import TestSessionLocal

IMM = "/api/v1/immobilier/immeubles"
HYP = "/api/v1/immobilier/hypotheques"
IDS: dict = {}

#: Paiement mensuel attendu (1 000 000 $, 5 %, 25 ans, composition semi).
PMT = paiement_mensuel_calcule(
    taux_pct=5.0, amortissement_mois=300, principal=1_000_000.0, composition="semi"
)


def _proche(a, b, tol=0.05):
    return abs(float(a) - float(b)) <= tol


@pytest.fixture(scope="module")
def conj_seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            ent = Entreprise(name="Gestion Smoke Conjointe inc.")
            s.add(ent)
            await s.flush()
            a = Immeuble(name="710 Legendre (conj)", address="710 rue Legendre", city="Montréal", is_active=True)
            b = Immeuble(name="9085 Millen (conj)", address="9085 rue Millen", city="Montréal", is_active=True)
            c = Immeuble(name="Autre immeuble (conj)", address="1 rue Ailleurs", city="Montréal", is_active=True)
            s.add_all([a, b, c])
            await s.flush()
            s.add_all([
                ImmeubleOwnership(immeuble_id=a.id, entreprise_id=ent.id, ownership_pct=100),
                ImmeubleOwnership(immeuble_id=b.id, entreprise_id=ent.id, ownership_pct=100),
            ])
            await s.commit()
            return {"ent": ent.id, "a": a.id, "b": b.id, "c": c.id}

    return run(_seed())


def test_creer_hypotheque_conjointe_repartie(client, auth_headers, conj_seed):
    a, b, c = conj_seed["a"], conj_seed["b"], conj_seed["c"]
    r = client.post(HYP, headers=auth_headers, json={
        "immeuble_id": a, "preteur": "Desjardins", "montant_initial": 1_000_000,
        "taux_pct": 5, "amortissement_mois": 300, "composition_interets": "semi",
        "immeubles": [{"immeuble_id": a, "part_pct": 60}, {"immeuble_id": b, "part_pct": 40}],
    })
    assert r.status_code == 201, r.text
    h = r.json()
    IDS["hyp"] = h["id"]
    assert h["immeuble_id"] == a and h["conjointe"] is True
    assert {(x["immeuble_id"], x["part_pct"]) for x in h["immeubles"]} == {(a, 60.0), (b, 40.0)}
    assert {x["immeuble_name"] for x in h["immeubles"]} == {"710 Legendre (conj)", "9085 Millen (conj)"}
    # Contexte par défaut = immeuble principal : 60 % de 1 M$.
    assert h["part_pct"] == 60.0 and h["balance_effective"] == 1_000_000.0
    assert h["balance_part"] == 600_000.0 and h["montant_initial_part"] == 600_000.0
    assert _proche(h["paiement_mensuel"], PMT) and _proche(h["paiement_mensuel_part"], PMT * 0.6)

    # Vue depuis chaque immeuble : même hypothèque, part différente.
    ra = client.get(f"{IMM}/{a}/hypotheques", headers=auth_headers).json()
    rb = client.get(f"{IMM}/{b}/hypotheques", headers=auth_headers).json()
    assert [x["id"] for x in ra] == [h["id"]] and ra[0]["part_pct"] == 60.0
    assert [x["id"] for x in rb] == [h["id"]] and rb[0]["part_pct"] == 40.0
    assert rb[0]["balance_part"] == 400_000.0 and rb[0]["immeuble_id"] == a
    assert _proche(rb[0]["paiement_mensuel_part"], PMT * 0.4)
    # Un immeuble non couvert ne la voit pas.
    assert client.get(f"{IMM}/{c}/hypotheques", headers=auth_headers).json() == []


def test_chaque_immeuble_porte_sa_part(client, auth_headers, conj_seed, run):
    a, b = conj_seed["a"], conj_seed["b"]
    # Financials de la fiche : balance et paiement = la part seulement.
    fa = client.get(f"{IMM}/{a}/financials", headers=auth_headers).json()
    fb = client.get(f"{IMM}/{b}/financials", headers=auth_headers).json()
    assert fa["balance_hypothecaire"] == 600_000.0 and fb["balance_hypothecaire"] == 400_000.0
    assert _proche(fa["paiement_hypotheque_mensuel"], PMT * 0.6)
    assert _proche(fb["paiement_hypotheque_mensuel"], PMT * 0.4)

    # P&L : la dette annuelle est répartie, le total vaut UNE hypothèque.
    pnl = client.get("/api/v1/immobilier/finances/pnl", headers=auth_headers).json()
    rows = {r["immeuble_id"]: r for r in pnl["rows"]}
    assert _proche(rows[a]["dette_annuelle"], PMT * 12 * 0.6, 0.6)
    assert _proche(rows[b]["dette_annuelle"], PMT * 12 * 0.4, 0.6)
    assert _proche(rows[a]["dette_annuelle"] + rows[b]["dette_annuelle"], PMT * 12, 0.6)

    # Prévisionnel : les deux immeubles = 100 % ; un seul = sa part.
    prev = client.get("/api/v1/immobilier/finances/previsionnel", headers=auth_headers, params={"mois": 3}).json()
    assert _proche(prev["hypotheque_mensuelle"], PMT, 0.1)
    prev_b = client.get("/api/v1/immobilier/finances/previsionnel", headers=auth_headers,
                        params={"mois": 3, "immeuble_id": b}).json()
    assert _proche(prev_b["hypotheque_mensuelle"], PMT * 0.4, 0.1)

    # Équité investisseur (snapshot de la compagnie qui détient les deux) :
    # la dette totale est 1 M$, pas 2 M$ ; chaque immeuble porte sa part.
    from app.services.invest_portfolio import entreprise_snapshot

    async def _snap():
        async with TestSessionLocal() as s:
            return await entreprise_snapshot(s, conj_seed["ent"])

    snap = run(_snap())
    assert snap["hypotheque_totale"] == 1_000_000.0
    par_imm = {i["immeuble_id"]: i for i in snap["immeubles"]}
    assert par_imm[a]["hypotheque_balance"] == 600_000.0
    assert par_imm[b]["hypotheque_balance"] == 400_000.0
    det = par_imm[b]["hypotheques"][0]
    assert det["conjointe"] is True and det["part_pct"] == 40.0
    assert det["balance"] == 400_000.0 and det["balance_totale"] == 1_000_000.0
    assert _proche(snap["paiement_hypo_mensuel"], PMT)


def test_repartition_validee(client, auth_headers, conj_seed):
    a, b = conj_seed["a"], conj_seed["b"]
    base = {"immeuble_id": a, "preteur": "Test", "montant_initial": 100}
    # Total ≠ 100.
    r = client.post(HYP, headers=auth_headers, json={**base, "immeubles": [{"immeuble_id": a, "part_pct": 60}, {"immeuble_id": b, "part_pct": 30}]})
    assert r.status_code == 422 and "100" in r.text
    # Immeuble en double.
    assert client.post(HYP, headers=auth_headers, json={**base, "immeubles": [{"immeuble_id": a, "part_pct": 50}, {"immeuble_id": a, "part_pct": 50}]}).status_code == 422
    # Immeuble inconnu.
    assert client.post(HYP, headers=auth_headers, json={**base, "immeubles": [{"immeuble_id": a, "part_pct": 50}, {"immeuble_id": 999999, "part_pct": 50}]}).status_code == 422
    # Une seule ligne = pas une conjointe.
    assert client.post(HYP, headers=auth_headers, json={**base, "immeubles": [{"immeuble_id": a, "part_pct": 100}]}).status_code == 422
    # Part nulle.
    assert client.post(HYP, headers=auth_headers, json={**base, "immeubles": [{"immeuble_id": a, "part_pct": 0}, {"immeuble_id": b, "part_pct": 100}]}).status_code == 422
    # Rien n'a été créé en douce.
    assert len(client.get(f"{IMM}/{a}/hypotheques", headers=auth_headers).json()) == 1


def test_modifier_la_repartition(client, auth_headers, conj_seed):
    a, b, c = conj_seed["a"], conj_seed["b"], conj_seed["c"]
    hid = IDS["hyp"]
    # 50 / 50.
    r = client.patch(f"{HYP}/{hid}", headers=auth_headers, json={"immeubles": [{"immeuble_id": a, "part_pct": 50}, {"immeuble_id": b, "part_pct": 50}]})
    assert r.status_code == 200, r.text
    assert r.json()["part_pct"] == 50.0 and r.json()["balance_part"] == 500_000.0
    assert client.get(f"{IMM}/{b}/hypotheques", headers=auth_headers).json()[0]["part_pct"] == 50.0
    # Un PATCH sans `immeubles` ne touche pas la répartition.
    r = client.patch(f"{HYP}/{hid}", headers=auth_headers, json={"notes": "terme à renégocier"})
    assert r.status_code == 200 and r.json()["conjointe"] is True and len(r.json()["immeubles"]) == 2
    # Répartition invalide en modification → refus, l'ancienne reste.
    assert client.patch(f"{HYP}/{hid}", headers=auth_headers, json={"immeubles": [{"immeuble_id": a, "part_pct": 80}, {"immeuble_id": b, "part_pct": 30}]}).status_code == 422
    assert client.get(f"{IMM}/{a}/hypotheques", headers=auth_headers).json()[0]["part_pct"] == 50.0
    # L'immeuble principal sort de la liste → l'hypothèque est ré-attachée.
    r = client.patch(f"{HYP}/{hid}", headers=auth_headers, json={"immeubles": [{"immeuble_id": b, "part_pct": 70}, {"immeuble_id": c, "part_pct": 30}]})
    assert r.status_code == 200, r.text
    assert r.json()["immeuble_id"] == b and r.json()["part_pct"] == 70.0
    assert client.get(f"{IMM}/{a}/hypotheques", headers=auth_headers).json() == []
    assert client.get(f"{IMM}/{c}/hypotheques", headers=auth_headers).json()[0]["part_pct"] == 30.0
    assert client.get(f"{IMM}/{a}/financials", headers=auth_headers).json()["balance_hypothecaire"] == 0.0
    # Retour à une hypothèque simple : 100 % sur son immeuble (b).
    r = client.patch(f"{HYP}/{hid}", headers=auth_headers, json={"immeubles": []})
    assert r.status_code == 200, r.text
    assert r.json()["conjointe"] is False and r.json()["immeubles"] == [] and r.json()["part_pct"] == 100.0
    assert r.json()["balance_part"] == 1_000_000.0
    assert client.get(f"{IMM}/{c}/hypotheques", headers=auth_headers).json() == []
    assert client.get(f"{IMM}/{b}/financials", headers=auth_headers).json()["balance_hypothecaire"] == 1_000_000.0


def test_hypotheque_simple_inchangee(client, auth_headers, conj_seed):
    c = conj_seed["c"]
    r = client.post(HYP, headers=auth_headers, json={"immeuble_id": c, "preteur": "BNC", "montant_initial": 250_000, "balance_actuelle": 200_000})
    assert r.status_code == 201, r.text
    h = r.json()
    assert h["conjointe"] is False and h["immeubles"] == [] and h["part_pct"] == 100.0
    assert h["balance_effective"] == 200_000.0 and h["balance_part"] == 200_000.0
    assert h["montant_initial_part"] == 250_000.0
    IDS["simple"] = h["id"]


def test_suppression_retire_la_repartition(client, auth_headers, conj_seed, run):
    a, b = conj_seed["a"], conj_seed["b"]
    hid = IDS["hyp"]
    assert client.patch(f"{HYP}/{hid}", headers=auth_headers, json={"immeubles": [{"immeuble_id": a, "part_pct": 25}, {"immeuble_id": b, "part_pct": 75}]}).status_code == 200
    assert client.delete(f"{HYP}/{hid}", headers=auth_headers).status_code == 204

    async def _n():
        async with TestSessionLocal() as s:
            return (await s.execute(select(func.count(HypothequeImmeuble.id)).where(HypothequeImmeuble.hypotheque_id == hid))).scalar_one()

    assert run(_n()) == 0
    assert client.get(f"{IMM}/{a}/hypotheques", headers=auth_headers).json() == []
    assert client.get(f"{IMM}/{b}/hypotheques", headers=auth_headers).json() == []


def test_cliquet_et_mcp_hypotheques(client, api_key_headers, conj_seed):
    from app.core.api_ia_couverture import TABLES_COUVERTES

    assert "imm_hypotheque_immeubles" in TABLES_COUVERTES
    r = client.get("/api/v1/activity/entities/hypotheques", headers=api_key_headers)
    assert r.status_code == 200, r.text
    assert r.json()["pole"] == "immobilier" and r.json()["count"] >= 1
    item = next(x for x in r.json()["items"] if x["id"] == IDS["simple"])
    assert item["entity_type"] == "imm_hypotheque" and item["preteur"] == "BNC"
    assert item["immeuble_id"] == conj_seed["c"] and item["balance_actuelle"] == 200_000.0
    r = client.get(f"/api/v1/activity/entities/hypotheque/{IDS['simple']}", headers=api_key_headers)
    assert r.status_code == 200, r.text
    assert r.json()["montant_initial"] == 250_000.0
