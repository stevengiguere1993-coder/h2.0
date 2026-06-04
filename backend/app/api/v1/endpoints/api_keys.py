"""Gestion des clés d'API personnelles (auth JWT) + permissions par pôle.

  POST   /api/v1/api-keys              → génère une clé (retournée UNE fois)
  GET    /api/v1/api-keys              → liste les clés de l'utilisateur
  GET    /api/v1/api-keys/capabilities → catalogue des capacités par pôle
  PATCH  /api/v1/api-keys/{id}         → met à jour les permissions (scopes)
  DELETE /api/v1/api-keys/{id}         → révoque une clé de l'utilisateur

Réservé à l'utilisateur lui-même : chacun ne voit et ne gère QUE ses
propres clés (scope strict par user_id). La clé en clair n'est JAMAIS
stockée — on ne garde que son hash SHA-256 + un préfixe lisible — et
n'est affichée qu'une seule fois, à la création.

Permissions PAR PÔLE (``scopes``) : chaque clé porte une liste de scopes
``<pole>:<capability>``. Le catalogue (pôles + capacités) vit dans
``app.services.api_capabilities``. Défaut sûr à la création : lecture de
TOUS les pôles (``<pole>:activity:read`` pour chaque pôle), aucune
écriture. Rétrocompat : une clé sans scopes lit déjà tous les pôles.
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
from app.services.api_capabilities import (
    POLE_SLUGS,
    catalog,
    sanitize_scopes,
)
from app.services.audit import log_action


router = APIRouter(prefix="/api-keys", tags=["api-keys"])


#: Défaut sûr à la création d'une clé : lecture de TOUS les pôles, aucune
#: écriture. Cohérent avec la rétrocompat (clé sans scopes = lecture tous
#: pôles) tout en rendant les scopes EXPLICITES dès la génération.
def _default_scopes() -> list[str]:
    return [f"{slug}:activity:read" for slug in POLE_SLUGS]


# ── Schémas ────────────────────────────────────────────────────────


class ApiKeyCreate(BaseModel):
    label: Optional[str] = None
    # Expiration optionnelle (ISO 8601). NULL = pas d'expiration.
    expires_at: Optional[datetime] = None
    # Permissions par pôle. NULL → défaut sûr (lecture de tous les pôles).
    scopes: Optional[List[str]] = None


class ApiKeyUpdate(BaseModel):
    # Remplace intégralement la liste de scopes de la clé. [] = aucune
    # permission (la clé ne pourra plus rien faire jusqu'à réactivation).
    scopes: List[str]


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
    scopes: List[str]


class ApiKeyCreated(ApiKeyRead):
    """Réponse de création : inclut le secret en clair, UNE seule fois."""

    api_key: str
    warning: str


def _to_read(api_key: ApiKey) -> ApiKeyRead:
    """Vue sûre d'une clé. Les scopes NULL (rétrocompat) sont exposés comme
    le défaut « lecture de tous les pôles » pour que l'UI affiche un état
    cohérent (interrupteurs de lecture déjà activés)."""
    scopes = api_key.scopes
    if not scopes:
        scopes = _default_scopes()
    return ApiKeyRead(
        id=api_key.id,
        key_prefix=api_key.key_prefix,
        label=api_key.label,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        scopes=scopes,
    )


# ── Catalogue des capacités (par pôle) ─────────────────────────────


@router.get(
    "/capabilities",
    summary="Catalogue des capacités d'API, groupées par pôle",
)
async def list_capabilities(user: CurrentUser) -> dict:
    """Retourne les pôles et, pour chacun, ses capacités activables
    (id ``<pole>:<cap>``, label FR, description, catégorie, risque,
    coming_soon). Source unique pour construire l'UI des interrupteurs."""
    return catalog()


# ── Endpoints CRUD ─────────────────────────────────────────────────


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Générer une clé d'API personnelle",
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

    # Scopes : si le client en fournit, on les nettoie (ne garde que des
    # capacités réelles, non « à venir ») ; sinon défaut sûr = lecture de
    # tous les pôles.
    if payload.scopes is None:
        scopes = _default_scopes()
    else:
        scopes = sanitize_scopes(payload.scopes)

    api_key = ApiKey(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        label=(payload.label or None),
        is_active=True,
        expires_at=payload.expires_at,
    )
    api_key.scopes = scopes
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)

    await log_action(
        db,
        user=user,
        action="api_key.created",
        entity_type="api_key",
        entity_id=api_key.id,
        details={
            "label": api_key.label,
            "key_prefix": api_key.key_prefix,
            "scopes": scopes,
        },
    )

    read = _to_read(api_key)
    return ApiKeyCreated(
        **read.model_dump(),
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
    return [_to_read(r) for r in rows]


@router.patch(
    "/{key_id}",
    response_model=ApiKeyRead,
    summary="Mettre à jour les permissions (scopes) d'une de mes clés",
)
async def update_api_key_scopes(
    key_id: int,
    payload: ApiKeyUpdate,
    user: CurrentUser,
    db: DBSession,
) -> ApiKeyRead:
    # Scope strict : on ne modifie QUE ses propres clés.
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

    # Nettoyage : ne garde que des capacités réelles (existantes, non
    # « à venir »). Un scope inconnu est silencieusement écarté.
    scopes = sanitize_scopes(payload.scopes)
    api_key.scopes = scopes
    await db.flush()

    await log_action(
        db,
        user=user,
        action="api_key.scopes_updated",
        entity_type="api_key",
        entity_id=api_key.id,
        details={"key_prefix": api_key.key_prefix, "scopes": scopes},
    )

    await db.refresh(api_key)
    return _to_read(api_key)


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
