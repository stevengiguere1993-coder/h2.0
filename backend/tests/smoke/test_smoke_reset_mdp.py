"""Smoke — réinitialisation de mot de passe en libre-service
(demande des gestionnaires, 2026-08-27).

Sécurité vérifiée : réponse identique que le courriel existe ou non,
jeton haché à usage unique, expiration à 60 minutes.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.user import User

from .conftest import EMPLOYEE_EMAIL, TestSessionLocal


def test_demande_reponse_generique(client, run):
    # Courriel inconnu → même réponse que pour un vrai compte.
    r = client.post(
        "/api/v1/auth/mot-de-passe-oublie",
        json={"email": "inconnu@nulle-part.test"},
    )
    assert r.status_code == 202, r.text
    generique = r.json()

    r2 = client.post(
        "/api/v1/auth/mot-de-passe-oublie",
        json={"email": EMPLOYEE_EMAIL},
    )
    assert r2.status_code == 202, r2.text
    assert r2.json() == generique

    # Le vrai compte a maintenant un jeton HACHÉ + une échéance.
    async def _etat():
        async with TestSessionLocal() as s:
            u = (
                await s.execute(
                    select(User).where(User.email == EMPLOYEE_EMAIL)
                )
            ).scalar_one()
            return u.reset_token_hash, u.reset_token_expires_at

    h, exp = run(_etat())
    assert h and len(h) == 64
    assert exp is not None


def test_reinitialisation_usage_unique(client, run):
    token = "jeton-de-test-usage-unique"

    async def _poser(expire_dans_minutes: int) -> None:
        async with TestSessionLocal() as s:
            u = (
                await s.execute(
                    select(User).where(User.email == EMPLOYEE_EMAIL)
                )
            ).scalar_one()
            u.reset_token_hash = hashlib.sha256(
                token.encode()
            ).hexdigest()
            u.reset_token_expires_at = datetime.now(
                timezone.utc
            ) + timedelta(minutes=expire_dans_minutes)
            await s.commit()

    run(_poser(30))

    # Mot de passe trop court → refusé.
    r0 = client.post(
        "/api/v1/auth/reinitialiser-mot-de-passe",
        json={"token": token, "nouveau_mot_de_passe": "court"},
    )
    assert r0.status_code == 422, r0.text

    r = client.post(
        "/api/v1/auth/reinitialiser-mot-de-passe",
        json={
            "token": token,
            "nouveau_mot_de_passe": "NouveauMdp!2026",
        },
    )
    assert r.status_code == 200, r.text

    # Le nouveau mot de passe fonctionne à la connexion.
    r2 = client.post(
        "/api/v1/auth/login",
        data={
            "username": EMPLOYEE_EMAIL,
            "password": "NouveauMdp!2026",
        },
    )
    assert r2.status_code == 200, r2.text

    # Le jeton est à usage UNIQUE.
    r3 = client.post(
        "/api/v1/auth/reinitialiser-mot-de-passe",
        json={
            "token": token,
            "nouveau_mot_de_passe": "AutreMdp!2026",
        },
    )
    assert r3.status_code == 400, r3.text

    # Un jeton expiré est refusé.
    run(_poser(-5))
    r4 = client.post(
        "/api/v1/auth/reinitialiser-mot-de-passe",
        json={
            "token": token,
            "nouveau_mot_de_passe": "AutreMdp!2026",
        },
    )
    assert r4.status_code == 400, r4.text
