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

Retour Steven 2026-11-13 : deux adresses → les numéros restent tels
quels (conflit seulement à la même adresse), prix d'achat et hypothèque
saisis en deux moitiés s'additionnent, et une simulation montre la fiche
résultante sans rien écrire.
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
            # Paire à la MÊME adresse : le « 1 » y est un vrai conflit.
            e = Immeuble(name="E (même adresse)", address="5 rue Même", is_active=True)
            f = Immeuble(name="F (même adresse)", address="5, rue  Même", is_active=True)
            emp = User(
                email="smoke-fusion-employe@example.com",
                hashed_password=get_password_hash("Sm0keFusion!42"),
                is_active=True, is_admin=False, role="employee",
                volets_json='["immobilier"]',
            )
            s.add_all([a, b, c, d, e, f, emp])
            await s.flush()
            logs = []
            for num in ("1", "2", "3"):
                logs.append(Logement(immeuble_id=a.id, numero=num, status=LogementStatus.VACANT.value))
                logs.append(Logement(immeuble_id=b.id, numero=num, status=LogementStatus.OCCUPE.value))
            logs.append(Logement(immeuble_id=d.id, numero="101", status=LogementStatus.VACANT.value))
            logs.append(Logement(immeuble_id=e.id, numero="1", status=LogementStatus.VACANT.value))
            logs.append(Logement(immeuble_id=f.id, numero="01", status=LogementStatus.VACANT.value))
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
            # Un prêt réparti en deux moitiés, une par fiche (le « 2 shots »).
            hyp_a = Hypotheque(immeuble_id=a.id, rang=1, preteur="Desjardins", montant_initial=1_000_000, paiement_mensuel=5_800, status="active", notes="Moitié Legendre")
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
                "a": a.id, "b": b.id, "c": c.id, "d": d.id, "e": e.id, "f": f.id,
                "emp": emp.id, "hyp_a": hyp_a.id, "hyp_b": hyp_b.id,
                "bail": bail.id, "lg_b1": lg_b1.id, "ent_a": ent_a.id,
            }

    seed = run(_seed())
    yield seed

    # La base est partagée par toute la suite : on retire les hypothèques
    # restantes pour ne pas gonfler les totaux (prévisionnel, P&L) des
    # tests qui suivent.
    async def _nettoyer() -> None:
        ids = [seed["a"], seed["b"], seed["c"], seed["d"], seed["e"], seed["f"]]
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
    # Deux adresses : les « 1, 2, 3 » de chaque fiche coexistent.
    assert ap["numeros_en_conflit"] == []
    assert ap["prefixe_suggere"] == ""
    assert ap["hypotheques_en_double"] == 1
    assert ap["hypotheques_additionnables"] == 1
    h = ap["hypotheques_source"][0]
    assert h["en_double"] is True
    assert h["additionnable_avec"] == fusion_seed["hyp_a"]
    assert h["montant_additionne"] == 2_000_000.0
    # Prix saisi en deux parts : la somme.
    assert ap["purchase_price_suggere"] == 1_350_000.0


def test_garde_fous(client, auth_headers, emp_headers, fusion_seed):
    a, b = fusion_seed["a"], fusion_seed["b"]
    # Même adresse, même numéro (« 01 » = « 1 ») sans préfixe : 409, rien
    # n'est écrit ; avec un préfixe, la simulation passe.
    e, f = fusion_seed["e"], fusion_seed["f"]
    ap = client.get(f"{IMM}/{e}/fusion/apercu", headers=auth_headers, params={"source_immeuble_id": f}).json()
    assert ap["numeros_en_conflit"] == ["01"] and ap["prefixe_suggere"] == "5-"
    r = client.post(f"{IMM}/{e}/fusion", headers=auth_headers, json={"source_immeuble_id": f})
    assert r.status_code == 409, r.text
    assert "01" in r.json()["detail"]
    r = client.post(f"{IMM}/{e}/fusion/simulation", headers=auth_headers, json={"source_immeuble_id": f})
    assert r.status_code == 409, r.text
    r = client.post(f"{IMM}/{e}/fusion/simulation", headers=auth_headers, json={"source_immeuble_id": f, "prefixe_numeros": "B-"})
    assert r.status_code == 200, r.text
    assert [l["numero"] for l in r.json()["resultat"]["logements"]] == ["1", "B-01"]
    assert client.get(f"{IMM}/{f}", headers=auth_headers).status_code == 200
    # Même immeuble, source inconnue.
    assert client.post(f"{IMM}/{a}/fusion", headers=auth_headers, json={"source_immeuble_id": a}).status_code == 400
    assert client.post(f"{IMM}/{a}/fusion", headers=auth_headers, json={"source_immeuble_id": 99_999_999}).status_code == 404
    # Employé qui ne voit pas la paire C/D : 403.
    r = client.post(f"{IMM}/{fusion_seed['c']}/fusion", headers=emp_headers, json={"source_immeuble_id": fusion_seed["d"]})
    assert r.status_code == 403, r.text


def test_simulation_ne_change_rien(client, auth_headers, fusion_seed, run):
    a, b = fusion_seed["a"], fusion_seed["b"]
    options = {"source_immeuble_id": b, "hypotheques": "additionner", "purchase_price": 1_350_000}
    r = client.post(f"{IMM}/{a}/fusion/simulation", headers=auth_headers, json=options)
    assert r.status_code == 200, r.text
    sim = r.json()
    assert sim["hypotheques_additionnees"] == 1
    fiche = sim["resultat"]
    assert fiche["address"] == "710 rue Legendre"
    assert fiche["address_secondaire"] == "9085 rue Millen"
    assert fiche["purchase_price"] == 1_350_000
    # Adresse principale d'abord, puis l'autre, ordre naturel.
    assert [(l["adresse"], l["numero"]) for l in fiche["logements"]] == [
        ("710 rue Legendre", "1"), ("710 rue Legendre", "2"), ("710 rue Legendre", "3"),
        ("9085 rue Millen", "1"), ("9085 rue Millen", "2"), ("9085 rue Millen", "3"),
    ]
    assert len(fiche["hypotheques"]) == 1
    assert fiche["hypotheques"][0]["montant_initial"] == 2_000_000
    assert fiche["total_hypotheques"] == 2_000_000
    assert fiche["total_paiements_mensuels"] == 11_600

    # Rien n'a été écrit.
    assert client.get(f"{IMM}/{b}", headers=auth_headers).status_code == 200
    assert len(client.get(f"{IMM}/{b}/logements", headers=auth_headers).json()) == 3
    hyps_a = client.get(f"{IMM}/{a}/hypotheques", headers=auth_headers).json()
    assert [h["montant_initial"] for h in hyps_a] == [1_000_000]
    assert client.get(f"{IMM}/{a}", headers=auth_headers).json()["purchase_price"] == 900_000


def test_fusion_millen_dans_legendre(client, auth_headers, fusion_seed, run):
    a, b = fusion_seed["a"], fusion_seed["b"]
    r = client.post(f"{IMM}/{a}/fusion", headers=auth_headers, json={
        "source_immeuble_id": b, "hypotheques": "additionner",
        "purchase_price": 1_350_000,
    })
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["immeuble_supprime_id"] == b
    assert res["hypotheques_exclues"] == 0
    assert res["hypotheques_additionnees"] == 1
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
    # Les numéros restent tels quels ; chaque logement garde son adresse.
    assert sorted((l["adresse"] or "", l["numero"]) for l in logs) == [
        ("", "1"), ("", "2"), ("", "3"),
        ("9085 rue Millen", "1"), ("9085 rue Millen", "2"), ("9085 rue Millen", "3"),
    ]
    # Les deux moitiés du prêt n'en font plus qu'un.
    hyps = client.get(f"{IMM}/{a}/hypotheques", headers=auth_headers).json()
    assert [(h["id"], h["preteur"]) for h in hyps] == [(fusion_seed["hyp_a"], "Desjardins")]
    assert hyps[0]["montant_initial"] == 2_000_000
    assert hyps[0]["paiement_mensuel"] == 11_600
    assert "Moitié Legendre" in hyps[0]["notes"] and f"#{fusion_seed['hyp_b']}" in hyps[0]["notes"]
    # Plus de faux doublons de logements dans le diagnostic.
    doublons = client.get("/api/v1/immobilier/logements/doublons", headers=auth_headers).json()
    assert not [g for g in doublons if g["immeuble_id"] == a]
    # Créer un « 4 » au 9085 Millen reste possible ; un 2e « 1 » au Millen non.
    r = client.post("/api/v1/immobilier/logements", headers=auth_headers, json={"immeuble_id": a, "numero": "1", "adresse": "9085 rue Millen"})
    assert r.status_code == 409, r.text
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
