"""Rôles fonctionnels des utilisateurs — closer, gestionnaire,
chargé de projet, technicien, admin office.

Endpoints :
  GET    /api/v1/user-roles                              — liste tous les rôles assignés (admin)
  GET    /api/v1/user-roles/me                           — mes propres rôles (n'importe quel user)
  GET    /api/v1/user-roles/by-role/{role_kind}          — users d'un rôle donné
  POST   /api/v1/user-roles                              — assigne un rôle à un user (admin)
  DELETE /api/v1/user-roles/{role_id}                    — retire un rôle (admin)
  GET    /api/v1/user-roles/kinds                        — liste des rôles disponibles
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, CurrentUser, DBSession
from app.models.user import User
from app.models.user_business_role import (
    FUNCTIONAL_ROLE_LABELS,
    FunctionalRole,
    UserBusinessRole,
)


router = APIRouter(prefix="/user-roles", tags=["user-roles"])


class UserRoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    role_kind: str
    notes: Optional[str]


class UserRoleWithUser(UserRoleRead):
    user_email: Optional[str] = None
    user_first_name: Optional[str] = None
    user_last_name: Optional[str] = None


class UserRoleCreate(BaseModel):
    user_id: int
    role_kind: str = Field(..., max_length=32)
    notes: Optional[str] = Field(default=None, max_length=255)


class RoleKindOption(BaseModel):
    kind: str
    label: str


@router.get(
    "/kinds",
    response_model=List[RoleKindOption],
    summary="Liste des rôles fonctionnels disponibles",
)
async def list_role_kinds(_: CurrentUser) -> List[RoleKindOption]:
    return [
        RoleKindOption(kind=k, label=v) for k, v in FUNCTIONAL_ROLE_LABELS.items()
    ]


@router.get(
    "",
    response_model=List[UserRoleWithUser],
    summary="Liste tous les rôles assignés (admin)",
)
async def list_all_roles(
    _: CurrentAdmin, db: DBSession
) -> List[UserRoleWithUser]:
    rows = (
        await db.execute(
            select(UserBusinessRole, User)
            .join(User, User.id == UserBusinessRole.user_id)
            .order_by(UserBusinessRole.role_kind, User.email)
        )
    ).all()
    out: List[UserRoleWithUser] = []
    for ur, user in rows:
        out.append(
            UserRoleWithUser(
                id=ur.id,
                user_id=ur.user_id,
                role_kind=ur.role_kind,
                notes=ur.notes,
                user_email=user.email,
                user_first_name=user.first_name,
                user_last_name=user.last_name,
            )
        )
    return out


@router.get(
    "/me",
    response_model=List[UserRoleRead],
    summary="Mes propres rôles",
)
async def list_my_roles(
    user: CurrentUser, db: DBSession
) -> List[UserRoleRead]:
    rows = (
        await db.execute(
            select(UserBusinessRole).where(
                UserBusinessRole.user_id == user.id
            )
        )
    ).scalars().all()
    return [UserRoleRead.model_validate(r) for r in rows]


@router.get(
    "/by-role/{role_kind}",
    response_model=List[UserRoleWithUser],
    summary="Liste des users ayant un rôle donné",
)
async def list_by_role(
    role_kind: str, _: CurrentUser, db: DBSession
) -> List[UserRoleWithUser]:
    if role_kind not in FUNCTIONAL_ROLE_LABELS:
        raise HTTPException(
            status_code=400,
            detail=f"role_kind inconnu : {role_kind}",
        )
    rows = (
        await db.execute(
            select(UserBusinessRole, User)
            .join(User, User.id == UserBusinessRole.user_id)
            .where(
                UserBusinessRole.role_kind == role_kind,
                User.is_active.is_(True),
            )
            .order_by(User.email)
        )
    ).all()
    out: List[UserRoleWithUser] = []
    for ur, user in rows:
        out.append(
            UserRoleWithUser(
                id=ur.id,
                user_id=ur.user_id,
                role_kind=ur.role_kind,
                notes=ur.notes,
                user_email=user.email,
                user_first_name=user.first_name,
                user_last_name=user.last_name,
            )
        )
    return out


@router.post(
    "",
    response_model=UserRoleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Assigne un rôle à un user (admin)",
)
async def assign_role(
    payload: UserRoleCreate, _: CurrentAdmin, db: DBSession
) -> UserRoleRead:
    if payload.role_kind not in FUNCTIONAL_ROLE_LABELS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"role_kind inconnu. Valeurs : {list(FUNCTIONAL_ROLE_LABELS.keys())}"
            ),
        )
    user_exists = (
        await db.execute(select(User).where(User.id == payload.user_id))
    ).scalar_one_or_none()
    if user_exists is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    # Idempotent : si déjà assigné, on met juste à jour les notes.
    existing = (
        await db.execute(
            select(UserBusinessRole).where(
                UserBusinessRole.user_id == payload.user_id,
                UserBusinessRole.role_kind == payload.role_kind,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.notes = payload.notes or existing.notes
        await db.flush()
        return UserRoleRead.model_validate(existing)
    ur = UserBusinessRole(
        user_id=payload.user_id,
        role_kind=payload.role_kind,
        notes=payload.notes,
    )
    db.add(ur)
    await db.flush()
    await db.refresh(ur)
    return UserRoleRead.model_validate(ur)


@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire un rôle (admin)",
)
async def revoke_role(
    role_id: int, _: CurrentAdmin, db: DBSession
) -> None:
    ur = (
        await db.execute(
            select(UserBusinessRole).where(UserBusinessRole.id == role_id)
        )
    ).scalar_one_or_none()
    if ur is None:
        raise HTTPException(status_code=404, detail="role_assignment_not_found")
    await db.delete(ur)
    await db.flush()
