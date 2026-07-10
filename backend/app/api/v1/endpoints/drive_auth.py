"""Google Drive OAuth — endpoints HTTP (Phase 1 Foundation).

Quatre routes :

    GET  /api/v1/drive/auth/url        → URL Google de consentement.
                                          Auth : admin/owner.
    GET  /api/v1/drive/auth/callback   → callback public (appelé par Google).
                                          Persiste les tokens, redirige.
    POST /api/v1/drive/auth/disconnect → révoque + supprime.
                                          Auth : admin/owner.
    GET  /api/v1/drive/auth/status     → {connected, google_email, expires_at}.
                                          Auth : admin/owner.

L'audit log Drive est écrit par ``app.services.drive_oauth`` lui-même
(action "drive_user_token.connected" / ".disconnected" / ".token_refreshed").
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.deps import DBSession, RequireAdminOrOwner
from app.core.config import settings
from app.services import drive_oauth

log = logging.getLogger(__name__)

router = APIRouter(prefix="/drive/auth", tags=["drive-oauth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AuthorizationUrlResponse(BaseModel):
    authorization_url: str


class StatusResponse(BaseModel):
    connected: bool
    google_email: Optional[str] = None
    expires_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Indique si les credentials Google sont configurés côté serveur. Si
    # False, l'UI affiche un message d'aide pour configurer Render plutôt
    # qu'un bouton mort.
    server_configured: bool
    # True quand des tokens existent en base mais que la session Google
    # est RÉELLEMENT morte (refresh refusé par Google) : l'UI doit dire
    # « expiré — reconnecte-toi » au lieu d'un faux « Connecté ».
    expired: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/url", response_model=AuthorizationUrlResponse)
async def get_auth_url(
    user: RequireAdminOrOwner,
) -> AuthorizationUrlResponse:
    """Retourne l'URL de consentement Google à ouvrir côté frontend."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google OAuth n'est pas configuré sur ce serveur "
            "(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET manquants). "
            "Voir docs/DRIVE_INTEGRATION.md.",
        )
    try:
        url = drive_oauth.get_authorization_url(user_id=user.id)
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)
        ) from exc
    return AuthorizationUrlResponse(authorization_url=url)


@router.get("/callback")
async def auth_callback(
    db: DBSession,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
) -> RedirectResponse:
    """Endpoint PUBLIC appelé par Google après consentement.

    Pas de dépendance d'auth — Google n'a pas de session Kratos. La
    sécurité repose sur la vérification HMAC du `state` qui porte le
    user_id signé avec ``jwt_secret``.
    """
    frontend = settings.frontend_url.rstrip("/")

    def _redirect(reason: str) -> RedirectResponse:
        # Frontend cible : /app/parametres/drive?drive=<reason>
        return RedirectResponse(
            f"{frontend}/app/parametres/drive?drive={reason}",
            status_code=status.HTTP_302_FOUND,
        )

    if error:
        log.warning("Drive OAuth callback reported error: %s", error)
        return _redirect(f"error:{error}")
    if not code or not state:
        return _redirect("error:missing_params")

    user_id = drive_oauth.verify_state(state)
    if user_id is None:
        return _redirect("error:invalid_state")

    try:
        await drive_oauth.exchange_code(db, code=code, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("Drive code exchange crashed: %s", exc)
        return _redirect("error:exchange_failed")

    return _redirect("connected")


@router.get("/status", response_model=StatusResponse)
async def auth_status(
    db: DBSession, user: RequireAdminOrOwner
) -> StatusResponse:
    server_configured = bool(
        settings.google_client_id and settings.google_client_secret
    )
    row = await drive_oauth.get_token_row(db, user_id=user.id)
    if row is None:
        return StatusResponse(
            connected=False, server_configured=server_configured
        )
    # Vérification RÉELLE : avant, on affichait « Connecté » dès qu'une
    # ligne de tokens existait — même si Google avait révoqué la session.
    # Résultat : les sections Drive disaient « Connexion requise » pendant
    # que Paramètres → Drive disait « Connecté » (bug Phil 2026-07-10).
    # On tente d'obtenir un access token valide (refresh au besoin) : un
    # refus Google = session morte → connected=False + expired=True.
    try:
        await drive_oauth.get_valid_access_token(db, user_id=user.id)
    except drive_oauth.DriveAuthError:
        return StatusResponse(
            connected=False,
            google_email=row.google_email,
            updated_at=row.updated_at,
            server_configured=server_configured,
            expired=True,
        )
    except Exception:  # noqa: BLE001 — réseau/Google down : ne pas mentir
        pass  # on garde l'affichage « connecté » (erreur transitoire)
    return StatusResponse(
        connected=True,
        google_email=row.google_email,
        expires_at=row.expires_at,
        updated_at=row.updated_at,
        server_configured=server_configured,
    )


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def auth_disconnect(
    db: DBSession, user: RequireAdminOrOwner
) -> None:
    """Révoque le refresh_token côté Google + supprime de la BDD."""
    await drive_oauth.revoke_token(db, user_id=user.id)
