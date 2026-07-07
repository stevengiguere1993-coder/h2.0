"""Smoke — permissions configurables (Paramètres → Permissions, phase 2A).

- GET /permissions (admin) renvoie la grille avec la capacité pilote
  `project.delete`.
- PUT /permissions/{cap} est réservé à l'owner (un admin → 403).
- La garde `require_capability` lit dynamiquement le rôle minimum : sans
  ligne en DB elle retombe sur le défaut (« manager ») ; avec une ligne
  « admin » elle renvoie « admin ». Nettoyage en fin de test pour ne pas
  polluer les autres tests (ex. la garde de delete_project du lot P-11).
"""
from sqlalchemy import delete

from app.models.role_permission import RolePermission
from app.services.permissions_service import (
    get_min_role,
    invalidate_permissions_cache,
)

from tests.smoke.conftest import TestSessionLocal


def test_get_permissions_grid(client, auth_headers):
    resp = client.get("/api/v1/permissions", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "employee" in body["roles"] and "owner" in body["roles"]
    ids = [c["capability"] for c in body["capabilities"]]
    assert "project.delete" in ids
    # Capacités sensibles branchées en 2C.
    assert "contrat_gestion.delete" in ids
    assert "contrat_gestion.template_edit" in ids
    # Suppressions immobilières branchées (défaut employé = actuel).
    assert "immeuble.delete" in ids
    assert "bail.delete" in ids
    # Chaque capacité expose un min_role valide + son défaut.
    for c in body["capabilities"]:
        assert c["min_role"] in body["roles"]
        assert c["default_min_role"] in body["roles"]


def test_set_min_role_requires_owner(client, auth_headers):
    # auth_headers = un admin (rang 3), pas owner → 403.
    resp = client.request(
        "PUT",
        "/api/v1/permissions/project.delete",
        headers=auth_headers,
        json={"min_role": "admin"},
    )
    assert resp.status_code == 403, resp.text


def test_get_min_role_is_dynamic(run):
    async def _clear():
        async with TestSessionLocal() as s:
            await s.execute(
                delete(RolePermission).where(
                    RolePermission.capability == "project.delete"
                )
            )
            await s.commit()

    try:
        run(_clear())
        invalidate_permissions_cache()
        # Sans ligne : défaut du registre.
        assert run(get_min_role("project.delete")) == "manager"

        async def _set_admin():
            async with TestSessionLocal() as s:
                s.add(
                    RolePermission(
                        capability="project.delete", min_role="admin"
                    )
                )
                await s.commit()

        run(_set_admin())
        invalidate_permissions_cache()
        assert run(get_min_role("project.delete")) == "admin"
    finally:
        # Restaure l'état par défaut pour les autres tests.
        run(_clear())
        invalidate_permissions_cache()
