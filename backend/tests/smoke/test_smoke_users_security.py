"""Smoke tests sécurité comptes (gestion des utilisateurs + punch/debug).

Vérifie les gardes de rang ajoutées sur les endpoints admin :

- set-password : un admin NE PEUT PAS agir sur un compte de rang
  supérieur (owner) → 403 ; mais peut agir sur un employé → 200.
- create_user : un admin NE PEUT PAS créer un compte de rang supérieur
  (owner) → 403 ; mais peut créer un employé / manager → 201.
- GET /punch/debug (dump PII des fiches employé) est réservé aux admins :
  un employé standard → 403.

Réutilise les fixtures de ``conftest.py`` (client, auth_headers,
employee_headers, employee_id, run). Un owner supplémentaire est semé
directement en DB pour le cas d'escalade.
"""

from __future__ import annotations

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.user import User

from .conftest import TestSessionLocal

OWNER_EMAIL = "smoke-owner@example.com"
OWNER_PASSWORD = "Sm0keOwner!42"


@pytest.fixture(scope="session")
def owner_id(run, seeded_users) -> int:
    """Sème un owner en DB (le conftest n'en fournit pas) pour tester la
    garde de rang admin→owner."""

    async def _seed() -> int:
        async with TestSessionLocal() as session:
            owner = User(
                email=OWNER_EMAIL,
                hashed_password=get_password_hash(OWNER_PASSWORD),
                is_active=True,
                is_admin=True,
                role="owner",
            )
            session.add(owner)
            await session.flush()
            oid = owner.id
            await session.commit()
            return oid

    return run(_seed())


def test_admin_cannot_set_password_on_owner(client, auth_headers, owner_id):
    """Escalade interdite : un admin qui vise un owner → 403."""
    resp = client.post(
        f"/api/v1/users/{owner_id}/set-password",
        headers=auth_headers,
        json={
            "password": "N0uveauMdp!99",
            "must_change": True,
            # Pas d'envoi de courriel dans les tests (pas de mailer).
            "send_email": False,
        },
    )
    assert resp.status_code == 403, resp.text


def test_admin_can_set_password_on_employee(
    client, auth_headers, employee_id
):
    """Flux légitime inchangé : un admin agit sur un employé → 200."""
    resp = client.post(
        f"/api/v1/users/{employee_id}/set-password",
        headers=auth_headers,
        json={
            "password": "N0uveauMdp!77",
            "must_change": True,
            "send_email": False,
        },
    )
    assert resp.status_code == 200, resp.text


def test_admin_cannot_create_owner(client, auth_headers):
    """Escalade interdite : un admin qui tente de CRÉER un compte owner
    (rang supérieur au sien) → 403. Aucun compte ne doit être créé."""
    resp = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "smoke-newowner@example.com",
            "role": "owner",
            "full_name": "Nouvel Owner",
        },
    )
    assert resp.status_code == 403, resp.text


def test_admin_can_create_employee(client, auth_headers):
    """Flux légitime : un admin crée un employé (rang inférieur) → 201."""
    resp = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "smoke-newemployee@example.com",
            "role": "employee",
        },
    )
    assert resp.status_code == 201, resp.text


def test_admin_can_create_manager(client, auth_headers):
    """Un admin (rang 3) peut créer un manager (rang 2 < 3) → 201."""
    resp = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "smoke-newmanager@example.com",
            "role": "manager",
        },
    )
    assert resp.status_code == 201, resp.text


def test_punch_debug_forbidden_for_employee(client, employee_headers):
    """GET /punch/debug expose des PII : interdit à un employé → 403."""
    resp = client.get("/api/v1/punch/debug", headers=employee_headers)
    assert resp.status_code == 403, resp.text
