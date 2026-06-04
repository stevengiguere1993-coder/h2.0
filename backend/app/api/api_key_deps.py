"""Dépendance d'authentification par clé d'API (lecture seule).

Ces clés ``krts_...`` n'ouvrent QUE les endpoints d'activité
(/api/v1/activity/*). Elles ne donnent accès qu'au compte de leur
propriétaire et ne sont jamais acceptées sur un endpoint de mutation.

Flux :
  1. Lire le secret depuis l'en-tête ``Authorization: Bearer krts_...``
     (ou, en repli, ``X-API-Key: krts_...``).
  2. Hasher (SHA-256) le secret reçu.
  3. Chercher une ApiKey active, non expirée, au hash correspondant.
  4. Charger le User propriétaire (actif).
  5. Mettre à jour ``last_used_at`` pour la traçabilité.
  6. 401 si quoi que ce soit manque / est invalide / révoqué / expiré.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.user import User


#: Préfixe obligatoire des clés d'API en clair.
API_KEY_PREFIX = "krts_"


def hash_api_key(raw_key: str) -> str:
    """Hash SHA-256 (hexdigest) d'une clé en clair. Déterministe : c'est
    ce qu'on stocke et ce sur quoi on cherche à l'authentification."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _extract_raw_key(
    authorization: Optional[str],
    x_api_key: Optional[str],
) -> Optional[str]:
    """Récupère le secret ``krts_...`` depuis l'en-tête Authorization
    (schéma Bearer) ou, en repli, X-API-Key. Retourne None si absent."""
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            candidate = parts[1].strip()
            if candidate.startswith(API_KEY_PREFIX):
                return candidate
    if x_api_key:
        candidate = x_api_key.strip()
        if candidate.startswith(API_KEY_PREFIX):
            return candidate
    return None


async def get_user_from_api_key(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
    x_api_key: Annotated[Optional[str], Header(alias="X-API-Key")] = None,
) -> User:
    """Authentifie une requête via clé d'API et retourne le User.

    Lève 401 si la clé est absente, invalide, révoquée, expirée, ou si
    l'utilisateur associé n'existe plus / est inactif.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Clé d'API invalide ou manquante.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    raw_key = _extract_raw_key(authorization, x_api_key)
    if not raw_key:
        raise credentials_exception

    key_hash = hash_api_key(raw_key)

    stmt = select(ApiKey).where(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active.is_(True),
    )
    api_key = (await db.execute(stmt)).scalar_one_or_none()
    if api_key is None:
        raise credentials_exception

    # Expiration (on compare en UTC ; les colonnes sont timezone-aware).
    now = datetime.now(timezone.utc)
    if api_key.expires_at is not None:
        expires_at = api_key.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise credentials_exception

    user = await db.get(User, api_key.user_id)
    if user is None or not user.is_active:
        raise credentials_exception

    # Traçabilité : dernier usage de la clé. Best-effort — un échec ici
    # ne doit pas casser l'authentification.
    try:
        api_key.last_used_at = now
        await db.flush()
    except Exception:
        pass

    return user


#: Alias type pour l'injection de dépendance dans les endpoints d'activité.
ApiKeyUser = Annotated[User, Depends(get_user_from_api_key)]
