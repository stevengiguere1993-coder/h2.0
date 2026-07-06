"""Smoke — authentification (login réel, mauvais mot de passe, /me)."""

from tests.smoke.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, EMPLOYEE_EMAIL


def test_login_ok(client, seeded_users):
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("access_token")
    assert body.get("token_type") == "bearer"


def test_login_bad_password_401(client, seeded_users):
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": ADMIN_EMAIL, "password": "mauvais-mot-de-passe"},
    )
    assert resp.status_code == 401


def test_login_unknown_user_401(client, seeded_users):
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": "inconnu@example.com", "password": "x" * 12},
    )
    assert resp.status_code == 401


def test_me_with_token_from_login(client, seeded_users):
    login = client.post(
        "/api/v1/auth/login",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    token = login.json()["access_token"]
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == ADMIN_EMAIL
    assert body["is_active"] is True


def test_me_without_token_401(client, seeded_users):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_employee(client, employee_headers):
    resp = client.get("/api/v1/auth/me", headers=employee_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == EMPLOYEE_EMAIL
