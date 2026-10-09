"""Smoke — jeton QuickBooks unique en base (incident 2026-10-09).

Steven, fiche du projet 155 avenue Joubert : « Dernier échec QuickBooks :
QBO refresh token invalide ou expiré […] (détail: invalid_grant) ».

Cause : Intuit fait tourner le refresh token (environ une fois par 24 h)
et l'ancien cesse de fonctionner. Le client QBO partagé lisait la base
UNE fois par processus ; depuis le 2026-10-04, la copie des reçus vers
le Drive d'Horizon utilise la connexion Construction avec son PROPRE
client. Quand ce 2e client faisait tourner le jeton, le client partagé
gardait l'ancien → invalid_grant pour tout le reste de Kratos.

Couvre :
1. un renouvellement fait par un AUTRE client n'empêche plus le client
   partagé de renouveler (il relit la base à chaque renouvellement) ;
2. même règle pour une connexion d'inc (qbo_connections) ;
3. invalid_grant → erreur « à reconnecter » lisible (plus d'appel d'API
   à faire à la main), état visible dans GET /qbo/status ;
4. un renouvellement réussi lève cet état ;
5. le callback OAuth (bouton « Reconnecter ») le lève aussi ;
6. le cron quotidien renouvelle chaque connexion (aucune n'expire faute
   d'usage) et marque tout de suite celle qu'Intuit refuse.

Intuit est simulé (httpx.MockTransport) : aucun appel réseau réel.
"""

from __future__ import annotations

import time
import types
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx
import pytest
from sqlalchemy import delete, select

import app.integrations.quickbooks as qb
from app.core.config import settings
from app.models.qbo_connection import QboConnection
from app.models.qbo_token import QboToken
from tests.smoke.conftest import TestSessionLocal

REALM = "4620816365"
SCOPE_INC = "inc:990001"


class FauxIntuit:
    """OAuth + API d'Intuit simulés. Chaque renouvellement fait tourner le
    refresh token et l'ancien cesse de fonctionner (invalid_grant)."""

    def __init__(self, valide: str) -> None:
        self.valides = {valide}
        self.presentes: List[str] = []
        self.n = 0
        self.api_auth: List[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tokens/bearer"):
            form = dict(urllib.parse.parse_qsl(request.content.decode()))
            if form.get("grant_type") == "authorization_code":
                self.valides = {"rt-oauth"}
                return httpx.Response(
                    200,
                    json={
                        "access_token": "at-oauth",
                        "refresh_token": "rt-oauth",
                        "expires_in": 3600,
                    },
                )
            jeton = form.get("refresh_token", "")
            self.presentes.append(jeton)
            if jeton not in self.valides:
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.n += 1
            nouveau = f"rt-{self.n}"
            self.valides = {nouveau}
            return httpx.Response(
                200,
                json={
                    "access_token": f"at-{self.n}",
                    "refresh_token": nouveau,
                    "expires_in": 3600,
                },
            )
        if request.url.path.endswith(f"/companyinfo/{REALM}"):
            return httpx.Response(
                200, json={"CompanyInfo": {"CompanyName": "Horizon (test)"}}
            )
        # API comptable v3 (query) : liste vide.
        self.api_auth.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"QueryResponse": {"Customer": []}})


def _shim_httpx(faux: FauxIntuit) -> Any:
    vrai = httpx.AsyncClient

    def fabrique(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return vrai(*args, transport=httpx.MockTransport(faux.handler), **kwargs)

    return types.SimpleNamespace(AsyncClient=fabrique)


async def _ligne_construction() -> Optional[QboToken]:
    async with TestSessionLocal() as s:
        return (
            await s.execute(select(QboToken).where(QboToken.id == 1))
        ).scalar_one_or_none()


async def _ligne_inc() -> Optional[QboConnection]:
    async with TestSessionLocal() as s:
        return (
            await s.execute(
                select(QboConnection).where(QboConnection.scope == SCOPE_INC)
            )
        ).scalar_one_or_none()


@pytest.fixture()
def intuit(monkeypatch, run, db_setup):
    faux = FauxIntuit("rt-0")
    shim = _shim_httpx(faux)
    monkeypatch.setattr(qb, "httpx", shim)
    from app.api.v1.endpoints import qbo_oauth

    monkeypatch.setattr(qbo_oauth, "httpx", shim)
    monkeypatch.setattr(settings, "quickbooks_client_id", "cid-test")
    monkeypatch.setattr(settings, "quickbooks_client_secret", "secret-test")
    monkeypatch.setattr(settings, "quickbooks_env", "sandbox")
    # Clients partagés neufs pour chaque test.
    monkeypatch.setattr(qb, "_qbo", None)
    monkeypatch.setattr(qb, "_qbo_by_scope", {})

    cols = [c.name for c in QboToken.__table__.columns]

    async def _preparer() -> Optional[Dict[str, Any]]:
        async with TestSessionLocal() as s:
            avant = (
                await s.execute(select(QboToken).where(QboToken.id == 1))
            ).scalar_one_or_none()
            sauvegarde = (
                {c: getattr(avant, c) for c in cols} if avant else None
            )
            await s.execute(delete(QboToken).where(QboToken.id == 1))
            await s.execute(
                delete(QboConnection).where(QboConnection.scope == SCOPE_INC)
            )
            s.add(
                QboToken(
                    id=1,
                    refresh_token="rt-0",
                    realm_id=REALM,
                    environment="sandbox",
                    company_name="Horizon (test)",
                )
            )
            await s.commit()
            return sauvegarde

    sauvegarde = run(_preparer())
    yield faux

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            await s.execute(delete(QboToken).where(QboToken.id == 1))
            await s.execute(
                delete(QboConnection).where(QboConnection.scope == SCOPE_INC)
            )
            if sauvegarde:
                s.add(QboToken(**sauvegarde))
            await s.commit()

    run(_nettoyer())


def test_rotation_par_un_autre_client_ne_casse_plus_le_client_partage(
    intuit, run
):
    async def scenario() -> None:
        partage = qb.get_qbo()
        await partage._load_refresh_from_db()
        assert partage.ready
        await partage.query("select * from Customer")
        assert intuit.presentes == ["rt-0"]

        # Un AUTRE client sur la même connexion (copie des reçus vers le
        # Drive, 2e instance…) fait tourner le jeton : rt-1 → rt-2, et
        # rt-1 cesse de fonctionner.
        autre = qb.QuickBooksClient()
        await autre.forcer_renouvellement()
        assert intuit.presentes == ["rt-0", "rt-1"]

        # L'access token du client partagé arrive à échéance.
        partage.tokens.access_expires_at = 0.0
        await partage.query("select * from Customer")
        # Avant le correctif : le client partagé présentait sa copie
        # mémoire (rt-1) → invalid_grant jusqu'au redémarrage.
        assert intuit.presentes[-1] == "rt-2"
        assert intuit.api_auth[-1] == "Bearer at-3"

    run(scenario())
    ligne = run(_ligne_construction())
    assert ligne.refresh_token == "rt-3"
    assert ligne.reconnect_required_at is None


def test_connexion_d_inc_meme_regle(intuit, run):
    async def seed() -> None:
        async with TestSessionLocal() as s:
            s.add(
                QboConnection(
                    scope=SCOPE_INC,
                    refresh_token="rt-0",
                    realm_id=REALM,
                    environment="sandbox",
                    company_name="Inc (test)",
                )
            )
            await s.commit()

    run(seed())

    async def scenario() -> None:
        partage = qb.get_qbo(SCOPE_INC)
        await partage._load_refresh_from_db()
        await partage.query("select * from Customer")
        autre = qb.QuickBooksClient(scope=SCOPE_INC)
        await autre.forcer_renouvellement()
        partage.tokens.access_expires_at = 0.0
        await partage.query("select * from Customer")
        assert intuit.presentes == ["rt-0", "rt-1", "rt-2"]

    run(scenario())
    assert run(_ligne_inc()).refresh_token == "rt-3"
    # La connexion Construction n'a pas bougé.
    assert run(_ligne_construction()).refresh_token == "rt-0"


def test_invalid_grant_demande_une_reconnexion(
    intuit, run, client, auth_headers
):
    intuit.valides = set()  # Intuit refuse le jeton enregistré.

    async def scenario() -> str:
        partage = qb.get_qbo()
        await partage._load_refresh_from_db()
        with pytest.raises(qb.QuickBooksReconnexionRequise) as exc:
            await partage.query("select * from Customer")
        # Les « except QuickBooksError » existants l'attrapent toujours.
        assert isinstance(exc.value, qb.QuickBooksError)
        return str(exc.value)

    message = run(scenario())
    assert "invalid_grant" in message
    assert "Paramètres → Comptabilité" in message
    assert "/api/v1/qbo/refresh-token" not in message

    r = client.get("/api/v1/qbo/status", headers=auth_headers)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["connected"] is True
    assert corps["needs_reconnect"] is True
    assert corps["reconnect_required_at"]
    assert "invalid_grant" in corps["last_refresh_error"]

    # Un jeton valide revient en base (reconnexion) : le renouvellement
    # suivant réussit et lève l'état « à reconnecter ».
    async def reconnecter() -> None:
        async with TestSessionLocal() as s:
            ligne = (
                await s.execute(select(QboToken).where(QboToken.id == 1))
            ).scalar_one()
            ligne.refresh_token = "rt-neuf"
            await s.commit()
        intuit.valides = {"rt-neuf"}
        await qb.get_qbo().query("select * from Customer")

    run(reconnecter())
    corps = client.get("/api/v1/qbo/status", headers=auth_headers).json()
    assert corps["needs_reconnect"] is False
    assert corps["last_refresh_error"] is None


def test_callback_oauth_leve_l_etat_a_reconnecter(
    intuit, run, client, auth_headers
):
    intuit.valides = set()

    async def echec() -> None:
        partage = qb.get_qbo()
        await partage._load_refresh_from_db()
        with pytest.raises(qb.QuickBooksReconnexionRequise):
            await partage.query("select * from Customer")

    run(echec())
    assert run(_ligne_construction()).reconnect_required_at is not None

    from app.api.v1.endpoints.qbo_oauth import _sign_state

    state = _sign_state("nonce-test", int(time.time()), "construction")
    r = client.get(
        "/api/v1/qbo/callback",
        params={"code": "code-test", "realmId": REALM, "state": state},
    )
    assert r.status_code == 302, r.text
    assert "qbo=connected" in r.headers["location"]

    ligne = run(_ligne_construction())
    assert ligne.refresh_token == "rt-oauth"
    assert ligne.reconnect_required_at is None
    assert ligne.last_refresh_error is None
    corps = client.get("/api/v1/qbo/status", headers=auth_headers).json()
    assert corps["needs_reconnect"] is False

    # Le client partagé repart avec le nouveau jeton.
    run(qb.get_qbo().query("select * from Customer"))
    assert intuit.api_auth[-1] == "Bearer at-oauth"


_ETAT = ("refresh_token", "reconnect_required_at", "last_refresh_error")


async def _etat_autres_connexions() -> Dict[str, Dict[str, Any]]:
    """Connexions laissées par d'autres tests (inc:…) : remises telles
    quelles après le passage du cron."""
    async with TestSessionLocal() as s:
        rows = (
            await s.execute(
                select(QboConnection).where(QboConnection.scope != SCOPE_INC)
            )
        ).scalars().all()
        return {r.scope: {k: getattr(r, k) for k in _ETAT} for r in rows}


async def _restaurer(etat: Dict[str, Dict[str, Any]]) -> None:
    if not etat:
        return
    async with TestSessionLocal() as s:
        rows = (
            await s.execute(
                select(QboConnection).where(QboConnection.scope.in_(list(etat)))
            )
        ).scalars().all()
        for r in rows:
            for k, v in etat[r.scope].items():
                setattr(r, k, v)
        await s.commit()


def test_cron_quotidien_garde_chaque_connexion_vivante(intuit, run):
    """Steven : « faire en sorte qu'elle n'expire jamais ». Le cron
    all-daily renouvelle chaque connexion (aucune n'atteint les ~100 jours
    sans usage d'Intuit) ; une connexion refusée est marquée à
    reconnecter, puis n'est plus présentée à Intuit."""

    async def seed() -> None:
        async with TestSessionLocal() as s:
            s.add(
                QboConnection(
                    scope=SCOPE_INC,
                    refresh_token="rt-mort",
                    realm_id=REALM,
                    environment="sandbox",
                    company_name="Inc (test)",
                )
            )
            await s.commit()

    run(seed())
    autres = run(_etat_autres_connexions())
    try:
        res = run(qb.garder_connexions_vivantes())
        assert res["construction"] == "ok"
        assert res[SCOPE_INC] == "à reconnecter"
        assert run(_ligne_construction()).refresh_token == "rt-1"
        ligne = run(_ligne_inc())
        assert ligne.reconnect_required_at is not None
        assert "Paramètres → Drive" in ligne.last_refresh_error

        # Le lendemain : Construction renouvelée de nouveau, la connexion
        # refusée sautée (seule une reconnexion la rétablit).
        n = len(intuit.presentes)
        res = run(qb.garder_connexions_vivantes())
        assert res["construction"] == "ok"
        assert SCOPE_INC not in res
        assert "rt-mort" not in intuit.presentes[n:]
        assert run(_ligne_construction()).refresh_token == "rt-2"
    finally:
        run(_restaurer(autres))
