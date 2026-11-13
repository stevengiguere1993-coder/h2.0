"""Smoke — vue d'ensemble des dépenses de la construction (bug 14, Steven
2026-10-03 : « vue d'ensemble des dépenses construction général et
calculer coût à l'heure vs entrée de fonds »).

Données en mars-avril 2032 (aucun autre test n'y écrit), retirées à la
fin du module. Employés sans prime CNESST ni CCQ : coût réel = taux.
QuickBooks est simulé : aucun appel réseau.

En développement depuis le 2026-10-23 (« juste permettre au dev de
voir ») : propriétaires seulement, sauf exception individuelle.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Dict

import pytest
from sqlalchemy import delete

import app.services.qbo_optimisation as opti
from app.core.security import create_access_token, get_password_hash
from app.integrations.quickbooks import QuickBooksError
from app.models.achat import Achat
from app.models.client import Client
from app.models.employe import Employe
from app.models.facture import Facture
from app.models.payment import Payment
from app.models.project import Project
from app.models.punch import Punch
from app.models.sous_traitant import SousTraitant
from app.models.user import User
from app.models.user_access_override import UserAccessOverride
from app.services import depenses_construction as svc
from app.services.punch_diner import aujourd_hui_local

from tests.smoke.conftest import TestSessionLocal

URL = "/api/v1/depenses-construction"
PERIODE = {"debut": "2032-03-01", "fin": "2032-04-30"}
PAGE = "page:entreprises.depenses_construction_dev"


def _compte(run, role: str, *, exception: bool = False) -> Dict[str, str]:
    """Compte de test et son jeton ; ``exception`` ouvre la page par une
    exception individuelle (Paramètres → Permissions)."""

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = User(
                email=f"smoke-depenses-{role}-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password=get_password_hash("smoke-depenses-x"),
                is_active=True,
                is_admin=role in ("owner", "admin"),
                role=role,
            )
            s.add(u)
            await s.flush()
            if exception:
                s.add(UserAccessOverride(user_id=u.id, key=PAGE, allow=True))
            await s.commit()
            return u.id

    return {"Authorization": f"Bearer {create_access_token(subject=str(run(_seed())))}"}


@pytest.fixture(scope="module")
def owner_headers(client, run) -> Dict[str, str]:
    return _compte(run, "owner")


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def donnees(run, db_setup):
    """Mars : 18 h (620 $), 1 050 $ de matériaux, 4 000 $ reçus HT.
    Avril : 7 h (280 $), 200 $ de matériaux, 2 000 $ de sous-traitant,
    100 $ de shop, 1 000 $ reçus HT."""
    ids: dict[str, list[int]] = {}

    async def _seed() -> None:
        async with TestSessionLocal() as s:
            a = Employe(full_name="Dépenses A", hourly_rate=40, cnesst_actif=False, is_ccq=False)
            b = Employe(full_name="Dépenses B", hourly_rate=30, cnesst_actif=False, is_ccq=False)
            client = Client(name="Client dépenses 2032")
            st = SousTraitant(full_name="Sous-traitant dépenses 2032")
            s.add_all([a, b, client, st])
            await s.flush()
            projet = Project(name="Chantier dépenses 2032", client_id=client.id)
            s.add(projet)
            await s.flush()

            def punch(emp: int, debut: datetime, heures: float, ferme: bool = True) -> Punch:
                return Punch(
                    employe_id=emp,
                    project_id=projet.id,
                    started_at=debut,
                    ended_at=debut.replace(hour=debut.hour + int(heures)) if ferme else None,
                    hours=heures if ferme else None,
                    approved=True,
                )

            punchs = [
                punch(a.id, _utc(2032, 3, 10, 13), 8),
                punch(b.id, _utc(2032, 3, 11, 13), 10),
                punch(a.id, _utc(2032, 4, 2, 13), 5),
                # 1er mai 2 h UTC = 30 avril 22 h à Montréal → avril.
                punch(a.id, _utc(2032, 5, 1, 2), 2),
                # Punch ouvert : pas encore d'heures.
                punch(a.id, _utc(2032, 4, 3, 13), 0, ferme=False),
                # Hors période.
                punch(b.id, _utc(2032, 6, 15, 13), 4),
            ]
            achats = [
                # Matériaux du projet : 1 149,75 $ payés = 1 000 $ HT.
                Achat(kind="material", project_id=projet.id, amount=1000, amount_taxes=149.75,
                      invoice_date=date(2032, 3, 5)),
                # Sans facture ni réception : daté de sa saisie.
                Achat(kind="material", project_id=projet.id, amount=50, amount_taxes=7.49,
                      created_at=_utc(2032, 3, 15, 15)),
                # Facture de sous-traitant datée de sa réception.
                Achat(kind="sub_invoice", sous_traitant_id=st.id, project_id=projet.id,
                      amount=2000, amount_taxes=299.50, received_at=_utc(2032, 4, 10, 15)),
                # Shop : relié à aucun projet ni client.
                Achat(kind="material", is_shop=True, amount=100, amount_taxes=14.98,
                      invoice_date=date(2032, 4, 20)),
                # Reçu rattaché au client seulement : matériaux.
                Achat(kind="material", client_id=client.id, amount=200, amount_taxes=29.95,
                      invoice_date=date(2032, 4, 21)),
                # Exclus : annulé, sortie d'inventaire, facture d'un autre mois.
                Achat(kind="material", project_id=projet.id, amount=5000, amount_taxes=0,
                      invoice_date=date(2032, 3, 6), status="cancelled"),
                Achat(kind="inventaire", project_id=projet.id, amount=300, amount_taxes=0,
                      invoice_date=date(2032, 3, 7)),
                Achat(kind="material", project_id=projet.id, amount=777, amount_taxes=0,
                      invoice_date=date(2032, 2, 28), received_at=_utc(2032, 3, 2, 15)),
            ]
            f1 = Facture(reference="DEP14-2032-1", client_id=client.id, project_id=projet.id,
                         subtotal=4000, total=4599, status="paid")
            # Import QuickBooks sans sous-total : taxes du Québec retirées.
            f2 = Facture(reference="DEP14-2032-2", client_id=client.id, project_id=projet.id,
                         status="paid")
            s.add_all([*punchs, *achats, f1, f2])
            await s.flush()
            paiements = [
                Payment(facture_id=f1.id, amount=4599, paid_at=date(2032, 3, 20)),
                Payment(facture_id=f2.id, amount=1149.75, paid_at=date(2032, 4, 25)),
                Payment(facture_id=f2.id, amount=500, paid_at=date(2032, 5, 2)),
            ]
            s.add_all(paiements)
            await s.commit()
            ids.update(
                employes=[a.id, b.id],
                punchs=[p.id for p in punchs],
                achats=[x.id for x in achats],
                paiements=[p.id for p in paiements],
                factures=[f1.id, f2.id],
                projets=[projet.id],
                clients=[client.id],
                sous_traitants=[st.id],
            )

    async def _purge() -> None:
        async with TestSessionLocal() as s:
            for modele, cle in (
                (Payment, "paiements"),
                (Facture, "factures"),
                (Achat, "achats"),
                (Punch, "punchs"),
                (Project, "projets"),
                (SousTraitant, "sous_traitants"),
                (Client, "clients"),
                (Employe, "employes"),
            ):
                if ids.get(cle):
                    await s.execute(delete(modele).where(modele.id.in_(ids[cle])))
            await s.commit()

    run(_seed())
    yield ids
    run(_purge())


# ── Vue d'ensemble Kratos ──────────────────────────────────────────────


def test_vue_ensemble(client, owner_headers, donnees):
    r = client.get(URL, headers=owner_headers, params=PERIODE)
    assert r.status_code == 200, r.text
    v = r.json()

    assert v["debut"] == "2032-03-01" and v["fin"] == "2032-04-30"
    assert v["heures"] == 25
    assert v["employes"] == 2
    assert v["main_oeuvre"] == 900  # 8 × 40 + 10 × 30 + 7 × 40
    assert v["materiaux"] == 1250
    assert v["sous_traitants"] == 2000
    assert v["frais_generaux"] == 100
    assert v["achats"] == 3350
    assert v["achats_ttc"] == pytest.approx(3851.67)
    assert v["depenses"] == 4250
    assert v["cout_heure"] == 170
    assert v["cout_main_oeuvre_heure"] == 36
    assert v["entrees_ttc"] == pytest.approx(5748.75)
    assert v["entrees_ht"] == 5000
    assert v["nb_paiements"] == 2
    assert v["entrees_heure"] == 200
    assert v["ecart_heure"] == 30
    assert v["resultat"] == 750

    cats = {c["cle"]: c for c in v["categories"]}
    assert [c["cle"] for c in v["categories"]] == [
        "main_oeuvre", "materiaux", "sous_traitants", "frais_generaux",
    ]
    assert cats["sous_traitants"]["montant"] == 2000
    assert cats["sous_traitants"]["par_heure"] == 80
    assert cats["sous_traitants"]["part_pct"] == 47.1
    assert cats["frais_generaux"]["par_heure"] == 4

    mars, avril = v["mois"]
    assert (mars["mois"], mars["debut"], mars["fin"]) == ("2032-03", "2032-03-01", "2032-03-31")
    assert mars["heures"] == 18 and mars["main_oeuvre"] == 620
    assert mars["materiaux"] == 1050 and mars["depenses"] == 1670
    assert mars["cout_heure"] == 92.78
    assert mars["entrees_ht"] == 4000 and mars["entrees_heure"] == 222.22
    assert mars["ecart_heure"] == 129.44
    # Le punch du 30 avril au soir (1er mai UTC) compte en avril.
    assert avril["heures"] == 7 and avril["main_oeuvre"] == 280
    assert avril["sous_traitants"] == 2000 and avril["frais_generaux"] == 100
    assert avril["depenses"] == 2580 and avril["cout_heure"] == 368.57
    assert avril["entrees_ht"] == 1000 and avril["ecart_heure"] == -225.71


def test_mois_entame_et_periode_sans_donnees(client, owner_headers, donnees):
    r = client.get(URL, headers=owner_headers, params={"debut": "2032-03-15", "fin": "2032-03-31"})
    assert r.status_code == 200, r.text
    v = r.json()
    # Le 10 et le 11 mars sont avant le 15 ; les 50 $ saisis le 15 et
    # le paiement du 20 y sont.
    assert v["heures"] == 0 and v["cout_heure"] is None and v["entrees_heure"] is None
    assert v["materiaux"] == 50 and v["entrees_ht"] == 4000
    assert [(m["mois"], m["debut"]) for m in v["mois"]] == [("2032-03", "2032-03-15")]

    r = client.get(URL, headers=owner_headers, params={"debut": "2033-01-01", "fin": "2033-02-15"})
    v = r.json()
    assert v["depenses"] == 0 and v["entrees_ht"] == 0 and v["heures"] == 0
    assert all(c["part_pct"] == 0 for c in v["categories"])
    assert [m["mois"] for m in v["mois"]] == ["2033-01", "2033-02"]


def test_periode_par_defaut_et_validation(client, owner_headers):
    r = client.get(URL, headers=owner_headers)
    assert r.status_code == 200, r.text
    auj = aujourd_hui_local()
    v = r.json()
    assert v["fin"] == auj.isoformat()
    assert v["debut"].endswith("-01") and len(v["mois"]) == 12

    r = client.get(URL, headers=owner_headers, params={"debut": "2032-05-01", "fin": "2032-04-30"})
    assert r.status_code == 422
    assert "précéder" in r.json()["detail"]
    r = client.get(URL, headers=owner_headers, params={"debut": "2020-01-01", "fin": "2032-04-30"})
    assert r.status_code == 422


def test_en_developpement_reserve_au_dev(client, run, owner_headers, auth_headers, employee_headers):
    # Propriétaire : la page est accordée (lien rouge dans le menu).
    assert client.get("/api/v1/auth/me", headers=owner_headers).json()["access"][PAGE] is True
    assert client.get(URL, headers=owner_headers, params=PERIODE).status_code == 200

    # Admin et employé : ni lien ni données.
    for h in (auth_headers, employee_headers):
        assert client.get("/api/v1/auth/me", headers=h).json()["access"][PAGE] is False
        assert client.get(URL, headers=h, params=PERIODE).status_code == 403
        assert client.get(f"{URL}/quickbooks", headers=h).status_code == 403

    # Exception individuelle : l'ouvrir à un admin sans changer le seuil.
    invite = _compte(run, "admin", exception=True)
    assert client.get("/api/v1/auth/me", headers=invite).json()["access"][PAGE] is True
    assert client.get(URL, headers=invite, params=PERIODE).status_code == 200


# ── QuickBooks ─────────────────────────────────────────────────────────


def test_quickbooks_ramene_aux_heures(client, owner_headers, donnees, monkeypatch):
    appels: list[tuple] = []

    async def faux_cashflow(scope, debut, fin, hypotheque_account_id=None):
        appels.append((scope, debut, fin))
        return {
            "mois": [
                {"mois": "Mars 2032", "debut": "2032-03-01", "fin": "2032-03-31",
                 "revenus": 6000, "depenses": 4000, "details": []},
                {"mois": "Avril 2032", "debut": "2032-04-01", "fin": "2032-04-30",
                 "revenus": 1000, "depenses": 3000, "details": []},
            ],
            "total": {
                "revenus": 7000,
                "depenses": 7000,
                "details": [
                    {"nom": "Ventes", "type": "revenu", "montant": 7000},
                    {"nom": "Loyer", "type": "depense", "montant": 2500},
                    {"nom": "Salaires", "type": "depense", "montant": 4500},
                ],
            },
        }

    monkeypatch.setattr(opti, "cashflow_mensuel", faux_cashflow)
    r = client.get(f"{URL}/quickbooks", headers=owner_headers, params=PERIODE)
    assert r.status_code == 200, r.text
    v = r.json()
    assert appels == [("construction", "2032-03-01", "2032-04-30")]
    assert v["connecte"] is True and v["erreur"] is None
    assert v["heures"] == 25
    assert v["depenses"] == 7000 and v["cout_heure"] == 280
    assert v["revenus_heure"] == 280
    # Postes de dépense seulement, les plus gros d'abord.
    assert v["postes"] == [
        {"nom": "Salaires", "montant": 4500},
        {"nom": "Loyer", "montant": 2500},
    ]
    assert [(m["mois"], m["heures"], m["cout_heure"]) for m in v["mois"]] == [
        ("2032-03", 18, 222.22),
        ("2032-04", 7, 428.57),
    ]


def test_quickbooks_non_connecte_ou_en_erreur(client, owner_headers, monkeypatch):
    async def non_connecte(*a, **kw):
        raise RuntimeError("QuickBooks n'est pas connecté pour « construction ».")

    monkeypatch.setattr(opti, "cashflow_mensuel", non_connecte)
    r = client.get(f"{URL}/quickbooks", headers=owner_headers, params=PERIODE)
    assert r.status_code == 200, r.text
    assert r.json()["connecte"] is False
    assert "pas connecté" in r.json()["erreur"]

    async def panne(*a, **kw):
        raise QuickBooksError("QBO 500")

    monkeypatch.setattr(opti, "cashflow_mensuel", panne)
    r = client.get(f"{URL}/quickbooks", headers=owner_headers, params=PERIODE)
    assert r.status_code == 200, r.text
    assert r.json()["connecte"] is True
    assert "QBO 500" in r.json()["erreur"]
    assert r.json()["cout_heure"] is None


# ── Règles de calcul ───────────────────────────────────────────────────


def test_regles_de_calcul():
    assert svc.mois_de_la_periode(date(2032, 1, 20), date(2032, 3, 5)) == [
        ("2032-01", date(2032, 1, 20), date(2032, 1, 31)),
        ("2032-02", date(2032, 2, 1), date(2032, 2, 29)),
        ("2032-03", date(2032, 3, 1), date(2032, 3, 5)),
    ]
    assert svc.mois_de_la_periode(date(2031, 12, 1), date(2032, 1, 1))[-1] == (
        "2032-01", date(2032, 1, 1), date(2032, 1, 1),
    )
    assert svc.categorie_achat("sub_invoice", None, 1, None) == "sous_traitants"
    assert svc.categorie_achat("material", 4, None, None) == "sous_traitants"
    assert svc.categorie_achat("material", None, None, None) == "frais_generaux"
    assert svc.categorie_achat("material", None, None, 3) == "materiaux"
    assert svc.part_hors_taxes(1149.75, 1000, 1149.75) == pytest.approx(1000)
    assert svc.part_hors_taxes(1149.75, None, None) == 1000
    # Sous-total incohérent (plus grand que le total) : on ne s'y fie pas.
    assert svc.part_hors_taxes(1149.75, 2000, 1149.75) == 1000
