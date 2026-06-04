"""Gestion des clés d'API personnelles (auth JWT).

  POST   /api/v1/api-keys        → génère une clé (retournée UNE fois)
  GET    /api/v1/api-keys        → liste les clés de l'utilisateur
  DELETE /api/v1/api-keys/{id}   → révoque une clé de l'utilisateur

Réservé à l'utilisateur lui-même : chacun ne voit et ne gère QUE ses
propres clés (scope strict par user_id). La clé en clair n'est JAMAIS
stockée — on ne garde que son hash SHA-256 + un préfixe lisible — et
n'est affichée qu'une seule fois, à la création.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.api_key_deps import API_KEY_PREFIX, hash_api_key
from app.api.deps import CurrentUser, DBSession
from app.models.api_key import ApiKey
from app.services.audit import log_action


router = APIRouter(prefix="/api-keys", tags=["api-keys"])


# ── Schémas ────────────────────────────────────────────────────────


class ApiKeyCreate(BaseModel):
    label: Optional[str] = None
    # Expiration optionnelle (ISO 8601). NULL = pas d'expiration.
    expires_at: Optional[datetime] = None


class ApiKeyRead(BaseModel):
    """Vue « sûre » d'une clé : jamais le secret ni le hash."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    key_prefix: str
    label: Optional[str]
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]


class ApiKeyCreated(ApiKeyRead):
    """Réponse de création : inclut le secret en clair, UNE seule fois."""

    api_key: str
    warning: str


# ── Endpoints ──────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Générer une clé d'API personnelle (lecture seule)",
)
async def create_api_key(
    payload: ApiKeyCreate,
    user: CurrentUser,
    db: DBSession,
) -> ApiKeyCreated:
    # Secret au format krts_<43 caractères urlsafe>. token_urlsafe(32)
    # produit ~43 caractères ; bien plus que le minimum demandé (32+).
    raw_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    key_hash = hash_api_key(raw_key)
    # Préfixe lisible : krts_ + 7 premiers caractères du secret (12 car.).
    key_prefix = raw_key[:12]

    api_key = ApiKey(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        label=(payload.label or None),
        is_active=True,
        expires_at=payload.expires_at,
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)

    await log_action(
        db,
        user=user,
        action="api_key.created",
        entity_type="api_key",
        entity_id=api_key.id,
        details={"label": api_key.label, "key_prefix": api_key.key_prefix},
    )

    return ApiKeyCreated(
        id=api_key.id,
        key_prefix=api_key.key_prefix,
        label=api_key.label,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        api_key=raw_key,
        warning=(
            "Copiez cette clé maintenant : elle ne sera plus jamais "
            "affichée. En cas de perte, révoquez-la et générez-en une "
            "nouvelle."
        ),
    )


@router.get(
    "",
    response_model=List[ApiKeyRead],
    summary="Lister mes clés d'API",
)
async def list_api_keys(
    user: CurrentUser,
    db: DBSession,
) -> List[ApiKeyRead]:
    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == user.id)
        .order_by(ApiKey.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [ApiKeyRead.model_validate(r) for r in rows]


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_200_OK,
    summary="Révoquer une de mes clés d'API",
)
async def revoke_api_key(
    key_id: int,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    # Scope strict : on ne peut révoquer QUE ses propres clés.
    stmt = select(ApiKey).where(
        ApiKey.id == key_id,
        ApiKey.user_id == user.id,
    )
    api_key = (await db.execute(stmt)).scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clé introuvable.",
        )

    api_key.is_active = False
    await db.flush()

    await log_action(
        db,
        user=user,
        action="api_key.revoked",
        entity_type="api_key",
        entity_id=api_key.id,
        details={"label": api_key.label, "key_prefix": api_key.key_prefix},
    )

    return {"status": "revoked", "id": api_key.id}
