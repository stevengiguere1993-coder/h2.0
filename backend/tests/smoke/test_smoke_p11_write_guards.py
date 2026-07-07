"""Smoke — durcissement des écritures destructives (P-11).

- ``delete_project`` est désormais réservé aux managers+ (auparavant
  ouvert à TOUT compte connecté, garde manquante) : un employé → 403.
  La garde tranche avant le lookup, donc un id inexistant renvoie quand
  même 403 (on teste bien l'autorisation, pas la présence).
- Les lignes d'une facture PAYÉE ne sont plus modifiables : ajouter une
  ligne à une facture payée → 409 (intégrité comptable).
"""

import uuid

from app.models.facture import Facture, FactureStatus

from tests.smoke.conftest import TestSessionLocal


def test_employee_cannot_delete_project(client, employee_headers):
    resp = client.delete("/api/v1/projects/999999", headers=employee_headers)
    assert resp.status_code == 403, resp.text


def _seed_paid_facture(run) -> int:
    async def _seed() -> int:
        async with TestSessionLocal() as session:
            fac = Facture(
                reference=f"FAC-SMK-{uuid.uuid4().hex[:10]}",
                status=FactureStatus.PAID.value,
            )
            session.add(fac)
            await session.commit()
            return int(fac.id)

    return run(_seed())


def test_cannot_add_line_to_paid_facture(client, auth_headers, run):
    fid = _seed_paid_facture(run)
    resp = client.post(
        f"/api/v1/factures/{fid}/items",
        headers=auth_headers,
        json={"description": "Ligne interdite sur facture payée"},
    )
    assert resp.status_code == 409, resp.text
