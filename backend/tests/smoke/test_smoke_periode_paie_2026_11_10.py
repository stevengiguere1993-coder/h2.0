"""Smoke — période de paie réglable (Steven, 2026-11-10).

« Choisir la fréquence de période de paie et de quel jour à quel jour […]
selon le système de paie on est du lundi au dimanche […] la paie est rendue
à la semaine. » Le rapport de paie suit le réglage.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.models.employe import Employe
from app.services import periode_paie
from app.services.punch_diner import MONTREAL, aujourd_hui_local

from tests.smoke.conftest import TestSessionLocal


def _iso(jour: date, h: int) -> str:
    return datetime.combine(jour, time(h), tzinfo=MONTREAL).astimezone(timezone.utc).isoformat()


# ── Calcul des périodes ─────────────────────────────────────────────────


def test_defaut_ancien_cycle_dimanche_samedi_aux_2_semaines():
    r = periode_paie.normaliser({})
    p = periode_paie.periode_contenant(date(2026, 4, 25), r)
    assert (p.debut, p.fin) == (date(2026, 4, 19), date(2026, 5, 2))
    assert p.versement == date(2026, 5, 7)
    assert len(p.semaines) == 2
    assert r.libelle_jours == "dimanche → samedi"


def test_hebdomadaire_lundi_dimanche():
    r = periode_paie.normaliser(
        {"frequence": "hebdomadaire", "jour_debut": 0, "debut_reference": "2026-11-11"}
    )
    # Référence ramenée sur le lundi précédent.
    assert r.debut_reference == date(2026, 11, 9)
    p = periode_paie.periode_contenant(date(2026, 11, 15), r)
    assert (p.debut, p.fin) == (date(2026, 11, 9), date(2026, 11, 15))
    assert len(p.semaines) == 1
    assert p.semaine_de(date(2026, 11, 15)) == 0
    # Le passé et le futur suivent la même grille.
    assert periode_paie.periode_contenant(date(2026, 1, 1), r).debut == date(2025, 12, 29)
    assert r.libelle_jours == "lundi → dimanche"


def test_periode_a_afficher_garde_la_precedente_jusquau_versement():
    r = periode_paie.normaliser(
        {"frequence": "hebdomadaire", "jour_debut": 0, "debut_reference": "2026-11-09",
         "jours_versement": 4}
    )
    # Mardi 17 : la semaine du 9 au 15 n'est pas encore versée (jeudi 19).
    assert periode_paie.periode_a_afficher(date(2026, 11, 17), r).debut == date(2026, 11, 9)
    assert periode_paie.periode_a_afficher(date(2026, 11, 20), r).debut == date(2026, 11, 16)


def test_config_invalide_retombe_sur_le_defaut():
    r = periode_paie.normaliser({"frequence": "mensuelle", "jour_debut": 9, "debut_reference": "x"})
    assert r.frequence == "aux_2_semaines" and r.jour_debut == 6
    assert r.debut_reference == periode_paie.DEBUT_REFERENCE_HISTORIQUE


# ── API ─────────────────────────────────────────────────────────────────


def test_reglages_et_rapport_hebdomadaire(client, auth_headers, run):
    r = client.get("/api/v1/punch/payroll/reglages", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.put(
        "/api/v1/punch/payroll/reglages",
        headers=auth_headers,
        json={"frequence": "hebdomadaire", "jour_debut": 0, "jours_coupure": 1,
              "jours_versement": 4},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["libelle_jours"] == "lundi → dimanche"
    assert body["jours_periode"] == 7
    debut = date.fromisoformat(body["periode_courante"]["debut"])
    assert debut.weekday() == 0
    assert debut <= aujourd_hui_local() <= debut + timedelta(days=6)

    # Un punch le dimanche soir (heure de Montréal) reste dans la semaine
    # qui finit ce dimanche, même s'il est lundi en UTC.
    dimanche = debut + timedelta(days=6)

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            e = Employe(full_name="Paie Hebdo")
            s.add(e)
            await s.commit()
            return e.id

    emp_id = run(_seed())
    r = client.post(
        "/api/v1/punch",
        headers=auth_headers,
        json={"employe_id": emp_id, "started_at": _iso(dimanche, 20),
              "ended_at": _iso(dimanche, 23)},
    )
    assert r.status_code == 201, r.text

    r = client.get(
        f"/api/v1/punch/payroll/bi-weekly?period_end={dimanche.isoformat()}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["period_start"] == debut.isoformat()
    assert rep["period_end"] == dimanche.isoformat()
    assert rep["nb_semaines"] == 1 and rep["week_2_start"] is None
    ligne = next(x for x in rep["rows"] if x["employe_id"] == emp_id)
    assert ligne["hours_week_1"] == 3.0 and ligne["hours_week_2"] == 0.0

    r = client.get(
        f"/api/v1/punch/payroll/bi-weekly.csv?period_end={dimanche.isoformat()}",
        headers=auth_headers,
    )
    assert r.status_code == 200 and '"Paie Hebdo",3.0,0.0' in r.text

    # Remise au cycle d'origine pour les autres tests.
    r = client.put(
        "/api/v1/punch/payroll/reglages",
        headers=auth_headers,
        json={"frequence": "aux_2_semaines", "jour_debut": 6,
              "debut_reference": "2026-04-19", "jours_coupure": 3, "jours_versement": 5},
    )
    assert r.status_code == 200, r.text
    assert r.json()["debut_reference"] == "2026-04-19"


def test_reglages_reserves_admin(client, employee_headers):
    r = client.put(
        "/api/v1/punch/payroll/reglages",
        headers=employee_headers,
        json={"frequence": "hebdomadaire", "jour_debut": 0},
    )
    assert r.status_code in (401, 403)
