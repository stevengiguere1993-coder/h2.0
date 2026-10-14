"""Smoke — case « dîner » de la fiche employé (Steven, 2026-10-05).

Cochée, elle retire 30 minutes de dîner des heures de punch de
l'employé, une fois par jour, quand la journée punchée dépasse 5 h, à
partir du jour où elle est cochée. Le retrait est noté sur le punch
(``diner_minutes``) et soustrait du total des heures de paie.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import delete

from app.core.security import create_access_token, get_password_hash
from app.models.employe import Employe
from app.models.punch import Punch
from app.models.user import User
from app.services.punch_diner import MONTREAL, aujourd_hui_local

from tests.smoke.conftest import TestSessionLocal

AUJOURD_HUI = aujourd_hui_local()


def _iso(jour: date, h: int, m: int = 0) -> str:
    """Instant ``jour`` à ``h:m`` heure de Montréal, en ISO UTC."""
    return (
        datetime.combine(jour, time(h, m), tzinfo=MONTREAL)
        .astimezone(timezone.utc)
        .isoformat()
    )


def _creer_employe(run, nom: str, *, diner: bool, depuis: date | None = None) -> int:
    async def _seed() -> int:
        async with TestSessionLocal() as s:
            e = Employe(full_name=nom, diner_auto=diner, diner_depuis=depuis)
            s.add(e)
            await s.commit()
            return e.id

    return run(_seed())


def _punch(client, headers, employe_id: int, debut: str, fin: str | None, **extra) -> dict:
    r = client.post(
        "/api/v1/punch",
        headers=headers,
        json={"employe_id": employe_id, "started_at": debut, "ended_at": fin, **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _periode_de_paie(jour: date) -> str:
    """Fin (vendredi) de la période de paie qui contient ``jour``."""
    from app.api.v1.endpoints.punch_ops import PAYROLL_ANCHOR_PERIOD_END

    ecart = (jour - PAYROLL_ANCHOR_PERIOD_END).days
    cycles = -(-ecart // 14)  # plafond
    return (PAYROLL_ANCHOR_PERIOD_END + timedelta(days=cycles * 14)).isoformat()


# ── Fiche employé ───────────────────────────────────────────────────────


def test_case_diner_sur_la_fiche(client, auth_headers, run):
    emp_id = _creer_employe(run, "Fiche Dîner", diner=False)

    r = client.get(f"/api/v1/employes/{emp_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["diner_auto"] is False
    assert r.json()["diner_depuis"] is None

    # Cochée → s'applique à partir d'aujourd'hui (heure de Montréal).
    r = client.patch(
        f"/api/v1/employes/{emp_id}", headers=auth_headers, json={"diner_auto": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["diner_auto"] is True
    assert r.json()["diner_depuis"] == AUJOURD_HUI.isoformat()

    # Réenregistrer la fiche sans toucher la case ne déplace pas la date.
    r = client.patch(
        f"/api/v1/employes/{emp_id}",
        headers=auth_headers,
        json={"diner_auto": True, "diner_depuis": "2026-01-05"},
    )
    assert r.json()["diner_depuis"] == "2026-01-05"
    r = client.patch(
        f"/api/v1/employes/{emp_id}",
        headers=auth_headers,
        json={"diner_auto": True, "notes": "Garde la date"},
    )
    assert r.json()["diner_depuis"] == "2026-01-05"

    # Décochée → plus de date.
    r = client.patch(
        f"/api/v1/employes/{emp_id}", headers=auth_headers, json={"diner_auto": False}
    )
    assert r.json()["diner_auto"] is False
    assert r.json()["diner_depuis"] is None

    # Création d'un employé avec la case cochée.
    r = client.post(
        "/api/v1/employes",
        headers=auth_headers,
        json={"full_name": "Nouveau Dîner", "diner_auto": True},
    )
    assert r.status_code == 201, r.text
    assert r.json()["diner_depuis"] == AUJOURD_HUI.isoformat()


# ── Retrait automatique ─────────────────────────────────────────────────


def test_journee_de_plus_de_5_h_retire_30_min(client, auth_headers, run):
    emp_id = _creer_employe(run, "Journée Pleine", diner=True, depuis=AUJOURD_HUI)

    p = _punch(client, auth_headers, emp_id, _iso(AUJOURD_HUI, 7), _iso(AUJOURD_HUI, 15, 30))
    assert p["diner_minutes"] == 30
    assert float(p["hours"]) == 8.0

    # Une seule fois par jour : le punch suivant garde toutes ses heures.
    p2 = _punch(client, auth_headers, emp_id, _iso(AUJOURD_HUI, 15, 30), _iso(AUJOURD_HUI, 17))
    assert p2["diner_minutes"] is None
    assert float(p2["hours"]) == 1.5

    # La note est lisible dans la liste de la gestion des punchs.
    r = client.get("/api/v1/punch?limit=500", headers=auth_headers)
    assert r.status_code == 200, r.text
    par_id = {x["id"]: x for x in r.json()}
    assert par_id[p["id"]]["diner_minutes"] == 30
    assert float(par_id[p["id"]]["hours"]) == 8.0


def test_journee_de_5_h_ou_moins_garde_tout(client, auth_headers, run):
    emp_id = _creer_employe(run, "Demi Journée", diner=True, depuis=AUJOURD_HUI)
    p = _punch(client, auth_headers, emp_id, _iso(AUJOURD_HUI, 8), _iso(AUJOURD_HUI, 13))
    assert p["diner_minutes"] is None
    assert float(p["hours"]) == 5.0


def test_le_punch_qui_depasse_5_h_porte_le_diner(client, auth_headers, run):
    emp_id = _creer_employe(run, "Deux Chantiers", diner=True, depuis=AUJOURD_HUI)
    matin = _punch(client, auth_headers, emp_id, _iso(AUJOURD_HUI, 7), _iso(AUJOURD_HUI, 11))
    assert matin["diner_minutes"] is None
    apres_midi = _punch(client, auth_headers, emp_id, _iso(AUJOURD_HUI, 11), _iso(AUJOURD_HUI, 15))
    assert apres_midi["diner_minutes"] == 30
    assert float(apres_midi["hours"]) == 3.5


def test_punch_trop_court_le_diner_va_au_plus_long(client, auth_headers, run):
    emp_id = _creer_employe(run, "Petit Punch", diner=True, depuis=AUJOURD_HUI)
    long_ = _punch(client, auth_headers, emp_id, _iso(AUJOURD_HUI, 7), _iso(AUJOURD_HUI, 11, 54))
    court = _punch(client, auth_headers, emp_id, _iso(AUJOURD_HUI, 11, 54), _iso(AUJOURD_HUI, 12, 24))
    assert court["diner_minutes"] is None
    assert float(court["hours"]) == 0.5

    r = client.get(f"/api/v1/punch/{long_['id']}", headers=auth_headers)
    assert r.json()["diner_minutes"] == 30
    assert float(r.json()["hours"]) == 4.4


def test_heures_d_avant_la_case_et_sans_case_ne_changent_pas(client, auth_headers, run):
    emp_id = _creer_employe(run, "Avant La Case", diner=True, depuis=AUJOURD_HUI)
    hier = AUJOURD_HUI - timedelta(days=1)
    p = _punch(client, auth_headers, emp_id, _iso(hier, 7), _iso(hier, 16))
    assert p["diner_minutes"] is None
    assert float(p["hours"]) == 9.0

    sans_case = _creer_employe(run, "Sans Case", diner=False)
    p = _punch(client, auth_headers, sans_case, _iso(AUJOURD_HUI, 7), _iso(AUJOURD_HUI, 16))
    assert p["diner_minutes"] is None
    assert float(p["hours"]) == 9.0


# ── Gestion des punchs : choix manuel ───────────────────────────────────


def test_gestion_enleve_ou_remet_le_diner(client, auth_headers, run):
    emp_id = _creer_employe(run, "Choix Manuel", diner=True, depuis=AUJOURD_HUI)
    p = _punch(client, auth_headers, emp_id, _iso(AUJOURD_HUI, 7), _iso(AUJOURD_HUI, 15, 30))
    assert float(p["hours"]) == 8.0

    # Approuver ne remet pas les 30 minutes (les heures sont recalculées
    # depuis le début et la fin, dîner retiré).
    r = client.patch(f"/api/v1/punch/{p['id']}", headers=auth_headers, json={"approved": True})
    assert r.status_code == 200, r.text
    assert float(r.json()["hours"]) == 8.0
    assert r.json()["diner_minutes"] == 30

    # Corriger l'heure de fin garde le dîner retiré.
    r = client.patch(
        f"/api/v1/punch/{p['id']}", headers=auth_headers, json={"ended_at": _iso(AUJOURD_HUI, 16)}
    )
    assert float(r.json()["hours"]) == 8.5

    # Le gestionnaire enlève le retrait, puis le remet.
    r = client.patch(f"/api/v1/punch/{p['id']}", headers=auth_headers, json={"diner_minutes": 0})
    assert r.status_code == 200, r.text
    assert r.json()["diner_minutes"] == 0
    assert float(r.json()["hours"]) == 9.0
    r = client.patch(f"/api/v1/punch/{p['id']}", headers=auth_headers, json={"diner_minutes": 30})
    assert float(r.json()["hours"]) == 8.5

    # Choix explicite à la création : pas de retrait, et la journée est
    # décidée (aucun retrait automatique ensuite).
    autre = _creer_employe(run, "Sans Retrait", diner=True, depuis=AUJOURD_HUI)
    p = _punch(
        client, auth_headers, autre, _iso(AUJOURD_HUI, 7), _iso(AUJOURD_HUI, 16), diner_minutes=0
    )
    assert p["diner_minutes"] == 0
    assert float(p["hours"]) == 9.0
    p2 = _punch(client, auth_headers, autre, _iso(AUJOURD_HUI, 16), _iso(AUJOURD_HUI, 18))
    assert p2["diner_minutes"] is None
    assert float(p2["hours"]) == 2.0


def test_fermer_un_punch_ouvert_dans_la_gestion(client, auth_headers, run):
    emp_id = _creer_employe(run, "Oubli De Punch", diner=True, depuis=AUJOURD_HUI)
    p = _punch(client, auth_headers, emp_id, _iso(AUJOURD_HUI, 7), None)
    assert p["hours"] is None
    r = client.patch(
        f"/api/v1/punch/{p['id']}", headers=auth_headers, json={"ended_at": _iso(AUJOURD_HUI, 15)}
    )
    assert r.status_code == 200, r.text
    assert r.json()["diner_minutes"] == 30
    assert float(r.json()["hours"]) == 7.5


# ── Paie ────────────────────────────────────────────────────────────────


def test_paie_soustrait_le_diner(client, auth_headers, run):
    emp_id = _creer_employe(run, "Zz Paie Dîner", diner=True, depuis=AUJOURD_HUI)
    _punch(client, auth_headers, emp_id, _iso(AUJOURD_HUI, 7), _iso(AUJOURD_HUI, 15, 30))

    r = client.get(
        f"/api/v1/punch/payroll/bi-weekly?period_end={_periode_de_paie(AUJOURD_HUI)}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rapport = r.json()
    ligne = next(x for x in rapport["rows"] if x["employe_id"] == emp_id)
    assert ligne["total_hours"] == 8.0
    assert ligne["hours_diner"] == 0.5
    assert ligne["diners"] == 1
    assert rapport["total_hours_diner"] >= 0.5

    mois = f"{AUJOURD_HUI.year:04d}-{AUJOURD_HUI.month:02d}"
    r = client.get(f"/api/v1/punch/payroll?month={mois}", headers=auth_headers)
    assert r.status_code == 200, r.text
    ligne = next(x for x in r.json()["rows"] if x["employe_id"] == emp_id)
    assert ligne["total_hours"] == 8.0
    assert ligne["hours_diner"] == 0.5

    r = client.get(
        f"/api/v1/punch/employe/{emp_id}/punches.csv?month={mois}", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    lignes = r.text.splitlines()
    assert lignes[0].split(",")[3:5] == ["hours", "diner_min"]
    assert lignes[1].split(",")[3:5] == ["8.0", "30"]


# ── Clock-out de l'employé (web, mobile) et fermeture de 22 h ───────────


@pytest.fixture(scope="module")
def employe_punch(run) -> dict:
    """Compte employé lié à une fiche avec la case « dîner » cochée."""
    courriel = "diner.punch@example.com"

    async def _seed():
        async with TestSessionLocal() as s:
            u = User(
                email=courriel,
                hashed_password=get_password_hash("x" * 12),
                is_active=True,
                is_admin=False,
                role="employee",
            )
            e = Employe(
                full_name="Punch Mobile",
                email=courriel,
                diner_auto=True,
                diner_depuis=AUJOURD_HUI - timedelta(days=7),
            )
            s.add_all([u, e])
            await s.commit()
            return {"user_id": u.id, "employe_id": e.id}

    ids = run(_seed())
    token = create_access_token(subject=str(ids["user_id"]))
    return {**ids, "headers": {"Authorization": f"Bearer {token}"}}


def _reculer_debut(run, punch_id: int, heures: float) -> None:
    async def _maj():
        async with TestSessionLocal() as s:
            p = await s.get(Punch, punch_id)
            p.started_at = datetime.now(timezone.utc) - timedelta(hours=heures)
            await s.commit()

    run(_maj())


def test_clock_out_web_et_mobile(client, employe_punch, run):
    h = employe_punch["headers"]

    # Web : 6 h punchées → 5 h 30 payées.
    r = client.post("/api/v1/punch/clock-in", headers=h, json={})
    assert r.status_code == 201, r.text
    _reculer_debut(run, r.json()["id"], 6)
    r = client.post("/api/v1/punch/clock-out", headers=h, json={})
    assert r.status_code == 200, r.text
    assert r.json()["diner_minutes"] == 30
    assert abs(float(r.json()["hours"]) - 5.5) < 0.02

    # Mobile : on efface la décision du jour pour rejouer la règle.
    async def _reinit():
        async with TestSessionLocal() as s:
            await s.execute(
                delete(Punch).where(Punch.employe_id == employe_punch["employe_id"])
            )
            await s.commit()

    run(_reinit())
    r = client.post("/api/v1/mobile/punch/start", headers=h, json={"task": "Administration"})
    assert r.status_code == 200, r.text
    _reculer_debut(run, r.json()["id"], 7)
    r = client.post("/api/v1/mobile/punch/stop", headers=h, json={})
    assert r.status_code == 200, r.text
    r = client.get(f"/api/v1/punch/{r.json()['id']}", headers=h)
    assert r.json()["diner_minutes"] == 30
    assert abs(float(r.json()["hours"]) - 6.5) < 0.02


def test_fermeture_automatique_de_22_h(run, employe_punch):
    from app.jobs.punch_auto_close import _run

    # Un jour sans autre punch de cet employé (les clock-out du test
    # précédent peuvent tomber hier selon l'heure où la suite tourne).
    jour = AUJOURD_HUI - timedelta(days=3)

    async def _ouvrir() -> int:
        async with TestSessionLocal() as s:
            p = Punch(
                employe_id=employe_punch["employe_id"],
                started_at=datetime.combine(jour, time(8), tzinfo=MONTREAL).astimezone(
                    timezone.utc
                ),
                regime="hors_decret",
            )
            s.add(p)
            await s.commit()
            return p.id

    punch_id = run(_ouvrir())
    run(_run())

    async def _relire():
        async with TestSessionLocal() as s:
            return await s.get(Punch, punch_id)

    p = run(_relire())
    assert p.ended_at is not None
    assert p.diner_minutes == 30
    assert float(p.hours) == 13.5  # 8 h → 22 h, moins le dîner
    assert "AUTO-FERMÉ" in (p.notes or "")
    # Laisse finir les éventuelles tâches d'arrière-plan.
    run(asyncio.sleep(0))
