"""Smoke — feuilles de temps hors construction (Steven, 2026-11-13).

« Les 4 volets » : mode de calcul des heures sur la fiche (punch
construction par défaut pour qui a une fiche Employé), feuilles alignées sur
la période de paie, suivi et rappels, heures des feuilles dans le rapport de
paie.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, get_password_hash
from app.models.employe import Employe
from app.models.notification import Notification
from app.models.timesheet import Timesheet
from app.models.user import User
from app.services import feuille_rappels
from app.services.punch_diner import aujourd_hui_local

from tests.smoke.conftest import TestSessionLocal


def _creer_user(run, email: str, *, fiche: bool = False) -> int:
    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = User(
                email=email,
                hashed_password=get_password_hash("x" * 12),
                is_active=True,
                is_admin=False,
                role="employee",
                volets_json='["entreprises"]',
                first_name="Feuille",
                last_name=email.split("@")[0],
            )
            s.add(u)
            if fiche:
                s.add(Employe(full_name=f"Fiche {email}", email=email))
            await s.commit()
            return u.id

    return run(_seed())


def _headers(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


@pytest.fixture(scope="module", autouse=True)
def paie_hebdo(client, auth_headers):
    r = client.put(
        "/api/v1/punch/payroll/reglages",
        headers=auth_headers,
        json={"frequence": "hebdomadaire", "jour_debut": 0},
    )
    assert r.status_code == 200, r.text
    yield
    client.put(
        "/api/v1/punch/payroll/reglages",
        headers=auth_headers,
        json={"frequence": "aux_2_semaines", "jour_debut": 6,
              "debut_reference": "2026-04-19"},
    )


def test_mode_par_defaut_et_cases(client, auth_headers, run):
    avec_fiche = _creer_user(run, "mode.punch@example.com", fiche=True)
    sans_fiche = _creer_user(run, "mode.feuille@example.com")

    r = client.get(f"/api/v1/users/{avec_fiche}/mode-heures", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "punch" and r.json()["choisi"] is False
    r = client.get(f"/api/v1/users/{sans_fiche}/mode-heures", headers=auth_headers)
    assert r.json()["mode"] == "feuille"

    r = client.put(
        f"/api/v1/users/{avec_fiche}/mode-heures",
        headers=auth_headers,
        json={"punch": True, "feuille": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "les_deux" and r.json()["choisi"] is True

    # Aucune case = retour au défaut.
    r = client.put(
        f"/api/v1/users/{avec_fiche}/mode-heures",
        headers=auth_headers,
        json={"punch": False, "feuille": False},
    )
    assert r.json()["mode"] == "punch" and r.json()["choisi"] is False


def test_feuille_hebdo_transition_et_rapport_de_paie(client, auth_headers, run):
    uid = _creer_user(run, "feuille.hebdo@example.com")
    h = _headers(uid)
    lundi = aujourd_hui_local() - timedelta(days=aujourd_hui_local().weekday())

    # Ancienne feuille de 14 jours qui finit le mercredi de cette semaine.
    async def _ancienne() -> None:
        async with TestSessionLocal() as s:
            s.add(Timesheet(
                user_id=uid,
                period_start=lundi - timedelta(days=11),
                period_end=lundi + timedelta(days=2),
                taux_horaire=20.0,
                taux_refacturation=30.0,
                status="brouillon",
            ))
            await s.commit()

    run(_ancienne())
    jeudi = lundi + timedelta(days=3)
    r = client.get(f"/api/v1/timesheets/resolve?period_start={jeudi}", headers=h)
    assert r.status_code == 200, r.text
    f = r.json()
    # Feuille de transition : du jeudi au dimanche (pas de chevauchement).
    assert f["period_start"] == jeudi.isoformat()
    assert f["period_end"] == (lundi + timedelta(days=6)).isoformat()
    assert len(f["jours_dates"]) == 4

    # Semaine suivante : feuille hebdomadaire complète, lundi → dimanche.
    r = client.get(
        f"/api/v1/timesheets/resolve?period_start={lundi + timedelta(days=8)}", headers=h
    )
    nf = r.json()
    assert nf["period_start"] == (lundi + timedelta(days=7)).isoformat()
    assert len(nf["jours_dates"]) == 7

    # Un jour hors de la feuille est refusé.
    cie = nf["lignes"][0]["company_id"]
    r = client.put(
        f"/api/v1/timesheets/{nf['id']}/taches",
        headers=h,
        json={"lignes": [{"day_index": 9, "company_id": cie, "title": "x", "hours": 1}]},
    )
    assert r.status_code == 422, r.text

    # Heures du jeudi, puis approbation : elles entrent dans la paie.
    r = client.put(
        f"/api/v1/timesheets/{f['id']}/taches",
        headers=h,
        json={"lignes": [{"day_index": 0, "company_id": cie,
                          "title": "Montage vidéo", "hours": 6}]},
    )
    assert r.status_code == 200, r.text
    rep = client.get(
        f"/api/v1/punch/payroll/bi-weekly?period_end={jeudi}", headers=auth_headers
    ).json()
    ligne = next(x for x in rep["rows"] if x.get("user_id") == uid)
    assert ligne["source"] == "feuille"
    assert ligne["total_hours"] == 6.0 and ligne["pending_hours"] == 6.0
    assert ligne["montant_total"] == 0.0

    r = client.post(f"/api/v1/timesheets/{f['id']}/approve", headers=auth_headers)
    assert r.status_code == 200, r.text
    rep = client.get(
        f"/api/v1/punch/payroll/bi-weekly?period_end={jeudi}", headers=auth_headers
    ).json()
    ligne = next(x for x in rep["rows"] if x.get("user_id") == uid)
    assert ligne["pending_hours"] == 0.0
    taux = f["taux_horaire"]
    assert ligne["montant_total"] == round(6 * taux, 2)
    csv = client.get(
        f"/api/v1/punch/payroll/bi-weekly.csv?period_end={jeudi}", headers=auth_headers
    ).text
    assert any(l.endswith(",feuille") for l in csv.splitlines())

    # Mode « punch » seulement : la feuille ne compte plus dans la paie.
    client.put(
        f"/api/v1/users/{uid}/mode-heures", headers=auth_headers,
        json={"punch": True, "feuille": False},
    )
    rep = client.get(
        f"/api/v1/punch/payroll/bi-weekly?period_end={jeudi}", headers=auth_headers
    ).json()
    assert not any(x.get("user_id") == uid for x in rep["rows"])


def test_suivi_et_rappels(client, auth_headers, run):
    uid = _creer_user(run, "feuille.rappel@example.com")
    r = client.get("/api/v1/entreprises/employes/suivi-temps", headers=auth_headers)
    assert r.status_code == 200, r.text
    ligne = next(x for x in r.json()["lignes"] if x["user_id"] == uid)
    assert ligne["mode_heures"] == "feuille"
    assert "jours_sans_saisie" in ligne and "heures_par_jour" in ligne

    # Mardi : le lundi est vide → rappel une seule fois.
    mardi = date(2030, 1, 8)

    async def _rappels():
        async with TestSessionLocal() as s:
            res = await feuille_rappels.rappels_pour_cron(s, mardi)
            await s.commit()
            return res

    run(_rappels())
    run(_rappels())

    async def _compte() -> int:
        async with TestSessionLocal() as s:
            rows = (
                await s.execute(
                    select(Notification).where(
                        Notification.user_id == uid,
                        Notification.kind == feuille_rappels.KIND_JOUR_VIDE,
                    )
                )
            ).scalars().all()
            return len(rows)

    assert run(_compte()) == 1
    assert feuille_rappels.jour_ouvrable_precedent(date(2030, 1, 7)) == date(2030, 1, 4)
