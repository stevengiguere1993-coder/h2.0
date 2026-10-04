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
