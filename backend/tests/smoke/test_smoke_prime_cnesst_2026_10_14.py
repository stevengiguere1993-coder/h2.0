"""Smoke — prime CNESST réglable (Steven, 2026-10-14).

Un taux global daté dans Paramètres → Prime CNESST, appliqué au coût
horaire réel de tous les employés ; sur la fiche, une case « Prime CNESST »
(décochée = aucune prime) et un taux personnalisé facultatif. À la mise en
ligne, le taux global est repris des fiches sans changer le coût de
quiconque avait un taux.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete, select, update

from app.models.automation_setting import AutomationSetting
from app.models.employe import Employe
from app.models.employe_rate_history import EmployeRateHistory
from app.models.project import Project
from app.models.punch import Punch
from app.services.cnesst import (
    CNESST_KEY,
    charger_bareme_cnesst,
    initialiser_cnesst_global,
)

from tests.smoke.conftest import TestSessionLocal

URL = "/api/v1/construction/cnesst"


@pytest.fixture(autouse=True)
def sans_bareme(run, db_setup):
    """Chaque test part sans taux global et n'en laisse pas aux autres."""

    async def _purge():
        async with TestSessionLocal() as s:
            await s.execute(delete(AutomationSetting).where(AutomationSetting.key == CNESST_KEY))
            await s.commit()

    run(_purge())
    yield
    run(_purge())


def _employe(run, nom: str, **kw) -> int:
    async def _seed() -> int:
        async with TestSessionLocal() as s:
            e = Employe(full_name=nom, **kw)
            s.add(e)
            await s.commit()
            return e.id

    return run(_seed())


def _projet_avec_punchs(run, punchs: list[tuple[int, date, float]]) -> int:
    """Projet + punchs fermés (employé, jour, heures)."""

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            p = Project(name="Chantier CNESST")
            s.add(p)
            await s.flush()
            for emp_id, jour, heures in punchs:
                debut = datetime(jour.year, jour.month, jour.day, 13, tzinfo=timezone.utc)
                s.add(
                    Punch(
                        employe_id=emp_id,
                        project_id=p.id,
                        started_at=debut,
                        ended_at=debut.replace(hour=13 + int(heures)),
                        hours=heures,
                        approved=True,
                    )
                )
            await s.commit()
            return p.id

    return run(_seed())


def _cout_main_oeuvre(client, headers, projet_id: int) -> float:
    r = client.get(f"/api/v1/projects/{projet_id}/finances", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["actual_labour_cost"]


# ── Paramètres ──────────────────────────────────────────────────────────


def test_taux_global_dans_les_parametres(client, auth_headers, employee_headers):
    r = client.get(URL, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["taux_actuel"] == 0.0
    assert r.json()["paliers"] == []

    r = client.put(URL, headers=auth_headers, json={"taux": 0.0216, "depuis": "2026-01-01"})
    assert r.status_code == 200, r.text
    assert r.json()["taux_actuel"] == 0.0216
    assert r.json()["paliers"] == [{"depuis": "2026-01-01", "taux": 0.0216}]

    # Un taux futur ne change pas le taux actuel ; la même date remplace.
    client.put(URL, headers=auth_headers, json={"taux": 0.03, "depuis": "2099-01-01"})
    r = client.put(URL, headers=auth_headers, json={"taux": 0.031, "depuis": "2099-01-01"})
    assert r.json()["taux_actuel"] == 0.0216
    assert r.json()["paliers"][-1] == {"depuis": "2099-01-01", "taux": 0.031}
    assert len(r.json()["paliers"]) == 2

    r = client.delete(f"{URL}/paliers/2099-01-01", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert len(r.json()["paliers"]) == 1
    # Le premier palier couvre le passé : il ne se supprime pas.
    assert client.delete(f"{URL}/paliers/2026-01-01", headers=auth_headers).status_code == 409
    assert client.delete(f"{URL}/paliers/2030-01-01", headers=auth_headers).status_code == 404

    # Taux en DÉCIMAL entre 0 et 1 ; réservé aux gestionnaires.
    assert client.put(URL, headers=auth_headers, json={"taux": 2.16}).status_code == 422
    r = client.put(URL, headers=employee_headers, json={"taux": 0.05})
    assert r.status_code == 403, r.text


# ── Coût réel des projets ──────────────────────────────────────────────


def test_prime_appliquee_au_cout_du_projet(client, auth_headers, run):
    client.put(URL, headers=auth_headers, json={"taux": 0.02, "depuis": "2000-01-01"})
    globale = _employe(run, "CNESST Globale", hourly_rate=30)
    perso = _employe(run, "CNESST Perso", hourly_rate=30, cnesst_rate=0.05)
    sans = _employe(run, "CNESST Aucune", hourly_rate=30, cnesst_actif=False)
    jour = date(2026, 9, 1)
    projet = _projet_avec_punchs(run, [(globale, jour, 10), (perso, jour, 10), (sans, jour, 10)])

    # 10 h × 30 $ × (1 + 2 %) + 10 h × 30 $ × (1 + 5 %) + 10 h × 30 $.
    assert _cout_main_oeuvre(client, auth_headers, projet) == pytest.approx(306 + 315 + 300)

    # Le statut de chacun est visible dans les Paramètres.
    statuts = {e["id"]: e for e in client.get(URL, headers=auth_headers).json()["employes"]}
    assert statuts[globale]["source"] == "global"
    assert statuts[globale]["taux_effectif"] == 0.02
    assert statuts[perso]["source"] == "perso"
    assert statuts[sans]["source"] == "aucune"
    assert statuts[sans]["taux_effectif"] == 0.0


def test_changer_le_taux_global_ne_recoute_pas_le_passe(client, auth_headers, run):
    client.put(URL, headers=auth_headers, json={"taux": 0.02, "depuis": "2000-01-01"})
    emp = _employe(run, "CNESST Datée", hourly_rate=50)
    projet = _projet_avec_punchs(
        run, [(emp, date(2026, 6, 15), 1), (emp, date(2026, 7, 15), 1)]
    )
    assert _cout_main_oeuvre(client, auth_headers, projet) == pytest.approx(51 + 51)

    client.put(URL, headers=auth_headers, json={"taux": 0.04, "depuis": "2026-07-01"})
    # Juin garde 2 %, juillet passe à 4 %.
    assert _cout_main_oeuvre(client, auth_headers, projet) == pytest.approx(51 + 52)


# ── Fiche employé ──────────────────────────────────────────────────────


def test_case_et_taux_perso_sur_la_fiche(client, auth_headers):
    r = client.post("/api/v1/employes", headers=auth_headers, json={"full_name": "Fiche CNESST"})
    assert r.status_code == 201, r.text
    assert r.json()["cnesst_actif"] is True
    assert r.json()["cnesst_rate"] is None
    emp_id = r.json()["id"]

    # Décochée : le taux personnalisé est effacé.
    r = client.post(
        "/api/v1/employes",
        headers=auth_headers,
        json={"full_name": "Fiche Sans CNESST", "cnesst_actif": False, "cnesst_rate": 0.05},
    )
    assert r.json()["cnesst_actif"] is False
    assert r.json()["cnesst_rate"] is None

    r = client.patch(
        f"/api/v1/employes/{emp_id}",
        headers=auth_headers,
        json={"cnesst_actif": True, "cnesst_rate": 0.04},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cnesst_rate"] == 0.04
    r = client.patch(f"/api/v1/employes/{emp_id}", headers=auth_headers, json={"cnesst_actif": False})
    assert r.json()["cnesst_actif"] is False
    assert r.json()["cnesst_rate"] is None


def test_la_case_s_applique_au_palier_en_vigueur(client, auth_headers, run):
    client.put(URL, headers=auth_headers, json={"taux": 0.02, "depuis": "2000-01-01"})
    emp_id = _employe(run, "Historique CNESST", hourly_rate=40)

    # Palier daté : la baseline garde la fiche d'avant, le palier suit le
    # taux global.
    r = client.post(
        f"/api/v1/employes/{emp_id}/rate-history",
        headers=auth_headers,
        json={"effective_date": "2026-03-01", "hourly_rate": 45, "cnesst_actif": True, "cnesst_rate": None},
    )
    assert r.status_code == 201, r.text
    paliers = r.json()
    assert [p["cnesst_taux_effectif"] for p in paliers] == [0.02, 0.02]

    projet = _projet_avec_punchs(run, [(emp_id, date(2026, 4, 1), 10)])
    assert _cout_main_oeuvre(client, auth_headers, projet) == pytest.approx(10 * 45 * 1.02)

    # Décocher la case sur la fiche retire la prime du palier en vigueur.
    r = client.patch(f"/api/v1/employes/{emp_id}", headers=auth_headers, json={"cnesst_actif": False})
    assert r.status_code == 200, r.text
    paliers = client.get(f"/api/v1/employes/{emp_id}/rate-history", headers=auth_headers).json()
    assert [p["cnesst_actif"] for p in paliers] == [True, False]
    assert [p["cnesst_taux_effectif"] for p in paliers] == [0.02, 0.0]
    assert _cout_main_oeuvre(client, auth_headers, projet) == pytest.approx(10 * 45)

    # Un taux personnalisé suit le même chemin.
    client.patch(
        f"/api/v1/employes/{emp_id}",
        headers=auth_headers,
        json={"cnesst_actif": True, "cnesst_rate": 0.03},
    )
    paliers = client.get(f"/api/v1/employes/{emp_id}/rate-history", headers=auth_headers).json()
    assert paliers[-1]["cnesst_rate"] == 0.03
    assert _cout_main_oeuvre(client, auth_headers, projet) == pytest.approx(10 * 45 * 1.03)


# ── Mise en ligne : reprise des taux saisis sur les fiches ──────────────


def test_initialisation_reprend_les_taux_des_fiches(run):
    async def _scenario():
        async with TestSessionLocal() as s:
            # Les employés des autres tests ne comptent pas ici.
            await s.execute(update(Employe).values(active=False))
            ids = {}
            for nom, kw in {
                "a": dict(cnesst_rate=0.0216),
                "b": dict(cnesst_rate=0.0216),
                "c": dict(cnesst_rate=0.0216),
                "d": dict(cnesst_rate=0.03),
                "zero": dict(cnesst_rate=0),
                "vide": dict(cnesst_rate=None),
                "inactif1": dict(cnesst_rate=0.05, active=False),
                "inactif2": dict(cnesst_rate=0.05, active=False),
                "inactif3": dict(cnesst_rate=0.05, active=False),
                "inactif4": dict(cnesst_rate=0.05, active=False),
            }.items():
                e = Employe(full_name=f"Reprise {nom}", **kw)
                s.add(e)
                await s.flush()
                ids[nom] = e.id
            for nom, taux in (("a", 0.0216), ("d", 0.03), ("zero", 0)):
                s.add(
                    EmployeRateHistory(
                        employe_id=ids[nom],
                        effective_date=date(2026, 1, 1),
                        hourly_rate=30,
                        cnesst_rate=taux,
                    )
                )
            await s.flush()

            # Le plus fréquent chez les ACTIFS (les 4 inactifs à 5 % ne
            # comptent pas).
            assert await initialiser_cnesst_global(s) == 0.0216
            bareme = await charger_bareme_cnesst(s)
            assert [(p.depuis, p.taux) for p in bareme.paliers] == [(date(2000, 1, 1), 0.0216)]

            async def fiche(nom):
                row = (
                    await s.execute(
                        select(Employe.cnesst_actif, Employe.cnesst_rate).where(
                            Employe.id == ids[nom]
                        )
                    )
                ).one()
                return (bool(row[0]), float(row[1]) if row[1] is not None else None)

            async def palier(nom):
                row = (
                    await s.execute(
                        select(
                            EmployeRateHistory.cnesst_actif, EmployeRateHistory.cnesst_rate
                        ).where(EmployeRateHistory.employe_id == ids[nom])
                    )
                ).one()
                return (bool(row[0]), float(row[1]) if row[1] is not None else None)

            assert await fiche("a") == (True, None)  # suit le taux global
            assert await fiche("d") == (True, 0.03)  # taux différent gardé
            assert await fiche("zero") == (False, None)  # 0 % → case décochée
            assert await fiche("vide") == (True, None)  # vide → taux global
            assert await fiche("inactif1") == (True, 0.05)
            assert await palier("a") == (True, None)
            assert await palier("d") == (True, 0.03)
            assert await palier("zero") == (False, None)

            # Une seule fois.
            assert await initialiser_cnesst_global(s) is None
            await s.rollback()

    run(_scenario())
