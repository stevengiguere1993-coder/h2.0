"""Smoke — zone employés (Steven, 2026-10-04).

Un employé « autre » (ex. vidéo / marketing : compte avec le seul pôle
Entreprises, sans fiche Employé Construction) a sa zone employés : il se
crée des tâches pour l'une de nos entreprises, les classe et supprime les
siennes ; un gestionnaire, depuis Entreprises → Employés, voit l'équipe,
planifie un tournage dans son agenda (visible dans sa zone employés) et
suit le temps travaillé.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.access_registry import GENERAL, PAGES_BY_KEY
from app.core.security import create_access_token, get_password_hash
from app.models.entreprise import Entreprise
from app.models.user import User

from tests.smoke.conftest import TestSessionLocal

VIDEO_EMAIL = "video.zone@example.com"


@pytest.fixture(scope="module")
def video(run) -> dict:
    """Employé « autre » : rôle employee, pôle Entreprises seulement."""

    async def _seed():
        async with TestSessionLocal() as s:
            u = User(
                email=VIDEO_EMAIL,
                hashed_password=get_password_hash("x" * 12),
                is_active=True,
                is_admin=False,
                role="employee",
                volets_json='["entreprises"]',
                first_name="Vicky",
                last_name="Vidéo",
            )
            e = Entreprise(name="Horizon Médias Zone")
            s.add_all([u, e])
            await s.commit()
            return {"id": u.id, "entreprise_id": e.id}

    ids = run(_seed())
    token = create_access_token(subject=str(ids["id"]))
    return {**ids, "headers": {"Authorization": f"Bearer {token}"}}


# ── Registre d'accès ────────────────────────────────────────────────────


def test_registre_zone_employes():
    zone = PAGES_BY_KEY["construction.mobile"]
    assert zone.label == "Zone employés"
    assert zone.volet == GENERAL  # un employé « autre » y entre aussi
    assert zone.default_min_role == "employee"
    sec = PAGES_BY_KEY["entreprises.employes"]
    assert sec.volet == "entreprises"
    assert sec.default_min_role == "admin"
    assert "/entreprises/employes" in sec.routes


def test_acces_calcule(client, auth_headers, video):
    me = client.get("/api/v1/auth/me", headers=video["headers"]).json()
    assert me["volets"] == ["entreprises"]
    assert me["access"]["page:construction.mobile"] is True
    assert me["access"].get("page:entreprises.employes") is not True
    admin = client.get("/api/v1/auth/me", headers=auth_headers).json()
    assert admin["access"]["page:entreprises.employes"] is True


# ── Mes tâches ──────────────────────────────────────────────────────────


def test_mes_taches_cycle(client, auth_headers, employee_headers, video):
    h = video["headers"]

    r = client.get("/api/v1/entreprises/mes-taches/entreprises", headers=h)
    assert r.status_code == 200, r.text
    assert video["entreprise_id"] in {e["id"] for e in r.json()}

    # Il se crée une tâche → assignée à lui, supprimable par lui.
    r = client.post(
        "/api/v1/entreprises/mes-taches",
        headers=h,
        json={"title": "  Monter la capsule chantier ", "entreprise_id": video["entreprise_id"],
              "priority": "eleve"},
    )
    assert r.status_code == 201, r.text
    mienne = r.json()
    assert mienne["title"] == "Monter la capsule chantier"
    assert mienne["status"] == "a_faire"
    assert mienne["peut_supprimer"] is True
    assert mienne["created_by_user_id"] == video["id"]
    assert video["id"] in mienne["assignee_user_ids"]
    assert mienne["entreprise_name"] == "Horizon Médias Zone"

    # Un gestionnaire lui assigne une tâche depuis le QG.
    r = client.post(
        "/api/v1/entreprises/taches",
        headers=auth_headers,
        json={"title": "Tournage client", "entreprise_id": video["entreprise_id"],
              "assignee_user_ids": [video["id"]]},
    )
    assert r.status_code == 201, r.text
    assignee = r.json()

    r = client.get("/api/v1/entreprises/mes-taches", headers=h)
    assert r.status_code == 200, r.text
    par_id = {t["id"]: t for t in r.json()}
    assert mienne["id"] in par_id and assignee["id"] in par_id
    assert par_id[assignee["id"]]["peut_supprimer"] is False

    # Classer : statut, priorité, échéance.
    r = client.patch(
        f"/api/v1/entreprises/mes-taches/{assignee['id']}",
        headers=h,
        json={"status": "in_progress", "priority": "urgent", "due_date": "2026-10-10"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"
    assert r.json()["due_date"] == "2026-10-10"

    # Terminer → completed_at posé, disparaît de la liste sans include_done.
    r = client.patch(
        f"/api/v1/entreprises/mes-taches/{assignee['id']}", headers=h, json={"status": "done"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["completed_at"] is not None
    ids = {t["id"] for t in client.get("/api/v1/entreprises/mes-taches", headers=h).json()}
    assert assignee["id"] not in ids
    ids = {
        t["id"]
        for t in client.get(
            "/api/v1/entreprises/mes-taches?include_done=true", headers=h
        ).json()
    }
    assert assignee["id"] in ids

    # Une tâche assignée par un gestionnaire ne se supprime pas d'ici.
    r = client.delete(f"/api/v1/entreprises/mes-taches/{assignee['id']}", headers=h)
    assert r.status_code == 403, r.text
    # La sienne, oui.
    r = client.delete(f"/api/v1/entreprises/mes-taches/{mienne['id']}", headers=h)
    assert r.status_code == 204, r.text
    r = client.get("/api/v1/entreprises/mes-taches?include_done=true", headers=h)
    assert mienne["id"] not in {t["id"] for t in r.json()}

    # Les tâches des autres n'existent pas pour lui.
    r = client.patch(
        f"/api/v1/entreprises/mes-taches/{assignee['id']}",
        headers=employee_headers,
        json={"status": "todo"},
    )
    assert r.status_code in (403, 404), r.text  # 403 = pas le pôle Entreprises

    # Entreprise inconnue refusée.
    r = client.post(
        "/api/v1/entreprises/mes-taches",
        headers=h,
        json={"title": "x", "entreprise_id": 999999},
    )
    assert r.status_code == 400, r.text


def test_mes_taches_exige_le_pole_entreprises(client, employee_headers):
    # L'employé Construction par défaut n'a pas le pôle Entreprises.
    r = client.get("/api/v1/entreprises/mes-taches", headers=employee_headers)
    assert r.status_code == 403, r.text


# ── Section Employés ────────────────────────────────────────────────────


def test_section_employes_reservee_aux_gestionnaires(client, video):
    r = client.get("/api/v1/entreprises/employes", headers=video["headers"])
    assert r.status_code == 403, r.text


def test_equipe_et_types(client, auth_headers, video, employee_id):
    r = client.get("/api/v1/entreprises/employes", headers=auth_headers)
    assert r.status_code == 200, r.text
    par_id = {u["id"]: u for u in r.json()}
    assert par_id[video["id"]]["type"] == "autre"
    assert par_id[video["id"]]["display_name"] == "Vicky Vidéo"
    assert par_id[video["id"]]["volets"] == ["entreprises"]
    # L'employé par défaut a les volets historiques (construction…).
    assert par_id[employee_id]["type"] == "construction"


def test_agenda_planifie_visible_dans_la_zone(client, auth_headers, video):
    h = video["headers"]
    start = datetime.now(timezone.utc) + timedelta(days=3)
    r = client.post(
        f"/api/v1/entreprises/employes/{video['id']}/agenda",
        headers=auth_headers,
        json={
            "title": "Tournage capsule MGV",
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=3)).isoformat(),
            "event_type": "tournage",
            "location": "Bureau",
        },
    )
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev["scope"] == "entreprises"
    assert ev["event_type"] == "tournage"
    assert ev["modifiable"] is True

    # Fin avant début / type inconnu → refusés.
    r = client.post(
        f"/api/v1/entreprises/employes/{video['id']}/agenda",
        headers=auth_headers,
        json={"title": "x", "start_at": start.isoformat(),
              "end_at": (start - timedelta(hours=1)).isoformat()},
    )
    assert r.status_code == 400, r.text
    r = client.post(
        f"/api/v1/entreprises/employes/{video['id']}/agenda",
        headers=auth_headers,
        json={"title": "x", "start_at": start.isoformat(), "event_type": "chantier"},
    )
    assert r.status_code == 422, r.text

    # L'employé le voit dans sa zone employés (agenda mobile) et est notifié.
    r = client.get("/api/v1/mobile/agenda?days=30", headers=h)
    assert r.status_code == 200, r.text
    vu = next(e for e in r.json() if e["id"] == ev["id"])
    assert vu["event_type"] == "tournage"
    r = client.get("/api/v1/notifications", headers=h)
    assert r.status_code == 200, r.text
    assert any(n["kind"] == "agenda.planifie" for n in r.json())

    # Et dans l'agenda de son téléphone (flux ICS), même sans fiche
    # Employé Construction.
    r = client.get("/api/v1/calendar/my-agenda-url", headers=h)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    r = client.get(f"/api/v1/calendar/my-agenda.ics?token={token}")
    assert r.status_code == 200, r.text
    assert f"UID:agenda-{ev['id']}@" in r.text
    assert "Tournage capsule MGV" in r.text

    # Le gestionnaire le retrouve dans l'agenda de l'employé, avec prochain
    # événement sur la fiche d'équipe.
    r = client.get(f"/api/v1/entreprises/employes/{video['id']}/agenda", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert ev["id"] in {e["id"] for e in r.json()}
    equipe = client.get("/api/v1/entreprises/employes", headers=auth_headers).json()
    fiche = next(u for u in equipe if u["id"] == video["id"])
    assert fiche["prochain_evenement"] is not None
    assert fiche["prochain_evenement"]["id"] == ev["id"]

    # Modifier puis supprimer.
    r = client.patch(
        f"/api/v1/entreprises/employes/agenda/{ev['id']}",
        headers=auth_headers,
        json={"title": "Tournage capsule MGV (reporté)", "event_type": "reunion"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Tournage capsule MGV (reporté)"
    assert r.json()["event_type"] == "reunion"

    # Un événement de l'agenda Construction ne se modifie pas d'ici.
    r = client.post(
        "/api/v1/agenda",
        headers=auth_headers,
        json={"title": "Chantier smoke zone", "start_at": start.isoformat()},
    )
    assert r.status_code == 201, r.text
    r = client.patch(
        f"/api/v1/entreprises/employes/agenda/{r.json()['id']}",
        headers=auth_headers,
        json={"title": "nope"},
    )
    assert r.status_code == 403, r.text

    r = client.delete(f"/api/v1/entreprises/employes/agenda/{ev['id']}", headers=auth_headers)
    assert r.status_code == 204, r.text
    r = client.get("/api/v1/mobile/agenda?days=30", headers=h)
    assert ev["id"] not in {e["id"] for e in r.json()}


def test_suivi_du_temps(client, auth_headers, video):
    h = video["headers"]
    # L'employé remplit sa feuille de la période courante : 3 h le jour 0.
    r = client.get("/api/v1/timesheets/resolve", headers=h)
    assert r.status_code == 200, r.text
    ts = r.json()
    cie = ts["lignes"][0]["company_id"]
    r = client.put(
        f"/api/v1/timesheets/{ts['id']}/taches",
        headers=h,
        json={"lignes": [{"day_index": 0, "company_id": cie, "title": "Montage", "hours": 3}]},
    )
    assert r.status_code == 200, r.text

    debut = date.fromisoformat(ts["period_start"])
    fin = debut + timedelta(days=13)
    r = client.get(
        f"/api/v1/entreprises/employes/suivi-temps?debut={debut}&fin={fin}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    suivi = r.json()
    ligne = next(l for l in suivi["lignes"] if l["user_id"] == video["id"])
    assert ligne["heures_feuille"] == 3.0
    assert ligne["heures_punch"] == 0.0
    assert ligne["heures_total"] == 3.0
    assert ligne["jours_travailles"] == 1
    assert suivi["total_heures"] >= 3.0

    # Sans plage → période de paie courante, même résultat pour lui.
    r = client.get("/api/v1/entreprises/employes/suivi-temps", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["debut"] == ts["period_start"]
    ligne = next(l for l in r.json()["lignes"] if l["user_id"] == video["id"])
    assert ligne["heures_feuille"] == 3.0

    # La fiche d'équipe reflète les heures de la période courante.
    equipe = client.get("/api/v1/entreprises/employes", headers=auth_headers).json()
    fiche = next(u for u in equipe if u["id"] == video["id"])
    assert fiche["heures_periode"] == 3.0
    assert fiche["feuille_statut"] == ts["status"]

    r = client.get(
        "/api/v1/entreprises/employes/suivi-temps?debut=2026-02-01&fin=2026-01-01",
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_suivi_du_temps_punch_jour_local(client, auth_headers, run):
    """Un punch Construction de 21 h (heure de Montréal) compte pour SON
    jour, même s'il tombe le lendemain en UTC."""
    from zoneinfo import ZoneInfo

    from app.models.employe import Employe
    from app.models.punch import Punch

    mtl = ZoneInfo("America/Toronto")
    jour = date(2026, 3, 10)
    debut_punch = datetime(2026, 3, 10, 21, 0, tzinfo=mtl)

    async def _seed():
        async with TestSessionLocal() as s:
            u = User(
                email="punch.zone@example.com",
                hashed_password=get_password_hash("x" * 12),
                is_active=True,
                is_admin=False,
                role="employee",
            )
            emp = Employe(full_name="Punch Zone", email="Punch.Zone@example.com")
            s.add_all([u, emp])
            await s.flush()
            s.add(
                Punch(
                    employe_id=emp.id,
                    started_at=debut_punch,
                    ended_at=debut_punch + timedelta(hours=2, minutes=30),
                    hours=2.5,
                )
            )
            await s.commit()
            return u.id

    uid = run(_seed())
    r = client.get(
        f"/api/v1/entreprises/employes/suivi-temps?debut={jour}&fin={jour}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    ligne = next(l for l in r.json()["lignes"] if l["user_id"] == uid)
    assert ligne["type"] == "construction"
    assert ligne["heures_punch"] == 2.5
    assert ligne["jours_travailles"] == 1
    # Le lendemain : rien.
    lendemain = jour + timedelta(days=1)
    r = client.get(
        f"/api/v1/entreprises/employes/suivi-temps?debut={lendemain}&fin={lendemain}",
        headers=auth_headers,
    )
    ligne = next(l for l in r.json()["lignes"] if l["user_id"] == uid)
    assert ligne["heures_punch"] == 0.0


# ── Aperçu « voir comme » (lecture seule) ───────────────────────────────


def _apercu(client, auth_headers, user_id: int) -> dict:
    """Jeton d'aperçu admin → ``user_id``, en en-tête Bearer."""
    r = client.post(f"/api/v1/users/{user_id}/apercu", headers=auth_headers)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_apercu_zone_employes_autre(client, auth_headers, admin_id, video):
    """Un admin qui regarde Kratos comme l'employé vidéo voit sa zone
    employés (mêmes accès, mêmes lectures) sans pouvoir rien y modifier."""
    h = _apercu(client, auth_headers, video["id"])
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["id"] == video["id"]
    assert me["apercu_par"] == admin_id
    assert me["volets"] == ["entreprises"]
    assert me["access"]["page:construction.mobile"] is True
    assert me["access"].get("page:entreprises.employes") is not True

    for url in (
        "/api/v1/mobile/agenda?days=14",
        "/api/v1/entreprises/mes-taches",
        "/api/v1/entreprises/mes-taches/entreprises",
        "/api/v1/timesheets/resolve",
    ):
        r = client.get(url, headers=h)
        assert r.status_code == 200, (url, r.text)
    # La section admin reste fermée, comme pour l'employé lui-même.
    assert client.get("/api/v1/entreprises/employes", headers=h).status_code == 403

    # Lecture seule : se créer une tâche est refusé, rien n'est créé.
    avant = client.get("/api/v1/entreprises/mes-taches", headers=h).json()
    r = client.post(
        "/api/v1/entreprises/mes-taches",
        headers=h,
        json={"title": "Pendant l'aperçu", "entreprise_id": video["entreprise_id"]},
    )
    assert r.status_code == 403, r.text
    assert "aperçu" in r.json()["detail"].lower()
    apres = client.get("/api/v1/entreprises/mes-taches", headers=h).json()
    assert len(apres) == len(avant)


def test_apercu_section_employes(client, auth_headers, run, video):
    """Vu comme un autre admin : la section Entreprises → Employés se
    charge (équipe, suivi du temps, agenda, tâches, feuilles) mais
    planifier dans l'agenda d'un employé est refusé."""

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = User(
                email="admin.apercu.zone@example.com",
                hashed_password=get_password_hash("x" * 12),
                is_active=True,
                is_admin=True,
                role="admin",
                first_name="Alex",
                last_name="Aperçu",
            )
            s.add(u)
            await s.commit()
            return u.id

    autre_admin = run(_seed())
    h = _apercu(client, auth_headers, autre_admin)
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["id"] == autre_admin
    assert me["access"]["page:entreprises.employes"] is True

    for url in (
        "/api/v1/entreprises/employes",
        "/api/v1/entreprises/employes?inclure_admins=true",
        "/api/v1/entreprises/employes/suivi-temps",
        f"/api/v1/entreprises/employes/{video['id']}/agenda",
        "/api/v1/entreprises/taches",
        "/api/v1/timesheets/team",
        "/api/v1/users",
    ):
        r = client.get(url, headers=h)
        assert r.status_code == 200, (url, r.text)
    equipe = client.get("/api/v1/entreprises/employes", headers=h).json()
    assert video["id"] in {e["id"] for e in equipe}

    debut = datetime.now(timezone.utc) + timedelta(days=3)
    r = client.post(
        f"/api/v1/entreprises/employes/{video['id']}/agenda",
        headers=h,
        json={
            "title": "Tournage pendant l'aperçu",
            "start_at": debut.isoformat(),
            "end_at": (debut + timedelta(hours=2)).isoformat(),
            "event_type": "tournage",
        },
    )
    assert r.status_code == 403, r.text
    titres = {
        e["title"]
        for e in client.get(
            f"/api/v1/entreprises/employes/{video['id']}/agenda", headers=h
        ).json()
    }
    assert "Tournage pendant l'aperçu" not in titres
