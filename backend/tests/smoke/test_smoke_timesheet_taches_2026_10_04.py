"""Smoke — feuille de temps par tâche (Steven 2026-10-04).

L'employé importe ses tâches Gestion d'entreprises (ou en saisit à la
main), choisit la journée, la compagnie et les heures ; la grille
compagnie × jour en est dérivée. Un gestionnaire peut réimputer une ligne
à une autre compagnie, et limiter les compagnies visibles d'un employé.
"""
from __future__ import annotations

from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache

from tests.smoke.conftest import TestSessionLocal


def _ligne(detail, company_id):
    return next(l for l in detail["lignes"] if l["company_id"] == company_id)


def test_feuille_par_tache(client, auth_headers, employee_headers, employee_id, run):
    async def _seed():
        async with TestSessionLocal() as s:
            e = Entreprise(name="Horizon Vidéo Test")
            s.add(e)
            await s.flush()
            t = EntrepriseTache(
                entreprise_id=e.id,
                title="Montage vidéo chantier",
                assignee_user_id=employee_id,
            )
            autre = EntrepriseTache(entreprise_id=e.id, title="Pas à moi")
            s.add_all([t, autre])
            await s.commit()
            return e.id, t.id

    ent_id, tache_id = run(_seed())

    r = client.get("/api/v1/timesheets/resolve", headers=employee_headers)
    assert r.status_code == 200, r.text
    ts = r.json()
    assert ts["mode_taches"] is False
    tsid = ts["id"]

    # Import : seule la tâche assignée remonte, avec sa compagnie miroir.
    r = client.get(
        f"/api/v1/timesheets/{tsid}/taches-importables", headers=employee_headers
    )
    assert r.status_code == 200, r.text
    imp = r.json()
    assert [t["id"] for t in imp] == [tache_id]
    cie = imp[0]["company_id"]
    assert cie is not None
    autre_cie = next(l["company_id"] for l in ts["lignes"] if l["company_id"] != cie)

    r = client.put(
        f"/api/v1/timesheets/{tsid}/taches",
        headers=employee_headers,
        json={
            "lignes": [
                {"day_index": 0, "company_id": cie, "entreprise_tache_id": tache_id,
                 "title": "Montage vidéo chantier", "hours": 3},
                {"day_index": 0, "company_id": cie, "title": "Tournage", "hours": 2.5},
                {"day_index": 2, "company_id": autre_cie, "title": "Meeting", "hours": 1},
            ]
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mode_taches"] is True
    assert len(d["taches"]) == 3
    assert _ligne(d, cie)["jours"][0] == 5.5
    assert d["total_heures"] == 6.5

    # La grille ne s'édite plus directement en mode tâches.
    r = client.put(
        f"/api/v1/timesheets/{tsid}/entries",
        headers=employee_headers,
        json={"entries": [{"company_id": cie, "day_index": 5, "hours": 8}]},
    )
    assert r.status_code == 200
    assert r.json()["total_heures"] == 6.5

    # Le gestionnaire réimpute « Meeting » à la première compagnie.
    lignes = [
        {k: t[k] for k in ("day_index", "company_id", "entreprise_tache_id", "title", "hours")}
        for t in d["taches"]
    ]
    for l in lignes:
        if l["title"] == "Meeting":
            l["company_id"] = cie
    r = client.put(
        f"/api/v1/timesheets/{tsid}/taches", headers=auth_headers, json={"lignes": lignes}
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert _ligne(d, cie)["total"] == 6.5
    assert _ligne(d, autre_cie)["total"] == 0

    # Compagnies assignées : l'employé ne voit plus que la sienne.
    r = client.put(
        "/api/v1/timesheets/user-companies",
        headers=auth_headers,
        json={"user_id": employee_id, "company_ids": [cie]},
    )
    assert r.status_code == 200, r.text
    r = client.put(
        "/api/v1/timesheets/user-companies",
        headers=employee_headers,
        json={"user_id": employee_id, "company_ids": []},
    )
    assert r.status_code == 403
    d = client.get(f"/api/v1/timesheets/{tsid}", headers=employee_headers).json()
    # autre_cie reste visible (déjà utilisée dans la grille ? non : plus de
    # lignes dessus) → seule la compagnie assignée.
    assert [l["company_id"] for l in d["lignes"]] == [cie]
    r = client.put(
        f"/api/v1/timesheets/{tsid}/taches",
        headers=employee_headers,
        json={"lignes": [{"day_index": 1, "company_id": autre_cie, "title": "x", "hours": 1}]},
    )
    assert r.status_code == 400

    # Remise à zéro de l'assignation.
    client.put(
        "/api/v1/timesheets/user-companies",
        headers=auth_headers,
        json={"user_id": employee_id, "company_ids": []},
    )


def test_garde_fous_lignes_et_grille(client, auth_headers, employee_headers, employee_id, run):
    """Retours de relecture : la grille obéit aux compagnies assignées, une
    tâche référencée doit exister et être assignée à l'employé, et des
    titres blancs ne vident pas une feuille saisie par la grille."""
    async def _seed():
        async with TestSessionLocal() as s:
            e = Entreprise(name="Horizon Garde-fous Test")
            s.add(e)
            await s.flush()
            autre = EntrepriseTache(entreprise_id=e.id, title="Tâche d'un collègue")
            s.add(autre)
            await s.commit()
            return autre.id

    tache_collegue = run(_seed())

    # Feuille d'une AUTRE période (vierge), saisie par la grille.
    r = client.get(
        "/api/v1/timesheets/resolve?period_start=2026-03-02", headers=employee_headers
    )
    assert r.status_code == 200, r.text
    ts = r.json()
    tsid = ts["id"]
    cie, autre_cie = ts["lignes"][0]["company_id"], ts["lignes"][1]["company_id"]

    r = client.put(
        f"/api/v1/timesheets/{tsid}/entries",
        headers=employee_headers,
        json={"entries": [{"company_id": cie, "day_index": 0, "hours": 8}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["total_heures"] == 8

    # Des lignes au titre blanc n'effacent pas la grille.
    r = client.put(
        f"/api/v1/timesheets/{tsid}/taches",
        headers=employee_headers,
        json={"lignes": [{"day_index": 0, "company_id": cie, "title": "   ", "hours": 3}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["total_heures"] == 8
    assert r.json()["mode_taches"] is False

    # Tâche inexistante ou non assignée à l'employé : la ligne est gardée
    # comme tâche manuelle (pas de 500, pas de lien vers la tâche d'autrui).
    for tid in (999_999_999, tache_collegue):
        r = client.put(
            f"/api/v1/timesheets/{tsid}/taches",
            headers=employee_headers,
            json={"lignes": [{"day_index": 0, "company_id": cie,
                              "entreprise_tache_id": tid, "title": "x", "hours": 1}]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["taches"][0]["entreprise_tache_id"] is None
        assert r.json()["total_heures"] == 1
    # Le gestionnaire peut référencer une tâche existante de quelqu'un d'autre.
    r = client.put(
        f"/api/v1/timesheets/{tsid}/taches",
        headers=auth_headers,
        json={"lignes": [{"day_index": 0, "company_id": cie,
                          "entreprise_tache_id": tache_collegue, "title": "x", "hours": 1}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["taches"][0]["entreprise_tache_id"] == tache_collegue
    r = client.put(
        f"/api/v1/timesheets/{tsid}/taches", headers=auth_headers, json={"lignes": []}
    )
    assert r.status_code == 200 and r.json()["total_heures"] == 0

    # Compagnies assignées : la grille refuse aussi les autres compagnies.
    r = client.put(
        "/api/v1/timesheets/user-companies",
        headers=auth_headers,
        json={"user_id": employee_id, "company_ids": [cie]},
    )
    assert r.status_code == 200, r.text
    r = client.put(
        f"/api/v1/timesheets/{tsid}/entries",
        headers=employee_headers,
        json={"entries": [{"company_id": autre_cie, "day_index": 1, "hours": 2}]},
    )
    assert r.status_code == 400, r.text
    r = client.put(
        f"/api/v1/timesheets/{tsid}/entries",
        headers=employee_headers,
        json={"entries": [{"company_id": cie, "day_index": 1, "hours": 2}]},
    )
    assert r.status_code == 200, r.text
    # Compagnie inexistante → 404 pour le gestionnaire.
    r = client.put(
        f"/api/v1/timesheets/{tsid}/entries",
        headers=auth_headers,
        json={"entries": [{"company_id": 999_999, "day_index": 1, "hours": 2}]},
    )
    assert r.status_code == 404, r.text
    client.put(
        "/api/v1/timesheets/user-companies",
        headers=auth_headers,
        json={"user_id": employee_id, "company_ids": []},
    )
