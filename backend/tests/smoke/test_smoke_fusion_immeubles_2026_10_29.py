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

Retour Steven 2026-11-13 : deux adresses → chaque logement garde son
adresse (conflit seulement à la même adresse), le préfixe PROPOSÉ est le
numéro civique de la fiche absorbée (« 9085- » pour les logements du 9085
Millen, jamais celui de l'autre fiche) avec un préfixe facultatif pour la
fiche gardée, prix d'achat et hypothèque saisis en deux moitiés
s'additionnent, et une simulation montre la fiche résultante sans rien
écrire.

Même jour, après la fusion du 9085 Millen / 710 Legendre : « la valeur
actuelle n'est pas bonne » — les évaluations de même type et de même date
(chaque fiche en portait la moitié) s'additionnent, une seule reste « de
référence » ; « l'adresse dans le haut devrait être présentée 9085 Millen
/ 710 Legendre, Montréal » — le nom automatique porte les deux adresses ;
« dans la modification je devrais être en mesure de modifier la valeur »
— ``valeur_actuelle`` sur la modification de l'immeuble.
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
    Evaluation,
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
from app.services.immeuble_nom import (
    adresse_courte,
    nom_automatique,
    nom_est_automatique,
)
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
            # Paire au nom AUTOMATIQUE (« adresse, ville ») : le titre de la
            # fiche fusionnée porte les deux adresses.
            g = Immeuble(
                name="9085, Avenue Millen, Montréal", address="9085, Avenue Millen",
                city="Montréal", is_active=True,
            )
            h = Immeuble(
                name="710, Rue Legendre Est, Montréal", address="710, Rue Legendre Est",
                city="Montréal", is_active=True,
            )
            s.add_all([a, b, c, d, e, f, g, h, emp])
            await s.flush()
            # La même évaluation portée en deux moitiés (une par fiche), les
            # deux « de référence » ; plus une évaluation propre au Millen.
            from datetime import datetime, timezone

            maintenant = datetime.now(timezone.utc)
            evals = [
                Evaluation(immeuble_id=a.id, kind="appraisal", valeur=500_000, taux_cap=5.25, date_evaluation=date(2025, 1, 27), is_reference=True, notes="Moitié Legendre", created_at=maintenant),
                Evaluation(immeuble_id=b.id, kind="appraisal", valeur=500_000, taux_cap=5.25, date_evaluation=date(2025, 1, 27), is_reference=True, created_at=maintenant),
                Evaluation(immeuble_id=a.id, kind="municipale", valeur=300_000, date_evaluation=date(2026, 1, 1), created_at=maintenant),
                Evaluation(immeuble_id=b.id, kind="municipale", valeur=300_000, date_evaluation=date(2026, 1, 1), created_at=maintenant),
                Evaluation(immeuble_id=b.id, kind="marchande", valeur=400_000, date_evaluation=date(2024, 5, 1), created_at=maintenant),
            ]
            s.add_all(evals)
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
                "g": g.id, "h": h.id,
                "eval_a": evals[0].id, "eval_b": evals[1].id,
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
    # Deux adresses : aucun conflit bloquant, mais les deux fiches portent
    # « 1, 2, 3 » → préfixe proposé = numéro civique de la fiche ABSORBÉE.
    assert ap["numeros_en_conflit"] == []
    assert ap["numeros_communs"] == ["1", "2", "3"]
    assert ap["numeros_source"] == ["1", "2", "3"]
    assert ap["prefixe_suggere"] == "9085-"
    assert ap["prefixe_cible_suggere"] == "710-"
    assert ap["hypotheques_en_double"] == 1
    assert ap["hypotheques_additionnables"] == 1
    h = ap["hypotheques_source"][0]
    assert h["en_double"] is True
    assert h["additionnable_avec"] == fusion_seed["hyp_a"]
    assert h["montant_additionne"] == 2_000_000.0
    # Prix saisi en deux parts : la somme.
    assert ap["purchase_price_suggere"] == 1_350_000.0
    # Évaluations : même type et même date des deux côtés = deux parts.
    assert ap["a_deplacer"]["évaluations"] == 3
    assert ap["evaluations_additionnables"] == 2
    paires = {e["kind"]: e for e in ap["evaluations_source"]}
    assert paires["appraisal"]["additionnable_avec"] == fusion_seed["eval_a"]
    assert paires["appraisal"]["valeur_additionnee"] == 1_000_000.0
    assert paires["municipale"]["valeur_additionnee"] == 600_000.0
    assert paires["marchande"]["additionnable_avec"] is None
    # Nom personnalisé : gardé.
    assert ap["nom_suggere"] == "710 Legendre (fusion)"


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
    # Sans préfixe : permis (adresses différentes), numéros tels quels.
    r = client.post(f"{IMM}/{a}/fusion/simulation", headers=auth_headers, json={"source_immeuble_id": b})
    assert r.status_code == 200, r.text
    assert [(l["adresse"], l["numero"]) for l in r.json()["resultat"]["logements"]] == [
        ("710 rue Legendre", "1"), ("710 rue Legendre", "2"), ("710 rue Legendre", "3"),
        ("9085 rue Millen", "1"), ("9085 rue Millen", "2"), ("9085 rue Millen", "3"),
    ]
    # Préfixe sur les deux fiches : chacune le sien.
    r = client.post(f"{IMM}/{a}/fusion/simulation", headers=auth_headers, json={
        "source_immeuble_id": b, "prefixe_numeros": "9085-", "prefixe_numeros_cible": "710-",
    })
    assert r.status_code == 200, r.text
    assert [(l["adresse"], l["numero"]) for l in r.json()["resultat"]["logements"]] == [
        ("710 rue Legendre", "710-1"), ("710 rue Legendre", "710-2"), ("710 rue Legendre", "710-3"),
        ("9085 rue Millen", "9085-1"), ("9085 rue Millen", "9085-2"), ("9085 rue Millen", "9085-3"),
    ]
    assert r.json()["deplaces"]["logements de la fiche gardée renumérotés"] == 3

    options = {
        "source_immeuble_id": b, "prefixe_numeros": "9085-",
        "hypotheques": "additionner", "purchase_price": 1_350_000,
    }
    r = client.post(f"{IMM}/{a}/fusion/simulation", headers=auth_headers, json=options)
    assert r.status_code == 200, r.text
    sim = r.json()
    assert sim["hypotheques_additionnees"] == 1
    fiche = sim["resultat"]
    assert fiche["address"] == "710 rue Legendre"
    assert fiche["address_secondaire"] == "9085 rue Millen"
    assert fiche["purchase_price"] == 1_350_000
    # Adresse principale d'abord, puis l'autre, ordre naturel ; les
    # logements absorbés portent LEUR numéro civique et gardent leur adresse.
    assert [(l["adresse"], l["numero"]) for l in fiche["logements"]] == [
        ("710 rue Legendre", "1"), ("710 rue Legendre", "2"), ("710 rue Legendre", "3"),
        ("9085 rue Millen", "9085-1"), ("9085 rue Millen", "9085-2"), ("9085 rue Millen", "9085-3"),
    ]
    assert len(fiche["hypotheques"]) == 1
    assert fiche["hypotheques"][0]["montant_initial"] == 2_000_000
    assert fiche["total_hypotheques"] == 2_000_000
    assert fiche["total_paiements_mensuels"] == 11_600
    # Évaluations transférées telles quelles (défaut) : les deux moitiés
    # restent, mais UNE seule référence — celle de la fiche gardée.
    assert sim["evaluations_additionnees"] == 0
    assert fiche["valeur_actuelle"] == 500_000 and fiche["valeur_municipale"] == 300_000
    assert [e["id"] for e in fiche["evaluations"] if e["is_reference"]] == [fusion_seed["eval_a"]]
    assert len(fiche["evaluations"]) == 5
    # Additionnées : la valeur du bâtiment est la somme des deux parts.
    r = client.post(f"{IMM}/{a}/fusion/simulation", headers=auth_headers, json={**options, "evaluations": "additionner"})
    assert r.status_code == 200, r.text
    sim = r.json()
    assert sim["evaluations_additionnees"] == 2 and sim["evaluations_exclues"] == 0
    assert sim["resultat"]["valeur_actuelle"] == 1_000_000
    assert sim["resultat"]["valeur_municipale"] == 600_000
    assert sorted((e["kind"], e["valeur"], e["is_reference"]) for e in sim["resultat"]["evaluations"]) == [
        ("appraisal", 1_000_000.0, True), ("marchande", 400_000.0, False), ("municipale", 600_000.0, False),
    ]
    # Saisies en double : celle de la fiche gardée reste seule.
    r = client.post(f"{IMM}/{a}/fusion/simulation", headers=auth_headers, json={**options, "evaluations": "exclure"})
    assert r.status_code == 200, r.text
    sim = r.json()
    assert sim["evaluations_exclues"] == 2 and sim["evaluations_additionnees"] == 0
    assert sim["resultat"]["valeur_actuelle"] == 500_000
    assert len(sim["resultat"]["evaluations"]) == 3
    # Nom choisi dans la fenêtre.
    r = client.post(f"{IMM}/{a}/fusion/simulation", headers=auth_headers, json={**options, "name": "  Le Legendre-Millen "})
    assert r.json()["resultat"]["name"] == "Le Legendre-Millen"

    # Rien n'a été écrit.
    assert client.get(f"{IMM}/{b}", headers=auth_headers).status_code == 200
    assert len(client.get(f"{IMM}/{b}/logements", headers=auth_headers).json()) == 3
    hyps_a = client.get(f"{IMM}/{a}/hypotheques", headers=auth_headers).json()
    assert [h["montant_initial"] for h in hyps_a] == [1_000_000]
    fiche_a = client.get(f"{IMM}/{a}", headers=auth_headers).json()
    assert fiche_a["purchase_price"] == 900_000 and fiche_a["name"] == "710 Legendre (fusion)"
    assert [l["numero"] for l in client.get(f"{IMM}/{a}/logements", headers=auth_headers).json()] == ["1", "2", "3"]
    evals_a = client.get(f"{IMM}/{a}/evaluations", headers=auth_headers).json()
    assert sorted((e["kind"], e["valeur"]) for e in evals_a) == [("appraisal", 500_000.0), ("municipale", 300_000.0)]
    assert len(client.get(f"{IMM}/{b}/evaluations", headers=auth_headers).json()) == 3


def test_fusion_millen_dans_legendre(client, auth_headers, fusion_seed, run):
    a, b = fusion_seed["a"], fusion_seed["b"]
    r = client.post(f"{IMM}/{a}/fusion", headers=auth_headers, json={
        "source_immeuble_id": b, "prefixe_numeros": "9085-",
        "hypotheques": "additionner", "evaluations": "additionner",
        "purchase_price": 1_350_000,
    })
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["evaluations_additionnees"] == 2
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
    # Les logements du 9085 Millen portent « 9085- » et gardent leur
    # adresse ; ceux de la fiche gardée ne changent pas.
    assert sorted((l["adresse"] or "", l["numero"]) for l in logs) == [
        ("", "1"), ("", "2"), ("", "3"),
        ("9085 rue Millen", "9085-1"), ("9085 rue Millen", "9085-2"), ("9085 rue Millen", "9085-3"),
    ]
    # Les deux moitiés du prêt n'en font plus qu'un.
    hyps = client.get(f"{IMM}/{a}/hypotheques", headers=auth_headers).json()
    assert [(h["id"], h["preteur"]) for h in hyps] == [(fusion_seed["hyp_a"], "Desjardins")]
    assert hyps[0]["montant_initial"] == 2_000_000
    assert hyps[0]["paiement_mensuel"] == 11_600
    assert "Moitié Legendre" in hyps[0]["notes"] and f"#{fusion_seed['hyp_b']}" in hyps[0]["notes"]
    assert "(desjardins, 1 000 000,00 $)" in hyps[0]["notes"]
    # Les deux moitiés d'évaluation n'en font plus qu'une, une seule
    # référence, et la fiche affiche la valeur du bâtiment complet.
    evals = client.get(f"{IMM}/{a}/evaluations", headers=auth_headers).json()
    assert sorted((e["kind"], e["valeur"], e["is_reference"]) for e in evals) == [
        ("appraisal", 1_000_000.0, True), ("marchande", 400_000.0, False), ("municipale", 600_000.0, False),
    ]
    agreee = next(e for e in evals if e["kind"] == "appraisal")
    assert agreee["id"] == fusion_seed["eval_a"] and agreee["taux_cap"] == 5.25
    assert "Moitié Legendre" in agreee["notes"] and f"#{fusion_seed['eval_b']}" in agreee["notes"]
    assert "500 000,00 $ + 500 000,00 $" in agreee["notes"]
    fin = client.get(f"{IMM}/{a}/financials", headers=auth_headers).json()
    assert fin["valeur_actuelle"] == 1_000_000 and fin["valeur_municipale"] == 600_000
    # Plus de faux doublons de logements dans le diagnostic.
    doublons = client.get("/api/v1/immobilier/logements/doublons", headers=auth_headers).json()
    assert not [g for g in doublons if g["immeuble_id"] == a]
    # Un 2e « 9085-1 » au Millen est refusé ; un « 1 » au Millen reste possible
    # (même numéro que le « 1 » du Legendre, mais autre adresse).
    r = client.post("/api/v1/immobilier/logements", headers=auth_headers, json={"immeuble_id": a, "numero": "9085-1", "adresse": "9085 rue Millen"})
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


def test_nom_deux_adresses():
    # Forme courte : numéro civique + nom de la voie.
    assert adresse_courte("9085, Avenue Millen") == "9085 Millen"
    assert adresse_courte("710, Rue Legendre Est") == "710 Legendre"
    assert adresse_courte("93, Avenue de l'Hôtel-Dieu") == "93 Hôtel-Dieu"
    assert adresse_courte("6646 Av. Des Érables") == "6646 Érables"
    assert adresse_courte("957-978, Place Sapinière") == "957-978 Sapinière"
    assert adresse_courte("1 - 5 Elgin") == "1-5 Elgin"
    assert adresse_courte("1660 Saint-Clément") == "1660 Saint-Clément"
    assert adresse_courte("125, 12e Avenue") == "125 12e Avenue"
    assert adresse_courte("Chemin du Lac") == "Chemin du Lac"
    # Une adresse : « adresse, ville » comme avant ; plusieurs : toutes.
    assert nom_automatique("9085, Avenue Millen", "Montréal") == "9085, Avenue Millen, Montréal"
    assert (
        nom_automatique("9085, Avenue Millen", "Montréal", "710, Rue Legendre Est")
        == "9085 Millen / 710 Legendre, Montréal"
    )
    assert (
        nom_automatique("1 rue A", None, "2 rue B · 3 rue C") == "1 A / 2 B / 3 C"
    )
    # Un nom qui n'est que l'adresse peut suivre ; un nom choisi, jamais.
    assert nom_est_automatique("9085, avenue Millen, Montréal", "9085, Avenue Millen", "Montréal")
    assert nom_est_automatique("9085 Millen / 710 Legendre, Montréal", "9085, Avenue Millen", "Montréal", "710, Rue Legendre Est")
    assert nom_est_automatique("", "9085, Avenue Millen", "Montréal")
    assert not nom_est_automatique("Le Millen", "9085, Avenue Millen", "Montréal")


def test_fusion_nom_deux_adresses(client, auth_headers, fusion_seed):
    g, h = fusion_seed["g"], fusion_seed["h"]
    ap = client.get(f"{IMM}/{g}/fusion/apercu", headers=auth_headers, params={"source_immeuble_id": h}).json()
    assert ap["nom_suggere"] == "9085 Millen / 710 Legendre, Montréal"
    assert ap["evaluations_source"] == [] and ap["evaluations_additionnables"] == 0
    r = client.post(f"{IMM}/{g}/fusion/simulation", headers=auth_headers, json={"source_immeuble_id": h})
    assert r.status_code == 200, r.text
    assert r.json()["resultat"]["name"] == "9085 Millen / 710 Legendre, Montréal"
    assert r.json()["resultat"]["valeur_actuelle"] is None
    assert client.get(f"{IMM}/{g}", headers=auth_headers).json()["name"] == "9085, Avenue Millen, Montréal"
    r = client.post(f"{IMM}/{g}/fusion", headers=auth_headers, json={"source_immeuble_id": h})
    assert r.status_code == 200, r.text
    imm = r.json()["immeuble"]
    assert imm["name"] == "9085 Millen / 710 Legendre, Montréal"
    assert imm["address"] == "9085, Avenue Millen"
    assert imm["address_secondaire"] == "710, Rue Legendre Est"


def test_modifier_immeuble_nom_et_valeur(client, auth_headers, fusion_seed):
    """« Modifier l'immeuble » : le nom automatique suit les adresses, et
    la valeur actuelle se saisit directement."""
    g = fusion_seed["g"]
    # Adresse secondaire retirée : le nom automatique revient à l'adresse.
    r = client.patch(f"{IMM}/{g}", headers=auth_headers, json={"address_secondaire": None})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "9085, Avenue Millen, Montréal"
    # Remise (écran : tous les champs envoyés, nom inchangé) : il la suit.
    r = client.patch(f"{IMM}/{g}", headers=auth_headers, json={
        "name": "9085, Avenue Millen, Montréal", "address": "9085, Avenue Millen",
        "city": "Montréal", "address_secondaire": "710, Rue Legendre Est",
    })
    assert r.json()["name"] == "9085 Millen / 710 Legendre, Montréal"
    # Nom personnalisé : gardé, même si l'adresse secondaire change.
    r = client.patch(f"{IMM}/{g}", headers=auth_headers, json={"name": "Le Millen"})
    assert r.json()["name"] == "Le Millen"
    r = client.patch(f"{IMM}/{g}", headers=auth_headers, json={"name": "Le Millen", "address_secondaire": "712, Rue Legendre Est"})
    assert r.json()["name"] == "Le Millen" and r.json()["address_secondaire"] == "712, Rue Legendre Est"
    # Nom vidé (« Laisser vide = adresse ») : le nom automatique.
    r = client.patch(f"{IMM}/{g}", headers=auth_headers, json={"name": None, "address_secondaire": "710, Rue Legendre Est"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "9085 Millen / 710 Legendre, Montréal"

    # Valeur actuelle : aucune évaluation → une évaluation du jour, de référence.
    assert client.get(f"{IMM}/{g}/financials", headers=auth_headers).json()["valeur_actuelle"] is None
    r = client.patch(f"{IMM}/{g}", headers=auth_headers, json={"valeur_actuelle": 3_000_000})
    assert r.status_code == 200, r.text
    evals = client.get(f"{IMM}/{g}/evaluations", headers=auth_headers).json()
    assert [(e["kind"], e["valeur"], e["is_reference"]) for e in evals] == [("marchande", 3_000_000.0, True)]
    assert client.get(f"{IMM}/{g}/financials", headers=auth_headers).json()["valeur_actuelle"] == 3_000_000
    # Même valeur renvoyée (l'écran envoie tous les champs) : rien de plus.
    client.patch(f"{IMM}/{g}", headers=auth_headers, json={"valeur_actuelle": 3_000_000})
    # Correction le même jour : l'évaluation du jour est corrigée.
    client.patch(f"{IMM}/{g}", headers=auth_headers, json={"valeur_actuelle": 3_160_000})
    evals = client.get(f"{IMM}/{g}/evaluations", headers=auth_headers).json()
    assert [(e["valeur"], e["is_reference"]) for e in evals] == [(3_160_000.0, True)]
    # Un rapport d'évaluateur plus ancien, de référence, n'est PAS réécrit :
    # la saisie ajoute une évaluation et reprend la référence.
    r = client.post("/api/v1/immobilier/evaluations", headers=auth_headers, json={
        "immeuble_id": g, "kind": "appraisal", "valeur": 2_900_000,
        "date_evaluation": "2025-01-27", "is_reference": True,
    })
    assert r.status_code == 201, r.text
    rapport = r.json()["id"]
    assert client.get(f"{IMM}/{g}/financials", headers=auth_headers).json()["valeur_actuelle"] == 2_900_000
    client.patch(f"{IMM}/{g}", headers=auth_headers, json={"valeur_actuelle": 3_200_000})
    evals = {e["id"]: e for e in client.get(f"{IMM}/{g}/evaluations", headers=auth_headers).json()}
    assert evals[rapport]["valeur"] == 2_900_000 and evals[rapport]["is_reference"] is False
    assert sorted((e["valeur"], e["is_reference"]) for e in evals.values()) == [(2_900_000.0, False), (3_200_000.0, True)]
    assert client.get(f"{IMM}/{g}/financials", headers=auth_headers).json()["valeur_actuelle"] == 3_200_000
    assert client.patch(f"{IMM}/{g}", headers=auth_headers, json={"valeur_actuelle": -1}).status_code == 422
