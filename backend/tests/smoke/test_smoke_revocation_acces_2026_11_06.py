"""Smoke — révocation complète des accès d'un compte désactivé (2026-11-06).

Phil, après le renvoi d'un employé : « peux-tu me confirmer qu'il n'a plus
accès à rien du tout ? ». Un compte désactivé est refusé partout (JWT et clé
d'API), mais ses appareils restaient abonnés aux notifications push : une
tâche assignée pouvait encore arriver sur son téléphone. Désormais :
désactiver = purger (push, clés d'API, jeton Drive, coffre), les envois push
ignorent les comptes inactifs, et un endpoint refait le ménage pour les
comptes désactivés avant le correctif.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import create_access_token, get_password_hash
from app.integrations.webpush import _vapid_configured  # noqa: F401 — import de fumée
from app.models.api_key import ApiKey
from app.models.push_subscription import PushSubscription
from app.models.user import User
from app.services.revocation_acces import abonnements_actifs_seulement, revoquer_acces
from tests.smoke.conftest import TestSessionLocal


def _run_in_session(run, coro_factory):
    async def _go():
        async with TestSessionLocal() as s:
            return await coro_factory(s)
    return run(_go())


def test_revocation_purge_push_cles_et_filtre_les_inactifs(client, run):  # client : crée le schéma
    async def _seed(s):
        u = User(email="renvoye@test.local", hashed_password=get_password_hash("x"), is_active=True, is_admin=False, role="employee")
        s.add(u)
        await s.flush()
        s.add_all([
            PushSubscription(user_id=u.id, endpoint="https://push.example/1", p256dh="k", auth="a", created_at=datetime.now(timezone.utc)),
            PushSubscription(user_id=u.id, endpoint="https://push.example/2", p256dh="k", auth="a", created_at=datetime.now(timezone.utc)),
            ApiKey(user_id=u.id, key_hash="h-renvoye", key_prefix="krt_x", label="perso", is_active=True, created_at=datetime.now(timezone.utc)),
        ])
        await s.commit()
        return u.id

    uid = _run_in_session(run, _seed)

    async def _actifs(s):
        return (await s.execute(abonnements_actifs_seulement(select(PushSubscription).where(PushSubscription.user_id == uid)))).scalars().all()

    # Compte actif : ses abonnements sont visibles pour l'envoi.
    assert len(_run_in_session(run, _actifs)) == 2

    async def _desactive_sans_purge(s):
        u = await s.get(User, uid)
        u.is_active = False
        await s.commit()

    _run_in_session(run, _desactive_sans_purge)
    # Compte inactif (même sans purge) : plus aucun abonnement servi à l'envoi.
    assert _run_in_session(run, _actifs) == []

    async def _purge(s):
        r = await revoquer_acces(s, uid)
        await s.commit()
        return r

    r = _run_in_session(run, _purge)
    assert r == {"push_supprimes": 2, "cles_api_desactivees": 1, "jetons_drive_supprimes": 0, "acces_coffre_retires": 0}

    async def _etat(s):
        subs = (await s.execute(select(PushSubscription).where(PushSubscription.user_id == uid))).scalars().all()
        cles = (await s.execute(select(ApiKey).where(ApiKey.user_id == uid))).scalars().all()
        return len(subs), [c.is_active for c in cles]

    assert _run_in_session(run, _etat) == (0, [False])
    # Idempotent.
    assert _run_in_session(run, _purge) == {"push_supprimes": 0, "cles_api_desactivees": 0, "jetons_drive_supprimes": 0, "acces_coffre_retires": 0}


def test_api_desactiver_purge_et_revoke_access(client, employee_headers, run):
    async def _seed(s):
        owner = User(email="owner-revocation@test.local", hashed_password=get_password_hash("x"), is_active=True, is_admin=True, role="owner")
        u = User(email="renvoye2@test.local", hashed_password=get_password_hash("x"), is_active=True, is_admin=False, role="employee")
        s.add_all([owner, u])
        await s.flush()
        s.add(PushSubscription(user_id=u.id, endpoint="https://push.example/3", p256dh="k", auth="a", created_at=datetime.now(timezone.utc)))
        await s.commit()
        return owner.id, u.id

    owner_id, uid = _run_in_session(run, _seed)
    owner_headers = {"Authorization": f"Bearer {create_access_token(subject=str(owner_id))}"}
    # Un employé ne peut pas révoquer.
    assert client.post(f"/api/v1/users/{uid}/revoke-access", headers=employee_headers).status_code in (401, 403)
    # Compte encore actif : il faut d'abord désactiver.
    r = client.post(f"/api/v1/users/{uid}/revoke-access", headers=owner_headers)
    assert r.status_code == 400, r.text
    # Désactiver = purger (push supprimés) et l'audit le dit.
    r = client.post(f"/api/v1/users/{uid}/deactivate", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    async def _etat(s):
        return len((await s.execute(select(PushSubscription).where(PushSubscription.user_id == uid))).scalars().all())

    assert _run_in_session(run, _etat) == 0
    r = client.get("/api/v1/audit", params={"entity_type": "user", "entity_id": uid}, headers=owner_headers)
    assert r.status_code == 200 and any(a["action"] == "user.deactivated" and '"push_supprimes": 1' in (a.get("details_json") or "") for a in r.json())
    # Ménage à part pour un compte déjà désactivé : idempotent, journalisé.
    r = client.post(f"/api/v1/users/{uid}/revoke-access", headers=owner_headers)
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["push_supprimes"] == 0
    # Un compte inactif ne peut plus rien appeler, même avec un jeton encore valide.
    jeton_renvoye = {"Authorization": f"Bearer {create_access_token(subject=str(uid))}"}
    assert client.get("/api/v1/auth/me", headers=jeton_renvoye).status_code == 401
