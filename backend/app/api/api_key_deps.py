"""Dépendance d'authentification par clé d'API + permissions par pôle.

Ces clés ``krts_...`` n'ouvrent QUE des endpoints explicitement prévus
pour elles (activité en lecture, et écritures autorisées par scope, ex.
créer une tâche d'un pôle). Elles ne donnent accès qu'au compte de leur
propriétaire.

Flux d'auth :
  1. Lire le secret depuis l'en-tête ``Authorization: Bearer krts_...``
     (ou, en repli, ``X-API-Key: krts_...``).
  2. Hasher (SHA-256) le secret reçu.
  3. Chercher une ApiKey active, non expirée, au hash correspondant.
  4. Charger le User propriétaire (actif).
  5. Mettre à jour ``last_used_at`` pour la traçabilité.
  6. 401 si quoi que ce soit manque / est invalide / révoqué / expiré.

Permissions PAR PÔLE : chaque clé porte des ``scopes`` au format
``<pole>:<capability>``. ``get_api_context`` retourne le contexte
(User + scopes) ; ``require_scope("<pole>:<cap>")`` est une fabrique de
dépendance qui renvoie 403 propre si la capacité n'est pas accordée à la
clé pour ce pôle. RÉTROCOMPAT : une clé sans scopes (ou avec l'ancien
``activity:read``) lit TOUS les pôles.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.user import User
from app.services.api_capabilities import (
    CAPABILITIES_BY_ID,
    POLE_LABELS,
    key_has_scope,
)


#: Préfixe obligatoire des clés d'API en clair.
API_KEY_PREFIX = "krts_"


def hash_api_key(raw_key: str) -> str:
    """Hash SHA-256 (hexdigest) d'une clé en clair. Déterministe : c'est
    ce qu'on stocke et ce sur quoi on cherche à l'authentification."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


@dataclass
class ApiContext:
    """Contexte d'une requête authentifiée par clé d'API : l'utilisateur
    propriétaire + les scopes (permissions par pôle) de la clé utilisée."""

    user: User
    scopes: Optional[list[str]]

    def has_scope(self, scope: str) -> bool:
        return key_has_scope(self.scopes, scope)


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


async def get_api_context(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
    x_api_key: Annotated[Optional[str], Header(alias="X-API-Key")] = None,
) -> ApiContext:
    """Authentifie une requête via clé d'API et retourne le contexte
    (User + scopes de la clé).

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

    # Capture les scopes AVANT de toucher à la clé (rien ne les modifie ici).
    scopes = api_key.scopes

    # Traçabilité : dernier usage de la clé. Best-effort — un échec ici
    # ne doit pas casser l'authentification.
    try:
        api_key.last_used_at = now
        await db.flush()
    except Exception:
        pass

    return ApiContext(user=user, scopes=scopes)


async def get_user_from_api_key(
    ctx: Annotated[ApiContext, Depends(get_api_context)],
) -> User:
    """Authentifie une requête via clé d'API et retourne le User.

    Conservé pour la rétrocompatibilité des endpoints existants : la
    logique d'auth vit désormais dans ``get_api_context`` (qui porte aussi
    les scopes). Les endpoints de lecture qui filtrent par pôle préfèrent
    dépendre directement de ``ApiKeyContext``."""
    return ctx.user


def require_scope(scope: str):
    """Fabrique une dépendance FastAPI qui exige la capacité ``scope``
    (ex. ``devlog:tasks:create``) sur la clé d'API. Renvoie 403 propre si
    la capacité n'est pas accordée pour ce pôle. Retourne l'``ApiContext``
    en cas de succès (utilisable comme dépendance ET injection).

    RÉTROCOMPAT gérée par ``key_has_scope`` : une clé sans scopes lit tous
    les pôles mais n'a AUCUNE capacité d'écriture."""

    async def _dep(
        ctx: Annotated[ApiContext, Depends(get_api_context)],
    ) -> ApiContext:
        if not ctx.has_scope(scope):
            cap = CAPABILITIES_BY_ID.get(scope)
            pole_slug = cap["pole"] if cap else scope.split(":", 1)[0]
            pole_label = POLE_LABELS.get(pole_slug, pole_slug)
            label = cap["label_fr"] if cap else scope
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Capacité « {label} » non activée pour le pôle "
                    f"« {pole_label} » sur cette clé d'API."
                ),
            )
        return ctx

    return _dep


#: Alias type pour l'injection de dépendance dans les endpoints d'activité.
ApiKeyUser = Annotated[User, Depends(get_user_from_api_key)]

#: Alias type : contexte complet (User + scopes) pour les endpoints qui
#: filtrent la lecture par pôle.
ApiKeyContext = Annotated[ApiContext, Depends(get_api_context)]
