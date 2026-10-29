"""Smoke — Fusion de deux fiches d'immeuble (retour Steven 2026-10-29).

« Le 710 Legendre et le 9085 Millen ont une hypothèque conjointe, mais le
calcul est en deux coups… C'est un 12 logements avec deux adresses de six
appartements : permettre de fusionner leur fiche, comme un seul
immeuble. »

- aperçu : ce que la source apporterait (logements, baux, hypothèques,
  codes…), numéros en conflit, préfixe suggéré, hypothèques en double ;
- fusion : logements (préfixés, avec leur adresse), baux, hypothèques
  (ou exclues si saisies en double), codes à la suite, affectations
  dédoublonnées, parts de propriété de la cible gardées, adresse
  secondaire, nb de logements et prix d'achat ; la source disparaît ;
- hypothèque conjointe 60/40 entre les deux fiches → redevient simple ;
- garde-fous : conflit de numéros sans préfixe (409), même immeuble
  (400), source inconnue (404), employé qui ne voit pas la source (403).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.security import create_access_token, get_password_hash
from app.models.entreprise import Entreprise
from app.models.immobilier import (
    Bail,
    BailStatus,
    Hypotheque,
    HypothequeImmeuble,
    HypothequeTranche,
    Immeuble,
    ImmeubleCode,
    ImmeubleOwnership,
    Locataire,
    Logement,
    LogementStatus,
)
from app.models.user import User
from app.models.user_immeuble import UserImmeuble
from tests.smoke.conftest import TestSessionLocal

IMM = "/api/v1/immobilier/immeubles"
HYP = "/api/v1/immobilier/hypotheques"


@pytest.fixture(scope="module")
def fusion_seed(run, seeded_users) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            ent_a = Entreprise(name="Legendre Smoke inc.")
            ent_b = Entreprise(name="Millen Smoke inc.")
            s.add_all([ent_a, ent_b])
            await s.flush()
            a = Immeuble(
                name="710 Legendre (fusion)", address="710 rue Legendre",
                city="Montréal", is_active=True, nb_logements=3,
                purchase_price=900_000, annee_construction=1965,
            )
            b = Immeuble(
                name="9085 Millen (fusion)", address="9085 rue Millen",
                city="Montréal", is_active=True, nb_logements=3,
                purchase_price=450_000, matricule="MAT-9085",
            )
            # Paire pour l'hypothèque conjointe 60/40 → simple après fusion.
            c = Immeuble(name="C (fusion conj)", address="1 rue C", is_active=True)
            d = Immeuble(name="D (fusion conj)", address="2 rue D", is_active=True)
            emp = User(
                email="smoke-fusion-employe@example.com",
                hashed_password=get_password_hash("Sm0keFusion!42"),
                is_active=True, is_admin=False, role="employee",
                volets_json='["immobilier"]',
            )
            s.add_all([a, b, c, d, emp])
            await s.flush()
            logs = []
            for num in ("1", "2", "3"):
                logs.append(Logement(immeuble_id=a.id, numero=num, status=LogementStatus.VACANT.value))
                logs.append(Logement(immeuble_id=b.id, numero=num, status=LogementStatus.OCCUPE.value))
            logs.append(Logement(immeuble_id=d.id, numero="101", status=LogementStatus.VACANT.value))
            loc = Locataire(full_name="Locataire Millen", email="loc.millen@example.com")
            s.add_all(logs + [loc])
            await s.flush()
            lg_b1 = next(l for l in logs if l.immeuble_id == b.id and l.numero == "1")
            debut = date.today().replace(day=1) - timedelta(days=200)
            bail = Bail(
                logement_id=lg_b1.id, locataire_id=loc.id, date_debut=debut,
                date_fin=debut + timedelta(days=730), loyer_mensuel=1_100.0,
                status=BailStatus.ACTIF.value,
            )
            # Même hypothèque saisie sur les deux fiches (le « 2 shots »).
            hyp_a = Hypotheque(immeuble_id=a.id, rang=1, preteur="Desjardins", montant_initial=1_000_000, paiement_mensuel=5_800, status="active")
            hyp_b = Hypotheque(immeuble_id=b.id, rang=1, preteur="desjardins ", montant_initial=1_000_000, paiement_mensuel=5_800, status="active")
            codes = [
                ImmeubleCode(immeuble_id=a.id, libelle="Porte avant", code="1234", position=0),
                ImmeubleCode(immeuble_id=b.id, libelle="Porte Millen", code="5678", position=0),
                ImmeubleCode(immeuble_id=b.id, libelle="Lock box Millen", code="9999", position=1),
            ]
            s.add_all([bail, hyp_a, hyp_b] + codes)
            s.add_all([
                ImmeubleOwnership(immeuble_id=a.id, entreprise_id=ent_a.id, ownership_pct=100),
                ImmeubleOwnership(immeuble_id=b.id, entreprise_id=ent_b.id, ownership_pct=100),
                # Employé affecté aux DEUX fiches → une seule ligne après fusion.
                UserImmeuble(user_id=emp.id, immeuble_id=a.id),
                UserImmeuble(user_id=emp.id, immeuble_id=b.id),
            ])
            await s.commit()
            return {
                "a": a.id, "b": b.id, "c": c.id, "d": d.id, "emp": emp.id,
                "bail": bail.id, "lg_b1": lg_b1.id, "ent_a": ent_a.id,
            }

    seed = run(_seed())
    yield seed

    # La base est partagée par toute la suite : on retire les hypothèques
    # restantes pour ne pas gonfler les totaux (prévisionnel, P&L) des
    # tests qui suivent.
    async def _nettoyer() -> None:
        ids = [seed["a"], seed["b"], seed["c"], seed["d"]]
        async with TestSessionLocal() as s:
            hyp_ids = list((await s.execute(
                select(Hypotheque.id).where(Hypotheque.immeuble_id.in_(ids))
            )).scalars())
            if hyp_ids:
                await s.execute(delete(HypothequeImmeuble).where(HypothequeImmeuble.hypotheque_id.in_(hyp_ids)))
                await s.execute(delete(HypothequeTranche).where(HypothequeTranche.hypotheque_id.in_(hyp_ids)))
                await s.execute(delete(Hypotheque).where(Hypotheque.id.in_(hyp_ids)))
            await s.commit()

    run(_nettoyer())


@pytest.fixture(scope="module")
def emp_headers(fusion_seed) -> dict:
    return {"Authorization": f"Bearer {create_access_token(subject=str(fusion_seed['emp']))}"}


def test_apercu_fusion(client, auth_headers, fusion_seed):
    a, b = fusion_seed["a"], fusion_seed["b"]
    r = client.get(f"{IMM}/{a}/fusion/apercu", headers=auth_headers, params={"source_immeuble_id": b})
    assert r.status_code == 200, r.text
    ap = r.json()
    assert ap["cible"]["id"] == a and ap["source"]["id"] == b
    assert ap["source"]["nb_logements"] == 3
    assert ap["a_deplacer"]["logements"] == 3
    assert ap["a_deplacer"]["baux"] == 1
    assert ap["a_deplacer"]["hypothèques"] == 1
    assert ap["a_deplacer"]["codes d'accès"] == 2
    assert ap["a_deplacer"]["affectations d'employés"] == 1
    assert ap["numeros_en_conflit"] == ["1", "2", "3"]
    assert ap["prefixe_suggere"] == "9085-"
    assert ap["hypotheques_en_double"] == 1
    assert ap["hypotheques_source"][0]["en_double"] is True
    assert ap["purchase_price_suggere"] == 1_350_000.0


def test_garde_fous(client, auth_headers, emp_headers, fusion_seed):
    a, b = fusion_seed["a"], fusion_seed["b"]
    # Conflit de numéros sans préfixe : rien n'est écrit.
    r = client.post(f"{IMM}/{a}/fusion", headers=auth_headers, json={"source_immeuble_id": b})
    assert r.status_code == 409, r.text
    assert "1, 2, 3" in r.json()["detail"]
    assert client.get(f"{IMM}/{b}", headers=auth_headers).status_code == 200
    # Même immeuble, source inconnue.
    assert client.post(f"{IMM}/{a}/fusion", headers=auth_headers, json={"source_immeuble_id": a}).status_code == 400
    assert client.post(f"{IMM}/{a}/fusion", headers=auth_headers, json={"source_immeuble_id": 99_999_999}).status_code == 404
    # Employé qui ne voit pas la paire C/D : 403.
    r = client.post(f"{IMM}/{fusion_seed['c']}/fusion", headers=emp_headers, json={"source_immeuble_id": fusion_seed["d"]})
    assert r.status_code == 403, r.text


def test_fusion_millen_dans_legendre(client, auth_headers, fusion_seed, run):
    a, b = fusion_seed["a"], fusion_seed["b"]
    r = client.post(f"{IMM}/{a}/fusion", headers=auth_headers, json={
        "source_immeuble_id": b, "prefixe_numeros": "9085-",
        "exclure_hypotheques": True, "purchase_price": 1_350_000,
    })
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["immeuble_supprime_id"] == b
    assert res["hypotheques_exclues"] == 1
    assert res["deplaces"]["logements"] == 3 and res["deplaces"]["baux"] == 1
    assert res["deplaces"]["codes d'accès"] == 2
    assert res["deplaces"]["affectations d'employés (doublons retirés)"] == 1
    assert "hypothèques" not in res["deplaces"]
    imm = res["immeuble"]
    assert imm["address"] == "710 rue Legendre"
    assert imm["address_secondaire"] == "9085 rue Millen"
    assert imm["nb_logements"] == 6
    assert imm["purchase_price"] == 1_350_000
    assert imm["annee_construction"] == 1965 and imm["matricule"] == "MAT-9085"

    # La source n'existe plus ; la cible porte tout.
    assert client.get(f"{IMM}/{b}", headers=auth_headers).status_code == 404
    logs = client.get(f"{IMM}/{a}/logements", headers=auth_headers).json()
    par_num = {l["numero"]: l for l in logs}
    assert set(par_num) == {"1", "2", "3", "9085-1", "9085-2", "9085-3"}
    assert par_num["9085-1"]["adresse"] == "9085 rue Millen"
    assert par_num["1"]["adresse"] is None
    hyps = client.get(f"{IMM}/{a}/hypotheques", headers=auth_headers).json()
    assert [h["preteur"] for h in hyps] == ["Desjardins"]
    codes = client.get(f"{IMM}/{a}/codes", headers=auth_headers).json()
    assert [(c["libelle"], c["position"]) for c in codes] == [
        ("Porte avant", 0), ("Porte Millen", 1), ("Lock box Millen", 2),
    ]

    async def _verif() -> None:
        async with TestSessionLocal() as s:
            bail = await s.get(Bail, fusion_seed["bail"])
            lg = await s.get(Logement, bail.logement_id)
            assert lg.id == fusion_seed["lg_b1"] and lg.immeuble_id == a
            affect = (await s.execute(select(UserImmeuble).where(UserImmeuble.user_id == fusion_seed["emp"]))).scalars().all()
            assert [u.immeuble_id for u in affect] == [a]
            parts = (await s.execute(select(ImmeubleOwnership).where(ImmeubleOwnership.immeuble_id == a))).scalars().all()
            assert [(p.entreprise_id, float(p.ownership_pct)) for p in parts] == [(fusion_seed["ent_a"], 100.0)]
            assert (await s.execute(select(Hypotheque).where(Hypotheque.immeuble_id == b))).scalars().all() == []
            assert (await s.execute(select(ImmeubleOwnership).where(ImmeubleOwnership.immeuble_id == b))).scalars().all() == []

    run(_verif())


def test_fusion_hypotheque_conjointe_redevient_simple(client, auth_headers, fusion_seed, run):
    c, d = fusion_seed["c"], fusion_seed["d"]
    r = client.post(HYP, headers=auth_headers, json={
        "immeuble_id": c, "preteur": "BNC", "montant_initial": 500_000,
        "taux_pct": 5, "amortissement_mois": 300, "composition_interets": "semi",
        "immeubles": [{"immeuble_id": c, "part_pct": 60}, {"immeuble_id": d, "part_pct": 40}],
    })
    assert r.status_code == 201, r.text
    hyp_id = r.json()["id"]
    ap = client.get(f"{IMM}/{c}/fusion/apercu", headers=auth_headers, params={"source_immeuble_id": d}).json()
    assert ap["numeros_en_conflit"] == [] and ap["prefixe_suggere"] == ""
    assert ap["a_deplacer"]["parts d'hypothèque conjointe"] == 1
    r = client.post(f"{IMM}/{c}/fusion", headers=auth_headers, json={"source_immeuble_id": d})
    assert r.status_code == 200, r.text
    hyps = client.get(f"{IMM}/{c}/hypotheques", headers=auth_headers).json()
    assert len(hyps) == 1 and hyps[0]["id"] == hyp_id
    assert hyps[0]["conjointe"] is False and hyps[0]["part_pct"] == 100.0
    assert hyps[0]["balance_part"] == hyps[0]["balance_effective"]

    async def _verif() -> None:
        async with TestSessionLocal() as s:
            rows = (await s.execute(select(HypothequeImmeuble).where(HypothequeImmeuble.hypotheque_id == hyp_id))).scalars().all()
            assert rows == []
            assert await s.get(Immeuble, d) is None

    run(_verif())
