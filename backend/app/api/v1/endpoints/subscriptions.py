"""Endpoints REST « Abonnements » — coffre de la compagnie.

Suivi des coûts logiciels + coffre à mots de passe chiffré.

Sécurité :
  - TOUTE la surface est réservée aux utilisateurs autorisés (liste
    nominative gérée par le proprio + proprio implicite) → dépendance
    :data:`VaultUser`.
  - La gestion de la liste d'accès est réservée au proprio
    (:data:`RequireOwner`).
  - Les mots de passe ne sont jamais renvoyés par la liste : seul
    ``GET /{id}/secret`` les déchiffre, et CHAQUE révélation est
    journalisée (audit log).
  - Le chiffrement est OBLIGATOIRE : si aucune clé n'est configurée, on
    refuse de stocker un mot de passe (jamais de clair).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from app.api.deps import CurrentUser, DBSession, RequireOwner
from app.models.subscription import Subscription
from app.models.subscription_vault_access import SubscriptionVaultAccess
from app.models.user import User
from app.services import subscription_access
from app.services.audit import log_action
from app.services.secret_vault import (
    VaultNotConfigured,
    decrypt_secret,
    encrypt_secret,
    vault_available,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


# ---------------------------------------------------------------------------
# Schémas
# ---------------------------------------------------------------------------


class SubscriptionRead(BaseModel):
    id: int
    name: str
    category: Optional[str] = None
    kind: str
    url: Optional[str] = None
    cost: Optional[float] = None
    currency: str
    billing_cycle: str
    next_renewal_at: Optional[date] = None
    paid_by: Optional[str] = None
    owner_user_id: Optional[int] = None
    login_username: Optional[str] = None
    # On n'expose JAMAIS le mot de passe ici — juste s'il y en a un.
    has_secret: bool
    notes: Optional[str] = None
    display_order: int


class SubscriptionCreate(BaseModel):
    name: str
    category: Optional[str] = None
    kind: str = "shared"
    url: Optional[str] = None
    cost: Optional[float] = None
    currency: str = "CAD"
    billing_cycle: str = "monthly"
    next_renewal_at: Optional[date] = None
    paid_by: Optional[str] = None
    owner_user_id: Optional[int] = None
    login_username: Optional[str] = None
    # Mot de passe en clair en ENTRÉE seulement → chiffré au repos.
    password: Optional[str] = None
    notes: Optional[str] = None


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    kind: Optional[str] = None
    url: Optional[str] = None
    cost: Optional[float] = None
    currency: Optional[str] = None
    billing_cycle: Optional[str] = None
    next_renewal_at: Optional[date] = None
    paid_by: Optional[str] = None
    owner_user_id: Optional[int] = None
    login_username: Optional[str] = None
    # Absent = inchangé ; "" = effacer ; valeur = remplacer.
    password: Optional[str] = None
    notes: Optional[str] = None
    display_order: Optional[int] = None


class SecretRead(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None


class VaultStatus(BaseModel):
    has_access: bool
    encryption_configured: bool


class AccessUser(BaseModel):
    user_id: int
    name: str
    email: str
    is_owner: bool


class AccessList(BaseModel):
    authorized: List[AccessUser]
    all_users: List[AccessUser]


class AccessUpdate(BaseModel):
    user_ids: List[int]


# ---------------------------------------------------------------------------
# Dépendance d'accès au coffre
# ---------------------------------------------------------------------------


async def _require_vault(db: DBSession, user: CurrentUser) -> User:
    if not await subscription_access.user_has_vault_access(db, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Accès au coffre Abonnements non autorisé.",
        )
    return user


VaultUser = Annotated[User, Depends(_require_vault)]


def _to_read(s: Subscription) -> SubscriptionRead:
    return SubscriptionRead(
        id=s.id,
        name=s.name,
        category=s.category,
        kind=s.kind,
        url=s.url,
        cost=float(s.cost) if s.cost is not None else None,
        currency=s.currency,
        billing_cycle=s.billing_cycle,
        next_renewal_at=s.next_renewal_at,
        paid_by=s.paid_by,
        owner_user_id=s.owner_user_id,
        login_username=s.login_username,
        has_secret=bool(s.secret_ciphertext),
        notes=s.notes,
        display_order=s.display_order,
    )


def _user_to_access(u: User) -> AccessUser:
    name = (
        " ".join(x for x in [u.first_name, u.last_name] if x).strip()
        or u.email
    )
    return AccessUser(
        user_id=u.id, name=name, email=u.email, is_owner=(u.role == "owner")
    )


# ---------------------------------------------------------------------------
# Statut (consommé par le frontend pour décider d'afficher l'onglet)
# ---------------------------------------------------------------------------


@router.get("/vault-status", response_model=VaultStatus)
async def vault_status(db: DBSession, user: CurrentUser) -> VaultStatus:
    """Dit au frontend si l'utilisateur a accès + si le chiffrement est prêt."""
    return VaultStatus(
        has_access=await subscription_access.user_has_vault_access(db, user),
        encryption_configured=vault_available(),
    )


# ---------------------------------------------------------------------------
# Gestion de la liste d'accès (proprio uniquement)
# ---------------------------------------------------------------------------


@router.get("/access", response_model=AccessList)
async def get_access(db: DBSession, owner: RequireOwner) -> AccessList:
    granted = set(await subscription_access.list_access_user_ids(db))
    users = (
        await db.execute(
            select(User)
            .where(User.is_active.is_(True))
            .order_by(User.first_name.asc(), User.email.asc())
        )
    ).scalars().all()
    authorized = [
        _user_to_access(u)
        for u in users
        if u.id in granted or u.role == "owner"
    ]
    return AccessList(
        authorized=authorized,
        all_users=[_user_to_access(u) for u in users],
    )


@router.put("/access", response_model=AccessList)
async def set_access(
    db: DBSession,
    owner: RequireOwner,
    payload: AccessUpdate = Body(...),
) -> AccessList:
    wanted = {uid for uid in payload.user_ids}
    existing = set(await subscription_access.list_access_user_ids(db))
    to_remove = existing - wanted
    to_add = wanted - existing
    if to_remove:
        await db.execute(
            delete(SubscriptionVaultAccess).where(
                SubscriptionVaultAccess.user_id.in_(to_remove)
            )
        )
    for uid in to_add:
        db.add(
            SubscriptionVaultAccess(
                user_id=uid, granted_by_user_id=owner.id
            )
        )
    await db.flush()
    await log_action(
        db,
        user=owner,
        action="subscription.access_updated",
        entity_type="subscription_vault",
        details={"authorized_user_ids": sorted(wanted)},
    )
    return await get_access(db, owner)


# ---------------------------------------------------------------------------
# CRUD abonnements
# ---------------------------------------------------------------------------


@router.get("", response_model=List[SubscriptionRead])
async def list_subscriptions(
    db: DBSession, user: VaultUser
) -> List[SubscriptionRead]:
    rows = (
        await db.execute(
            select(Subscription).order_by(
                Subscription.display_order.asc(), Subscription.id.asc()
            )
        )
    ).scalars().all()
    return [_to_read(s) for s in rows]


@router.post("", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    db: DBSession,
    user: VaultUser,
    payload: SubscriptionCreate = Body(...),
) -> SubscriptionRead:
    ciphertext: Optional[str] = None
    if payload.password:
        try:
            ciphertext = encrypt_secret(payload.password)
        except VaultNotConfigured as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc))

    max_order = (
        await db.execute(select(func.max(Subscription.display_order)))
    ).scalar()
    sub = Subscription(
        name=payload.name.strip(),
        category=payload.category,
        kind=payload.kind if payload.kind in ("shared", "personal") else "shared",
        url=payload.url,
        cost=payload.cost,
        currency=payload.currency or "CAD",
        billing_cycle=(
            payload.billing_cycle
            if payload.billing_cycle in ("monthly", "yearly")
            else "monthly"
        ),
        next_renewal_at=payload.next_renewal_at,
        paid_by=payload.paid_by,
        owner_user_id=payload.owner_user_id,
        login_username=payload.login_username,
        secret_ciphertext=ciphertext,
        notes=payload.notes,
        display_order=int(max_order or 0) + 1,
        created_by_email=user.email,
    )
    db.add(sub)
    await db.flush()
    await db.refresh(sub)
    await log_action(
        db,
        user=user,
        action="subscription.created",
        entity_type="subscription",
        entity_id=sub.id,
        details={"name": sub.name, "kind": sub.kind},
    )
    return _to_read(sub)


@router.patch("/{sub_id}", response_model=SubscriptionRead)
async def update_subscription(
    sub_id: int,
    db: DBSession,
    user: VaultUser,
    payload: SubscriptionUpdate = Body(...),
) -> SubscriptionRead:
    sub = (
        await db.execute(select(Subscription).where(Subscription.id == sub_id))
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Abonnement introuvable.")

    data = payload.model_dump(exclude_unset=True)

    # Mot de passe : géré à part (chiffrement / effacement).
    if "password" in data:
        pwd = data.pop("password")
        if pwd:
            try:
                sub.secret_ciphertext = encrypt_secret(pwd)
            except VaultNotConfigured as exc:
                raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
        else:
            # "" → on efface le mot de passe stocké.
            sub.secret_ciphertext = None

    for field, value in data.items():
        if field == "kind" and value not in ("shared", "personal"):
            continue
        if field == "billing_cycle" and value not in ("monthly", "yearly"):
            continue
        setattr(sub, field, value)

    await db.flush()
    await db.refresh(sub)
    await log_action(
        db,
        user=user,
        action="subscription.updated",
        entity_type="subscription",
        entity_id=sub.id,
        details={"fields": sorted(data.keys())},
    )
    return _to_read(sub)


@router.delete("/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    sub_id: int, db: DBSession, user: VaultUser
) -> None:
    sub = (
        await db.execute(select(Subscription).where(Subscription.id == sub_id))
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Abonnement introuvable.")
    name = sub.name
    await db.delete(sub)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="subscription.deleted",
        entity_type="subscription",
        entity_id=sub_id,
        details={"name": name},
    )


@router.get("/{sub_id}/secret", response_model=SecretRead)
async def reveal_secret(
    sub_id: int, db: DBSession, user: VaultUser
) -> SecretRead:
    """Déchiffre et renvoie les identifiants. CHAQUE appel est journalisé."""
    sub = (
        await db.execute(select(Subscription).where(Subscription.id == sub_id))
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Abonnement introuvable.")

    password: Optional[str] = None
    if sub.secret_ciphertext:
        try:
            password = decrypt_secret(sub.secret_ciphertext)
        except (VaultNotConfigured, ValueError) as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc))

    await log_action(
        db,
        user=user,
        action="subscription.secret_revealed",
        entity_type="subscription",
        entity_id=sub.id,
        details={"name": sub.name},
    )
    return SecretRead(username=sub.login_username, password=password)
