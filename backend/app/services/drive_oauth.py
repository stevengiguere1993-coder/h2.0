"""Google Drive OAuth wrapper — Phase 1 Foundation.

Gère le flow OAuth 2.0 pour permettre à chaque utilisateur Kratos de
connecter SON compte Google et de donner accès à son Drive.

Surface publique :

    get_authorization_url(user_id, state)
        Build l'URL Google de consentement (PKCE non utilisé — server-side
        confidential client). Le `state` est signé HMAC-SHA256 avec
        ``jwt_secret`` et porte le ``user_id`` + un nonce + un timestamp.

    exchange_code(db, code, user_id)
        Échange un authorization_code contre access/refresh tokens, fetch
        l'email Google associé, persiste chiffré dans drive_user_tokens
        (upsert), log dans drive_audit_logs.

    get_valid_access_token(db, user_id)
        Retourne un access_token déchiffré valide pour le user, en
        refresh-ant automatiquement si l'expiration approche (< 60 s).
        Phase 1 : utilisé uniquement par le endpoint /status. Phases 2+ :
        utilisé par tous les appels Drive API.

    revoke_token(db, user_id)
        Révoque le refresh_token côté Google + supprime la ligne locale.

    get_user_email(db, user_id)
        Retourne l'email Google enregistré (sans toucher au token).

Chiffrement : ``cryptography.fernet.Fernet`` avec ``DRIVE_TOKEN_ENCRYPTION_KEY``.
Si la clé n'est pas configurée, fallback INSECURE qui log un WARNING — pour
ne pas crasher en dev. À configurer obligatoirement en prod (voir docs/
DRIVE_INTEGRATION.md).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.drive_audit_log import DriveAuditLog
from app.models.drive_user_token import DriveUserToken

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes Google
# ---------------------------------------------------------------------------

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Scopes Phase 1 : on demande déjà drive.file (accès aux fichiers créés
# ou ouverts par Kratos) pour ne pas avoir à redemander le consentement
# Phase 2. Sans drive.file on ne peut rien faire d'utile.
#
# Note : userinfo.email + openid sont quasi-toujours implicites mais on
# les liste pour rendre le scope set explicite et auditable.
DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/drive.file "
    "https://www.googleapis.com/auth/userinfo.email "
    "openid"
)

# TTL du state OAuth (anti-CSRF) — 10 min, plus large que QBO (5 min) car
# l'écran de consentement Google peut prendre du temps si l'utilisateur
# doit choisir un compte / re-saisir son mot de passe / faire 2FA.
_STATE_TTL_SECONDS = 600

# Marge de sécurité sur expires_at avant de déclencher un refresh.
_REFRESH_BUFFER_SECONDS = 60


# ---------------------------------------------------------------------------
# Chiffrement Fernet
# ---------------------------------------------------------------------------


def _get_fernet() -> Optional[Fernet]:
    """Retourne le Fernet configuré, ou None si la clé est absente.

    En l'absence de clé, on log un WARNING et on bascule en fallback
    base64 (cf. ``_encrypt`` / ``_decrypt``). C'est INSECURE — on accepte
    en dev pour ne pas casser le boot, mais en prod on DOIT configurer
    DRIVE_TOKEN_ENCRYPTION_KEY (cf. docs/DRIVE_INTEGRATION.md).
    """
    key = settings.drive_token_encryption_key
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "DRIVE_TOKEN_ENCRYPTION_KEY invalide (Fernet refuse) — "
            "fallback base64 INSECURE : %s",
            exc,
        )
        return None


def _encrypt(plaintext: str) -> bytes:
    """Chiffre un token avec Fernet (si clé configurée) ou fallback base64."""
    fernet = _get_fernet()
    if fernet is None:
        log.warning(
            "DRIVE_TOKEN_ENCRYPTION_KEY absent — tokens stockés en "
            "base64 NON CHIFFRÉ (dev only)."
        )
        return base64.b64encode(plaintext.encode("utf-8"))
    return fernet.encrypt(plaintext.encode("utf-8"))


def _decrypt(blob: bytes) -> str:
    """Déchiffre un blob de la BDD (Fernet ou fallback base64)."""
    if blob is None:
        raise ValueError("empty token blob")
    fernet = _get_fernet()
    if fernet is None:
        try:
            return base64.b64decode(blob).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"base64 decode failed: {exc}") from exc
    try:
        return fernet.decrypt(bytes(blob)).decode("utf-8")
    except InvalidToken as exc:
        # Probable : la clé a changé depuis le chiffrement. L'utilisateur
        # doit se reconnecter à Drive.
        raise ValueError(
            "token déchiffrement échoué — la clé a probablement changé"
        ) from exc


# ---------------------------------------------------------------------------
# State signing (anti-CSRF)
# ---------------------------------------------------------------------------


def _sign_state(user_id: int, nonce: str, ts: int) -> str:
    raw = f"{ts}.{user_id}.{nonce}".encode()
    sig = hmac.new(
        settings.jwt_secret.encode(), raw, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(raw + b"|" + sig).decode().rstrip("=")


def verify_state(token: str) -> Optional[int]:
    """Vérifie la signature + TTL du state. Retourne user_id si valide."""
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
        if len(parts) != 3:
            return None
        ts = int(parts[0])
        user_id = int(parts[1])
        if (time.time() - ts) > _STATE_TTL_SECONDS:
            return None
        return user_id
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Audit helper (local — n'utilise pas app.services.audit pour rester sur la
# table dédiée drive_audit_logs)
# ---------------------------------------------------------------------------


async def _audit(
    db: AsyncSession,
    *,
    user_id: Optional[int],
    google_email: Optional[str],
    action: str,
    success: bool = True,
    error_message: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    try:
        entry = DriveAuditLog(
            user_id=user_id,
            google_email=google_email,
            action=action,
            success=success,
            error_message=error_message,
            details=details,
        )
        db.add(entry)
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning("drive audit log failed for %s: %s", action, exc)


# ---------------------------------------------------------------------------
# Surface publique
# ---------------------------------------------------------------------------


def get_authorization_url(user_id: int) -> str:
    """Construit l'URL de consentement Google. Le state porte le user_id."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError(
            "Google OAuth non configuré : GOOGLE_CLIENT_ID / "
            "GOOGLE_CLIENT_SECRET manquants."
        )
    nonce = secrets.token_urlsafe(16)
    state = _sign_state(user_id, nonce, int(time.time()))
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": DEFAULT_SCOPES,
        # access_type=offline → Google renvoie un refresh_token.
        "access_type": "offline",
        # prompt=consent force l'écran de consentement même si le user a
        # déjà autorisé — c'est ce qui garantit qu'on récupère TOUJOURS
        # un refresh_token au callback (sans ça, Google n'en renvoie un
        # qu'au premier consentement, et les reconnexions tombent sur
        # access_token seul = refresh impossible).
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{_GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def _fetch_google_email(access_token: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code < 400:
                return r.json().get("email")
    except Exception as exc:  # noqa: BLE001
        log.warning("Drive: get userinfo échoué : %s", exc)
    return None


async def exchange_code(
    db: AsyncSession, *, code: str, user_id: int
) -> DriveUserToken:
    """Échange code → tokens, persiste chiffré, retourne la ligne BDD."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError("Google OAuth non configuré.")

    async with httpx.AsyncClient(timeout=20.0) as http:
        r = await http.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        if r.status_code >= 400:
            log.error("Drive code exchange failed: %s %s", r.status_code, r.text)
            await _audit(
                db,
                user_id=user_id,
                google_email=None,
                action="drive_user_token.connect_failed",
                success=False,
                error_message=f"http_{r.status_code}: {r.text[:200]}",
            )
            raise RuntimeError(f"Google token exchange HTTP {r.status_code}")
        payload = r.json()

    access_token: Optional[str] = payload.get("access_token")
    refresh_token: Optional[str] = payload.get("refresh_token")
    expires_in: int = int(payload.get("expires_in", 3600))
    granted_scopes: Optional[str] = payload.get("scope")

    if not access_token or not refresh_token:
        # Google n'a pas renvoyé de refresh_token : on ne pourra pas
        # rafraîchir plus tard. Cf. prompt=consent dans authorize_url.
        await _audit(
            db,
            user_id=user_id,
            google_email=None,
            action="drive_user_token.connect_failed",
            success=False,
            error_message="missing refresh_token (forgot prompt=consent ?)",
        )
        raise RuntimeError("Google n'a pas renvoyé de refresh_token.")

    google_email = await _fetch_google_email(access_token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Upsert (user_id est unique).
    existing = (
        await db.execute(
            select(DriveUserToken).where(DriveUserToken.user_id == user_id)
        )
    ).scalar_one_or_none()

    if existing is None:
        row = DriveUserToken(
            user_id=user_id,
            google_email=google_email,
            access_token=_encrypt(access_token),
            refresh_token=_encrypt(refresh_token),
            expires_at=expires_at,
            granted_scopes=granted_scopes,
        )
        db.add(row)
    else:
        existing.google_email = google_email
        existing.access_token = _encrypt(access_token)
        existing.refresh_token = _encrypt(refresh_token)
        existing.expires_at = expires_at
        existing.granted_scopes = granted_scopes
        row = existing

    await db.flush()
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="drive_user_token.connected",
        details={"scopes": granted_scopes},
    )
    return row


async def _refresh(
    db: AsyncSession, row: DriveUserToken
) -> str:
    """Refresh l'access_token via le refresh_token stocké."""
    refresh_token = _decrypt(row.refresh_token)
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Accept": "application/json"},
            )
            if r.status_code >= 400:
                await _audit(
                    db,
                    user_id=row.user_id,
                    google_email=row.google_email,
                    action="drive_user_token.refresh_failed",
                    success=False,
                    error_message=f"http_{r.status_code}: {r.text[:200]}",
                )
                raise RuntimeError(f"refresh HTTP {r.status_code}")
            payload = r.json()
    except Exception as exc:
        await _audit(
            db,
            user_id=row.user_id,
            google_email=row.google_email,
            action="drive_user_token.refresh_failed",
            success=False,
            error_message=str(exc)[:200],
        )
        raise

    new_access = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 3600))
    if not new_access:
        raise RuntimeError("Google refresh sans access_token")

    row.access_token = _encrypt(new_access)
    row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    # Google peut occasionnellement renvoyer un nouveau refresh_token —
    # le persister pour rester aligné.
    new_refresh = payload.get("refresh_token")
    if new_refresh:
        row.refresh_token = _encrypt(new_refresh)
    await db.flush()
    await _audit(
        db,
        user_id=row.user_id,
        google_email=row.google_email,
        action="drive_user_token.token_refreshed",
    )
    return new_access


async def get_valid_access_token(
    db: AsyncSession, *, user_id: int
) -> Optional[str]:
    """Retourne un access_token valide ou None si l'utilisateur n'est pas connecté."""
    row = (
        await db.execute(
            select(DriveUserToken).where(DriveUserToken.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    expires_at = row.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is None or expires_at <= now + timedelta(
        seconds=_REFRESH_BUFFER_SECONDS
    ):
        return await _refresh(db, row)
    return _decrypt(row.access_token)


async def revoke_token(db: AsyncSession, *, user_id: int) -> None:
    """Révoque le refresh_token côté Google + supprime la ligne locale."""
    row = (
        await db.execute(
            select(DriveUserToken).where(DriveUserToken.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return
    google_email = row.google_email
    try:
        refresh_token = _decrypt(row.refresh_token)
        async with httpx.AsyncClient(timeout=10.0) as http:
            # Endpoint Google /revoke : 200 si OK, 400 si déjà révoqué
            # (on ignore les deux cas → toujours best-effort).
            await http.post(
                _GOOGLE_REVOKE_URL,
                data={"token": refresh_token},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                },
            )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Drive: revoke côté Google échoué (best-effort) : %s", exc
        )
    await db.execute(
        delete(DriveUserToken).where(DriveUserToken.user_id == user_id)
    )
    await db.flush()
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="drive_user_token.disconnected",
    )


async def get_user_email(
    db: AsyncSession, *, user_id: int
) -> Optional[str]:
    row = (
        await db.execute(
            select(DriveUserToken.google_email).where(
                DriveUserToken.user_id == user_id
            )
        )
    ).first()
    return row[0] if row else None


async def get_token_row(
    db: AsyncSession, *, user_id: int
) -> Optional[DriveUserToken]:
    """Retourne la ligne BDD complète (pour le endpoint /status)."""
    return (
        await db.execute(
            select(DriveUserToken).where(DriveUserToken.user_id == user_id)
        )
    ).scalar_one_or_none()


__all__ = [
    "DEFAULT_SCOPES",
    "exchange_code",
    "get_authorization_url",
    "get_token_row",
    "get_user_email",
    "get_valid_access_token",
    "revoke_token",
    "verify_state",
]
