"""Smoke — MODE ESSAI de l'aperçu « voir comme » (app/core/essai.py).

Un admin en aperçu (jeton ``apercu_par``) active « Mode essai » : ses
écritures passent avec les droits EXACTS de l'utilisateur regardé, mais
rien n'est gardé et aucun appel externe ne part. Verrouille :

- sans l'en-tête ``X-Kratos-Essai`` : lecture seule stricte (403) ;
- avec l'en-tête : une écriture permise répond 200 + ``X-Kratos-Essai:
  annule`` et la base reste INTACTE ; une écriture que l'utilisateur
  regardé n'a pas le droit de faire reste refusée (403 de rôle) ;
- dans la requête, un ``commit()`` puis une relecture voient la ligne
  (l'endpoint se comporte comme en vrai) ; après la requête, ni la
  ligne de l'endpoint, ni celle d'une BackgroundTask n'existent ;
- un appel httpx sortant est bloqué (409 + ``X-Kratos-Essai-Externe``) ;
- aucun journal d'audit pour un essai ;
- l'en-tête est ignoré avec un jeton NORMAL (écriture réelle) ;
- aperçu en chaîne et jeton Twilio refusés même en essai.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import BackgroundTasks
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.db.session import AsyncSessionLocal
from app.main import app as fastapi_app
from app.models.audit_log import AuditLog
from app.models.user import User

from .conftest import TestSessionLocal

ESSAI = {"X-Kratos-Essai": "1"}
_CHEMIN_TEST = "/api/v1/_essai_smoke"


# ── Routes de test (montées sur l'app, jamais en prod) ───────────────


async def _ecrire_marqueur(marqueur: str, user_id: int) -> None:
    async with AsyncSessionLocal() as s:
        s.add(
            AuditLog(
                user_id=user_id,
                action="smoke.essai",
                entity_type=marqueur,
            )
        )
        await s.commit()


async def _route_ecriture(
    marqueur: str,
    db: DBSession,
    user: CurrentUser,
    background: BackgroundTasks,
) -> dict:
    """Écrit + commit (session de requête), relit, puis planifie une
    écriture en BackgroundTask via ``AsyncSessionLocal``."""
    db.add(AuditLog(user_id=user.id, action="smoke.essai", entity_type=marqueur))
    await db.commit()
    vus = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.entity_type == marqueur
            )
        )
    ).scalar_one()
    # Termine la transaction de lecture : sous SQLite, un lecteur ouvert
    # bloquerait l'écriture de la BackgroundTask (jeton normal).
    await db.commit()
    background.add_task(_ecrire_marqueur, marqueur + "-bg", user.id)
    return {"vus_dans_la_requete": vus}


async def _route_externe(user: CurrentUser) -> dict:
    async with httpx.AsyncClient() as c:
        await c.post("https://quickbooks.api.intuit.com/v3/test", json={})
    return {"ok": True}


async def _route_externe_rattrapee(user: CurrentUser) -> dict:
    """Comme beaucoup de services « best-effort » : l'erreur est avalée."""
    try:
        async with httpx.AsyncClient() as c:
            await c.post("https://api.vopay.com/test", json={})
    except Exception:
        return {"envoye": False}
    return {"envoye": True}


fastapi_app.router.add_api_route(
    _CHEMIN_TEST + "/ecriture/{marqueur}", _route_ecriture, methods=["POST"]
)
fastapi_app.router.add_api_route(
    _CHEMIN_TEST + "/externe", _route_externe, methods=["POST"]
)
fastapi_app.router.add_api_route(
    _CHEMIN_TEST + "/externe-rattrapee", _route_externe_rattrapee, methods=["POST"]
)


# ── Helpers ───────────────────────────────────────────────────────────


def _compter(run, entity_type: str) -> int:
    async def _c() -> int:
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(func.count()).select_from(AuditLog).where(
                        AuditLog.entity_type == entity_type
                    )
                )
            ).scalar_one()

    return run(_c())


def _theme(run, user_id: int):
    async def _t():
        async with TestSessionLocal() as s:
            return (await s.get(User, user_id)).theme_preference

    return run(_t())


@pytest.fixture(scope="module")
def apercu_headers(client, auth_headers, employee_id) -> dict:
    resp = client.post(f"/api/v1/users/{employee_id}/apercu", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── Tests ─────────────────────────────────────────────────────────────


def test_sans_mode_essai_l_apercu_reste_en_lecture_seule(
    client, apercu_headers, run, employee_id
):
    avant = _theme(run, employee_id)
    resp = client.patch(
        "/api/v1/auth/me/theme", headers=apercu_headers, json={"theme": "dark"}
    )
    assert resp.status_code == 403, resp.text
    assert "mode essai" in resp.json()["detail"].lower()
    assert "x-kratos-essai" not in resp.headers
    assert _theme(run, employee_id) == avant


def test_ecriture_permise_en_essai_puis_annulee(
    client, apercu_headers, run, employee_id
):
    avant = _theme(run, employee_id)
    cible = "light" if avant == "dark" else "dark"
    resp = client.patch(
        "/api/v1/auth/me/theme",
        headers={**apercu_headers, **ESSAI},
        json={"theme": cible},
    )
    assert resp.status_code == 200, resp.text
    # La réponse reflète l'action comme si elle avait eu lieu…
    assert resp.json()["theme_preference"] == cible
    assert resp.headers["x-kratos-essai"] == "annule"
    # …mais rien n'est resté en base.
    assert _theme(run, employee_id) == avant


def test_permissions_de_l_utilisateur_regarde_appliquees_en_essai(
    client, apercu_headers, employee_id
):
    """Un employé ne gère pas les comptes : l'essai renvoie le MÊME refus
    de rôle que pour lui (pas le refus « lecture seule » de l'aperçu)."""
    resp = client.put(
        f"/api/v1/users/{employee_id}/projects",
        headers={**apercu_headers, **ESSAI},
        json={"project_ids": []},
    )
    assert resp.status_code == 403, resp.text
    assert "lecture seule" not in resp.json()["detail"].lower()
    assert resp.headers["x-kratos-essai"] == "annule"


def test_commit_visible_dans_la_requete_mais_rien_ne_reste(
    client, apercu_headers, run
):
    marqueur = f"essai-{uuid.uuid4().hex[:10]}"
    resp = client.post(
        f"{_CHEMIN_TEST}/ecriture/{marqueur}", headers={**apercu_headers, **ESSAI}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["vus_dans_la_requete"] == 1
    assert _compter(run, marqueur) == 0
    assert _compter(run, marqueur + "-bg") == 0


def test_appel_externe_bloque_en_essai(client, apercu_headers):
    resp = client.post(f"{_CHEMIN_TEST}/externe", headers={**apercu_headers, **ESSAI})
    assert resp.status_code == 409, resp.text
    assert "quickbooks.api.intuit.com" in resp.json()["detail"]
    assert resp.headers["x-kratos-essai-externe"] == "quickbooks.api.intuit.com"


def test_appel_externe_rattrape_reste_bloque_et_signale(client, apercu_headers):
    resp = client.post(
        f"{_CHEMIN_TEST}/externe-rattrapee", headers={**apercu_headers, **ESSAI}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"envoye": False}
    assert resp.headers["x-kratos-essai-externe"] == "api.vopay.com"


def test_aucun_journal_d_audit_pour_un_essai(client, apercu_headers, run):
    async def _n() -> int:
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(func.count()).select_from(AuditLog).where(
                        AuditLog.action == "api.patch",
                        AuditLog.details_json.contains("/api/v1/auth/me/theme"),
                    )
                )
            ).scalar_one()

    avant = run(_n())
    resp = client.patch(
        "/api/v1/auth/me/theme",
        headers={**apercu_headers, **ESSAI},
        json={"theme": "dark"},
    )
    assert resp.status_code == 200, resp.text
    assert run(_n()) == avant


def test_en_tete_ignore_avec_un_jeton_normal(client, auth_headers, run):
    marqueur = f"reel-{uuid.uuid4().hex[:10]}"
    resp = client.post(
        f"{_CHEMIN_TEST}/ecriture/{marqueur}", headers={**auth_headers, **ESSAI}
    )
    assert resp.status_code == 200, resp.text
    assert "x-kratos-essai" not in resp.headers
    assert _compter(run, marqueur) == 1


def test_aperçu_en_chaine_refuse_meme_en_essai(client, apercu_headers, admin_id):
    resp = client.post(
        f"/api/v1/users/{admin_id}/apercu", headers={**apercu_headers, **ESSAI}
    )
    assert resp.status_code == 403, resp.text
    assert "aperçu" in resp.json()["detail"].lower()


def test_jeton_twilio_refuse_en_apercu(client, apercu_headers):
    resp = client.get("/api/v1/voice/sdk/token", headers=apercu_headers)
    assert resp.status_code == 403, resp.text
    assert "aperçu" in resp.json()["detail"].lower()
