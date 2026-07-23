"""QuickBooks Online OAuth 2.0 flow.

Three endpoints working together to let an admin connect a QBO company
to the portal without ever touching env vars:

    GET  /api/v1/qbo/connect      → returns the Intuit consent URL
    GET  /api/v1/qbo/callback     → receives code + realmId from Intuit,
                                    exchanges them for tokens, persists.
    GET  /api/v1/qbo/status       → connection status (for /app/parametres)
    POST /api/v1/qbo/disconnect   → clears the saved tokens

State CSRF protection: the /connect endpoint signs a short-lived state
token (HMAC-SHA256 over timestamp + nonce using jwt_secret). /callback
verifies both the signature AND the TTL (5 min) before accepting the
exchange.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.api.deps import CurrentAdmin, CurrentUser, DBSession
from app.core.config import settings
from app.models.qbo_connection import QBO_CONNECTION_SCOPES, QboConnection
from app.models.qbo_token import QboToken

#: Scopes de connexion valides : "construction" (legacy qbo_tokens) +
#: les scopes multi-compagnies (qbo_connections).
_ALL_SCOPES = ("construction",) + QBO_CONNECTION_SCOPES


log = logging.getLogger(__name__)

router = APIRouter(prefix="/qbo", tags=["quickbooks-oauth"])

_INTUIT_AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
_INTUIT_TOKEN_URL = (
    "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
)
_INTUIT_REVOKE_URL = (
    "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
)
# `com.intuit.quickbooks.accounting` : API comptable v3 (clients, factures,
# achats…). `project-management.project` : API Projets (GraphQL) — permet de
# CRÉER de vrais projets QBO (onglet Projets) depuis Kratos. Ce 2e scope
# requiert un accès Premium API (palier partenaire Silver+) ET n'est ajouté
# QUE si `QBO_ENABLE_PROJECTS_API=true` : sinon demander un scope non
# accordé peut faire échouer la reconnexion OAuth. Après activation, il
# faut SE RECONNECTER à QuickBooks pour couvrir ce scope.
_BASE_SCOPE = "com.intuit.quickbooks.accounting"
_PROJECTS_SCOPE = "project-management.project"


def _oauth_scope() -> str:
    if settings.qbo_enable_projects_api:
        return f"{_BASE_SCOPE} {_PROJECTS_SCOPE}"
    return _BASE_SCOPE
_STATE_TTL_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# State signing — prevents CSRF + binds callback to this deploy's secret
# ---------------------------------------------------------------------------

def _sign_state(nonce: str, ts: int, scope: str = "construction") -> str:
    # Le scope voyage DANS le state signé : le callback Intuit ne porte
    # rien d'autre qui permette de savoir à quel pôle appartient la
    # compagnie qu'on vient d'autoriser.
    raw = f"{ts}.{nonce}.{scope}".encode()
    sig = hmac.new(
        settings.jwt_secret.encode(), raw, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(raw + b"|" + sig).decode().rstrip("=")


def _verify_state(token: str) -> Optional[str]:
    """Vérifie signature + TTL ; retourne le scope (None = invalide).
    Les states legacy sans scope valent "construction"."""
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode())
        raw, sig = decoded.rsplit(b"|", 1)
        expected = hmac.new(
            settings.jwt_secret.encode(), raw, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        parts = raw.decode().split(".")
        ts = int(parts[0])
        if (time.time() - ts) > _STATE_TTL_SECONDS:
            return None
        scope = parts[2] if len(parts) >= 3 else "construction"
        return scope if scope in _ALL_SCOPES else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ConnectResponse(BaseModel):
    auth_url: str
    environment: str


class StatusResponse(BaseModel):
    connected: bool
    # Environnement avec lequel la connexion a été établie (stocké en DB
    # au moment du callback OAuth).
    environment: Optional[str] = None
    # Environnement actuellement ciblé par la config (QUICKBOOKS_ENV).
    active_environment: Optional[str] = None
    # True si la connexion a été faite dans un autre environnement que
    # celui ciblé aujourd'hui (ex. token sandbox alors qu'on tape la prod)
    # → cause classique du 403 ApplicationAuthorizationFailed. Il faut
    # alors se déconnecter puis se reconnecter.
    env_mismatch: bool = False
    realm_id: Optional[str] = None
    company_name: Optional[str] = None
    connected_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/connect", response_model=ConnectResponse)
async def qbo_connect(
    _: CurrentAdmin,
    scope: str = Query(default="construction"),
) -> ConnectResponse:
    """Build the Intuit consent URL. The frontend redirects the browser
    to this URL; after the user approves, Intuit redirects back to the
    /callback endpoint with `code` + `realmId`. La MÊME app Intuit sert
    toutes les compagnies — `scope` choisit le pôle Kratos auquel la
    compagnie autorisée sera rattachée."""
    if scope not in _ALL_SCOPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "scope invalide")
    if not settings.quickbooks_client_id or not settings.quickbooks_client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "QuickBooks n'est pas configuré sur ce serveur "
            "(QUICKBOOKS_CLIENT_ID / QUICKBOOKS_CLIENT_SECRET manquants).",
        )
    nonce = secrets.token_urlsafe(16)
    state = _sign_state(nonce, int(time.time()), scope)
    params = {
        "client_id": settings.quickbooks_client_id,
        "response_type": "code",
        "scope": _oauth_scope(),
        "redirect_uri": settings.quickbooks_redirect_uri,
        "state": state,
    }
    auth_url = f"{_INTUIT_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return ConnectResponse(
        auth_url=auth_url, environment=settings.quickbooks_env
    )


@router.get("/callback")
async def qbo_callback(
    db: DBSession,
    code: Optional[str] = Query(default=None),
    realmId: Optional[str] = Query(default=None),  # noqa: N803 — Intuit casing
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
) -> RedirectResponse:
    """Intuit sends the user here with `?code=...&realmId=...&state=...`.
    We exchange the code for an access + refresh token, fetch the
    company name, persist everything, then redirect the browser back to
    the frontend settings page with a banner."""

    frontend = settings.frontend_url.rstrip("/")

    def _redirect(reason: str) -> RedirectResponse:
        # next-intl est configuré en localePrefix "as-needed" : la locale
        # par défaut (fr) NE doit PAS être préfixée dans l'URL, sinon
        # Next.js renvoie 404. On cible donc directement /app/...
        return RedirectResponse(
            f"{frontend}/app/parametres/comptabilite?qbo={reason}",
            status_code=status.HTTP_302_FOUND,
        )

    if error:
        log.warning("QBO OAuth callback reported error: %s", error)
        return _redirect(f"error:{error}")
    if not code or not realmId or not state:
        return _redirect("error:missing_params")
    scope = _verify_state(state)
    if scope is None:
        return _redirect("error:invalid_state")

    # Exchange authorization code for tokens
    basic = base64.b64encode(
        f"{settings.quickbooks_client_id}:{settings.quickbooks_client_secret}".encode()
    ).decode("ascii")
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.post(
                _INTUIT_TOKEN_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {basic}",
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.quickbooks_redirect_uri,
                },
            )
            if r.status_code >= 400:
                log.error(
                    "QBO code exchange failed: %s %s", r.status_code, r.text
                )
                return _redirect("error:token_exchange_failed")
            tok = r.json()
    except Exception as exc:
        log.exception("QBO code exchange crashed: %s", exc)
        return _redirect("error:token_exchange_crashed")

    refresh_token = tok.get("refresh_token")
    access_token = tok.get("access_token")
    if not refresh_token or not access_token:
        return _redirect("error:no_tokens_returned")

    # Fetch CompanyInfo for a pretty display in the UI
    company_name: Optional[str] = None
    try:
        base_api = (
            "https://quickbooks.api.intuit.com"
            if settings.quickbooks_env == "production"
            else "https://sandbox-quickbooks.api.intuit.com"
        )
        async with httpx.AsyncClient(timeout=15.0) as http:
            ci = await http.get(
                f"{base_api}/v3/company/{realmId}/companyinfo/{realmId}",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
                params={"minorversion": "70"},
            )
            if ci.status_code < 400:
                payload = ci.json().get("CompanyInfo") or {}
                company_name = payload.get("CompanyName")
    except Exception as exc:
        log.warning("Could not fetch QBO CompanyInfo: %s", exc)

    now = datetime.now(timezone.utc)
    if scope == "construction":
        # Chemin HISTORIQUE (compagnie Horizon) — inchangé : upsert de la
        # ligne unique qbo_tokens id=1.
        row = (
            await db.execute(select(QboToken).where(QboToken.id == 1))
        ).scalar_one_or_none()
        if row is None:
            row = QboToken(
                id=1,
                refresh_token=refresh_token,
                realm_id=str(realmId),
                environment=settings.quickbooks_env,
                company_name=company_name,
                connected_at=now,
            )
            db.add(row)
        else:
            row.refresh_token = refresh_token
            row.realm_id = str(realmId)
            row.environment = settings.quickbooks_env
            row.company_name = company_name
            row.connected_at = now
        await db.commit()

        # Reset the in-process QBO client so the next call reads fresh
        # values from the DB / env.
        try:
            from app.integrations import quickbooks as qbo_mod

            if qbo_mod._qbo is not None:
                qbo_mod._qbo.tokens.refresh_token = refresh_token
                qbo_mod._qbo.tokens.access_token = access_token
                qbo_mod._qbo.tokens.access_expires_at = (
                    time.time() + int(tok.get("expires_in", 3600))
                )
                qbo_mod._qbo.realm_id = str(realmId)
                qbo_mod._qbo._db_loaded = True
        except Exception as exc:
            log.warning("Could not prime in-process QBO client: %s", exc)
    else:
        # Connexions multi-compagnies (entreprise / immobilier) : upsert
        # par scope dans qbo_connections.
        conn_row = (
            await db.execute(
                select(QboConnection).where(QboConnection.scope == scope)
            )
        ).scalar_one_or_none()
        if conn_row is None:
            db.add(
                QboConnection(
                    scope=scope,
                    refresh_token=refresh_token,
                    realm_id=str(realmId),
                    environment=settings.quickbooks_env,
                    company_name=company_name,
                    connected_at=now,
                )
            )
        else:
            conn_row.refresh_token = refresh_token
            conn_row.realm_id = str(realmId)
            conn_row.environment = settings.quickbooks_env
            conn_row.company_name = company_name
            conn_row.connected_at = now
        await db.commit()

        try:
            from app.integrations import quickbooks as qbo_mod

            qbo_mod.reset_qbo(scope)
        except Exception as exc:
            log.warning("Could not reset scoped QBO client: %s", exc)

    return _redirect("connected")


@router.get("/status", response_model=StatusResponse)
async def qbo_status(
    db: DBSession,
    _: CurrentUser,
    scope: str = Query(default="construction"),
) -> StatusResponse:
    if scope not in _ALL_SCOPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "scope invalide")
    active_env = (settings.quickbooks_env or "sandbox").lower()
    if scope == "construction":
        row = (
            await db.execute(select(QboToken).where(QboToken.id == 1))
        ).scalar_one_or_none()
    else:
        row = (
            await db.execute(
                select(QboConnection).where(QboConnection.scope == scope)
            )
        ).scalar_one_or_none()
    if row is None or not row.refresh_token:
        return StatusResponse(
            connected=False, active_environment=active_env
        )
    conn_env = (row.environment or settings.quickbooks_env or "").lower()
    return StatusResponse(
        connected=True,
        environment=conn_env,
        active_environment=active_env,
        env_mismatch=bool(conn_env and conn_env != active_env),
        realm_id=row.realm_id,
        company_name=row.company_name,
        connected_at=row.connected_at,
    )


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def qbo_disconnect(
    db: DBSession,
    _: CurrentAdmin,
    scope: str = Query(default="construction"),
) -> None:
    """Forget the saved tokens locally. Does NOT revoke at Intuit — if
    you want to fully revoke, do it from the QBO company settings
    (Apps → Disconnect). Keeping local-only keeps the call idempotent
    and avoids blocking on Intuit's revoke endpoint."""
    if scope not in _ALL_SCOPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "scope invalide")
    if scope == "construction":
        await db.execute(delete(QboToken).where(QboToken.id == 1))
    else:
        await db.execute(
            delete(QboConnection).where(QboConnection.scope == scope)
        )
    await db.commit()

    try:
        from app.integrations import quickbooks as qbo_mod

        qbo_mod.reset_qbo(scope)
    except Exception:
        pass
