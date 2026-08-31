"""Smoke — ventilation du coûtant des lignes de soumission
(retour du gestionnaire de chantier, 2026-08-27) : la colonne Coût $/u
devient Coût main-d'œuvre + Coût matériaux ; le coûtant total reste la
somme (marges, agrégats et garde-fous inchangés).
"""
from __future__ import annotations

from app.models.soumission import Soumission

from .conftest import TestSessionLocal


def _seed_soumission(run) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            sou = Soumission(
                reference="SOU-VENT-1",
                title="Chantier ventilation",
            )
            s.add(sou)
            await s.flush()
            sid = sou.id
            await s.commit()
            return sid

    return run(_go())


def test_ventilation_mo_materiaux(client, auth_headers, run):
    sid = _seed_soumission(run)

    # Création avec ventilation : le coûtant total = MO + matériaux.
    r = client.post(
        f"/api/v1/soumissions/{sid}/items",
        headers=auth_headers,
        json={
            "description": "Réfection salle de bain",
            "quantity": 2,
            "unit_price": 100,
            "cost_labor_per_unit": 30,
            "cost_material_per_unit": 20,
        },
    )
    assert r.status_code in (200, 201), r.text
    item = r.json()
    assert item["cost_labor_per_unit"] == 30
    assert item["cost_material_per_unit"] == 20
    assert item["cost_per_unit"] == 50

    # Modifier UNE des deux composantes recalcule le total.
    r2 = client.patch(
        f"/api/v1/soumissions/{sid}/items/{item['id']}",
        headers=auth_headers,
        json={"cost_material_per_unit": 25},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["cost_per_unit"] == 55

    # Une ligne à l'ancienne (coûtant direct, sans ventilation) reste
    # valide : total conservé, composantes vides.
    r3 = client.post(
        f"/api/v1/soumissions/{sid}/items",
        headers=auth_headers,
        json={
            "description": "Ligne historique",
            "quantity": 1,
            "unit_price": 80,
            "cost_per_unit": 40,
        },
    )
    assert r3.status_code in (200, 201), r3.text
    ancien = r3.json()
    assert ancien["cost_per_unit"] == 40
    assert ancien["cost_labor_per_unit"] is None
    assert ancien["cost_material_per_unit"] is None
