"""Smoke — punch de la feuille de temps (bug 16, Steven 2026-10-18).

L'employé « autre » (pôle Entreprises, sans fiche Employé Construction)
punche sur une compagnie et une tâche de sa feuille : l'arrêt ajoute la
durée à la ligne du jour (même tâche → même ligne). Pas de soumission ni
d'approbation tant qu'un punch court ; une feuille saisie par compagnie
garde ses heures ; un punch oublié se corrige (heure de fin, plafond de
24 h) ; un gestionnaire voit et arrête le punch d'un employé.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import update

from app.core.security import create_access_token, get_password_hash
from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache
from app.models.timesheet import TimesheetPunch
from app.models.user import User

from tests.smoke.conftest import TestSessionLocal

MTL = ZoneInfo("America/Toronto")

#: Mardi 2026-03-03, 9 h (Montréal) : période du 2026-02-23 au 2026-03-08,
#: jour 8. Une date passée fixe rend le test indépendant de l'heure.
T0 = datetime(2026, 3, 3, 9, 0, tzinfo=MTL).astimezone(timezone.utc)
#: Mardi 2026-04-07, 10 h : période du 2026-04-06, jour 1.
T1 = datetime(2026, 4, 7, 10, 0, tzinfo=MTL).astimezone(timezone.utc)


@pytest.fixture(scope="module")
def video(run) -> dict:
    """Employé « autre » avec une tâche assignée dans son entreprise."""

    async def _seed():
        async with TestSessionLocal() as s:
            u = User(
                email="punch.video@example.com",
                hashed_password=get_password_hash("x" * 12),
                is_active=True,
                is_admin=False,
                role="employee",
                volets_json='["entreprises"]',
                first_name="Paul",
                last_name="Punch",
            )
            e = Entreprise(name="Horizon Médias Punch")
            s.add_all([u, e])
            await s.flush()
            t = EntrepriseTache(
                entreprise_id=e.id, title="Montage capsule", assignee_user_id=u.id
            )
            s.add(t)
            await s.commit()
            return {"id": u.id, "tache_id": t.id}

    ids = run(_seed())
    token = create_access_token(subject=str(ids["id"]))
    return {**ids, "headers": {"Authorization": f"Bearer {token}"}}


def _deplacer_debut(run, user_id: int, debut: datetime) -> None:
    """Fait comme si le punch ouvert avait commencé à ``debut``."""

    async def _go():
        async with TestSessionLocal() as s:
            await s.execute(
                update(TimesheetPunch)
                .where(
                    TimesheetPunch.user_id == user_id,
                    TimesheetPunch.ended_at.is_(None),
                )
                .values(started_at=debut)
            )
            await s.commit()

    run(_go())


def _compagnie(client, video) -> int:
    """Compagnie miroir de l'entreprise de la tâche assignée."""
    ts = client.get("/api/v1/timesheets/resolve", headers=video["headers"]).json()
    imp = client.get(
        f"/api/v1/timesheets/{ts['id']}/taches-importables", headers=video["headers"]
    ).json()
    cie = next(t["company_id"] for t in imp if t["id"] == video["tache_id"])
    assert cie is not None
    return cie


def test_punch_cycle_et_fusion(client, auth_headers, video, run):
    h = video["headers"]
    cie = _compagnie(client, video)

    r = client.get("/api/v1/timesheets/punch", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["en_cours"] is None

    # Sans tâche ni titre : refusé.
    r = client.post("/api/v1/timesheets/punch/start", headers=h, json={"company_id": cie})
    assert r.status_code == 422, r.text
    # Compagnie absente de sa feuille : refusé.
    r = client.post(
        "/api/v1/timesheets/punch/start",
        headers=h,
        json={"company_id": 999_999, "title": "x"},
    )
    assert r.status_code == 400, r.text

    # Tâche assignée : le titre vient de la tâche.
    r = client.post(
        "/api/v1/timesheets/punch/start",
        headers=h,
        json={"company_id": cie, "entreprise_tache_id": video["tache_id"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Montage capsule"
    assert r.json()["company_label"]
    r = client.post(
        "/api/v1/timesheets/punch/start", headers=h, json={"company_id": cie, "title": "y"}
    )
    assert r.status_code == 409

    en_cours = client.get("/api/v1/timesheets/punch", headers=h).json()["en_cours"]
    assert en_cours["title"] == "Montage capsule"
    assert en_cours["ended_at"] is None

    # Le punch a commencé le 2026-03-03 à 9 h : la feuille de cette
    # période ne se soumet pas tant qu'il court.
    _deplacer_debut(run, video["id"], T0)
    feuille = client.get(
        "/api/v1/timesheets/resolve?period_start=2026-03-03", headers=h
    ).json()
    assert feuille["period_start"] == "2026-02-23"
    r = client.post(f"/api/v1/timesheets/{feuille['id']}/submit", headers=h)
    assert r.status_code == 409, r.text
    assert "punch" in r.json()["detail"]

    r = client.post(
        "/api/v1/timesheets/punch/stop",
        headers=h,
        json={"fin": (T0 + timedelta(hours=2, minutes=30)).isoformat()},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["heures_ajoutees"] == 2.5
    assert out["punch"]["hours"] == 2.5
    assert out["feuille"]["id"] == feuille["id"]
    assert out["feuille"]["mode_taches"] is True
    (ligne,) = out["feuille"]["taches"]
    assert ligne["day_index"] == 8
    assert ligne["entreprise_tache_id"] == video["tache_id"]
    assert ligne["hours"] == 2.5
    assert out["feuille"]["total_heures"] == 2.5
    assert client.get("/api/v1/timesheets/punch", headers=h).json()["en_cours"] is None

    # Même tâche, même jour : les heures s'ajoutent à la même ligne.
    r = client.post(
        "/api/v1/timesheets/punch/start",
        headers=h,
        json={"company_id": cie, "entreprise_tache_id": video["tache_id"]},
    )
    assert r.status_code == 201, r.text
    _deplacer_debut(run, video["id"], T0 + timedelta(hours=3))
    r = client.post(
        "/api/v1/timesheets/punch/stop",
        headers=h,
        json={"fin": (T0 + timedelta(hours=4)).isoformat()},
    )
    assert r.status_code == 200, r.text
    (ligne,) = r.json()["feuille"]["taches"]
    assert ligne["hours"] == 3.5

    # Tâche saisie à la main : nouvelle ligne.
    r = client.post(
        "/api/v1/timesheets/punch/start",
        headers=h,
        json={"company_id": cie, "title": "  Tournage client  "},
    )
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Tournage client"
    _deplacer_debut(run, video["id"], T0 + timedelta(hours=5))
    r = client.post(
        "/api/v1/timesheets/punch/stop",
        headers=h,
        json={"fin": (T0 + timedelta(hours=5, minutes=30)).isoformat()},
    )
    assert r.status_code == 200, r.text
    d = r.json()["feuille"]
    assert sorted((t["title"], t["hours"]) for t in d["taches"]) == [
        ("Montage capsule", 3.5),
        ("Tournage client", 0.5),
    ]
    assert d["total_heures"] == 4.0
    assert next(l for l in d["lignes"] if l["company_id"] == cie)["jours"][8] == 4.0

    # Plus de punch : la feuille se soumet.
    r = client.post(f"/api/v1/timesheets/{feuille['id']}/submit", headers=h)
    assert r.status_code == 200, r.text

    # Feuille courante soumise → pas de nouveau punch tant qu'elle n'est
    # pas rouverte.
    courante = client.get("/api/v1/timesheets/resolve", headers=h).json()
    r = client.post(f"/api/v1/timesheets/{courante['id']}/submit", headers=h)
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/timesheets/punch/start", headers=h, json={"company_id": cie, "title": "z"}
    )
    assert r.status_code == 409, r.text
    r = client.post(f"/api/v1/timesheets/{courante['id']}/reopen", headers=auth_headers)
    assert r.status_code == 200, r.text


def test_punch_garde_la_grille(client, video, run):
    """Feuille saisie par compagnie : ses heures deviennent des lignes au
    premier punch au lieu d'être effacées par la grille dérivée."""
    h = video["headers"]
    cie = _compagnie(client, video)
    ts = client.get("/api/v1/timesheets/resolve?period_start=2026-04-07", headers=h).json()
    assert ts["period_start"] == "2026-04-06"
    r = client.put(
        f"/api/v1/timesheets/{ts['id']}/entries",
        headers=h,
        json={"entries": [{"company_id": cie, "day_index": 0, "hours": 8}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["mode_taches"] is False

    r = client.post(
        "/api/v1/timesheets/punch/start", headers=h, json={"company_id": cie, "title": "Tournage"}
    )
    assert r.status_code == 201, r.text
    _deplacer_debut(run, video["id"], T1)
    r = client.post(
        "/api/v1/timesheets/punch/stop",
        headers=h,
        json={"fin": (T1 + timedelta(hours=2)).isoformat()},
    )
    assert r.status_code == 200, r.text
    d = r.json()["feuille"]
    assert d["id"] == ts["id"]
    assert d["total_heures"] == 10
    assert sorted((t["day_index"], t["title"], t["hours"]) for t in d["taches"]) == [
        (0, "Heures saisies par compagnie", 8),
        (1, "Tournage", 2),
    ]
    jours = next(l for l in d["lignes"] if l["company_id"] == cie)["jours"]
    assert jours[0] == 8 and jours[1] == 2


def test_punch_oublie_annulation_et_gestionnaire(client, auth_headers, employee_headers, video, run):
    h = video["headers"]
    cie = _compagnie(client, video)

    # Annuler un punch démarré par erreur : rien n'est ajouté.
    r = client.post(
        "/api/v1/timesheets/punch/start", headers=h, json={"company_id": cie, "title": "Erreur"}
    )
    assert r.status_code == 201, r.text
    r = client.delete("/api/v1/timesheets/punch", headers=h)
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/timesheets/punch", headers=h).json()["en_cours"] is None
    assert client.delete("/api/v1/timesheets/punch", headers=h).status_code == 404
    assert client.post("/api/v1/timesheets/punch/stop", headers=h).status_code == 404

    # Punch oublié depuis 30 h.
    r = client.post(
        "/api/v1/timesheets/punch/start", headers=h, json={"company_id": cie, "title": "Oubli"}
    )
    assert r.status_code == 201, r.text
    debut = datetime.now(timezone.utc) - timedelta(hours=30)
    _deplacer_debut(run, video["id"], debut)

    # Un gestionnaire le voit (équipe et état) ; un autre employé, non.
    r = client.get("/api/v1/entreprises/employes", headers=auth_headers)
    assert r.status_code == 200, r.text
    moi = next(e for e in r.json() if e["id"] == video["id"])
    assert moi["punch_en_cours"]["title"] == "Oubli"
    r = client.get(f"/api/v1/timesheets/punch?user_id={video['id']}", headers=auth_headers)
    assert r.json()["en_cours"]["title"] == "Oubli"
    r = client.get(f"/api/v1/timesheets/punch?user_id={video['id']}", headers=employee_headers)
    assert r.status_code == 403
    r = client.post(
        "/api/v1/timesheets/punch/stop", headers=employee_headers, json={"user_id": video["id"]}
    )
    assert r.status_code == 403

    # Pas d'approbation de la période tant qu'il court.
    jour = debut.astimezone(MTL).date().isoformat()
    feuille = client.get(f"/api/v1/timesheets/resolve?period_start={jour}", headers=h).json()
    r = client.post(f"/api/v1/timesheets/{feuille['id']}/approve", headers=auth_headers)
    assert r.status_code == 409, r.text

    # Heure de fin dans le futur, ou avant le début : refusée.
    r = client.post(
        "/api/v1/timesheets/punch/stop",
        headers=h,
        json={"fin": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()},
    )
    assert r.status_code == 400, r.text
    r = client.post(
        "/api/v1/timesheets/punch/stop",
        headers=h,
        json={"fin": (debut - timedelta(minutes=5)).isoformat()},
    )
    assert r.status_code == 400, r.text

    # Le gestionnaire l'arrête sans heure de fin : plafond de 24 h.
    r = client.post(
        "/api/v1/timesheets/punch/stop", headers=auth_headers, json={"user_id": video["id"]}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["punch"]["hours"] == 24
    assert out["heures_ajoutees"] == 24
    ligne = next(t for t in out["feuille"]["taches"] if t["title"] == "Oubli")
    assert ligne["hours"] == 24
    r = client.get("/api/v1/entreprises/employes", headers=auth_headers)
    moi = next(e for e in r.json() if e["id"] == video["id"])
    assert moi["punch_en_cours"] is None

    # Arrêté : l'approbation passe.
    r = client.post(f"/api/v1/timesheets/{feuille['id']}/approve", headers=auth_headers)
    assert r.status_code == 200, r.text
