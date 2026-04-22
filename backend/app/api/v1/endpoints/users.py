"""User management — owner-only.

    GET    /api/v1/users                   — list all users
    PATCH  /api/v1/users/{id}/role         — change role
    POST   /api/v1/users/{id}/deactivate   — disable account
    POST   /api/v1/users/{id}/activate     — re-enable account
    GET    /api/v1/users/{id}/projects     — project members for this user
    PUT    /api/v1/users/{id}/projects     — set assigned projects (bulk)

Creating new users via email + password is handled by /auth/register for
now; this module is only concerned with role + permission management.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, insert, select

from app.api.deps import DBSession, RequireAdminRole, RequireOwner
from app.core.security import get_password_hash
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User, UserRole


router = APIRouter(prefix="/users", tags=["users-admin"])


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    is_active: bool
    is_admin: bool
    role: str
    created_at: datetime


class RoleUpdate(BaseModel):
    role: str = Field(..., pattern="^(owner|admin|manager|employee)$")


class ProjectAssignments(BaseModel):
    project_ids: List[int]


class ProjectMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    address: Optional[str] = None
    status: Optional[str] = None


@router.get("", response_model=List[UserRead])
async def list_users(db: DBSession, _: RequireOwner) -> List[UserRead]:
    rows = (
        await db.execute(select(User).order_by(User.email.asc()))
    ).scalars().all()
    return [UserRead.model_validate(r) for r in rows]


@router.patch("/{user_id}/role", response_model=UserRead)
async def update_role(
    user_id: int,
    data: RoleUpdate,
    db: DBSession,
    owner: RequireOwner,
) -> UserRead:
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    # Owners can't demote themselves to prevent locking out the account.
    if u.id == owner.id and data.role != UserRole.OWNER.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Tu ne peux pas rétrograder ton propre compte.",
        )
    u.role = data.role
    # Keep the legacy is_admin flag in sync so old code paths still work.
    u.is_admin = data.role in (UserRole.OWNER.value, UserRole.ADMIN.value)
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


@router.post("/{user_id}/deactivate", response_model=UserRead)
async def deactivate(
    user_id: int,
    db: DBSession,
    owner: RequireOwner,
) -> UserRead:
    if user_id == owner.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Tu ne peux pas te désactiver."
        )
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    u.is_active = False
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


@router.post("/{user_id}/activate", response_model=UserRead)
async def activate(
    user_id: int,
    db: DBSession,
    _: RequireOwner,
) -> UserRead:
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    u.is_active = True
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


# ---------- Password management (admin / owner) ----------

class SetPasswordBody(BaseModel):
    """Admin sets a user's password directly. If `must_change` is True,
    the user is forced to change it at next login."""

    password: str = Field(..., min_length=8, max_length=128)
    must_change: bool = Field(default=True)


@router.post("/{user_id}/set-password", response_model=UserRead)
async def set_password(
    user_id: int,
    body: SetPasswordBody,
    db: DBSession,
    _: RequireAdminRole,
) -> UserRead:
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    u.hashed_password = get_password_hash(body.password)
    u.must_change_password = body.must_change
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer définitivement un compte utilisateur (owner)",
)
async def delete_user(
    user_id: int,
    db: DBSession,
    owner: RequireOwner,
) -> None:
    """Hard-delete : supprime la ligne. Les FK pointant vers ce user
    (ProjectMember, Notifications, AuditLog, AvailabilitySlot, feed
    iCal…) sont géré·es par les ON DELETE de leurs propres déclarations
    (CASCADE ou SET NULL).

    Sécurités :
      - Un owner ne peut pas se supprimer lui-même
      - On bloque la suppression du dernier owner actif (sinon plus
        personne ne peut gérer les rôles)
    """
    if user_id == owner.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Tu ne peux pas supprimer ton propre compte.",
        )
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if u.role == UserRole.OWNER.value:
        # Compte les autres owners actifs encore présents.
        from sqlalchemy import func

        remaining = (
            await db.execute(
                select(func.count(User.id)).where(
                    User.role == UserRole.OWNER.value,
                    User.is_active.is_(True),
                    User.id != user_id,
                )
            )
        ).scalar_one()
        if int(remaining or 0) == 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Impossible de supprimer le dernier propriétaire actif. "
                "Crée un autre owner d'abord.",
            )

    await db.delete(u)
    await db.flush()


@router.post("/{user_id}/force-password-change", response_model=UserRead)
async def force_password_change(
    user_id: int,
    db: DBSession,
    _: RequireAdminRole,
) -> UserRead:
    """Just flips the must_change_password flag without rotating the
    password. Used when an admin wants to invite a user to update an
    expired password without choosing a new one for them."""
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    u.must_change_password = True
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


@router.get("/{user_id}/projects", response_model=List[ProjectMini])
async def get_user_projects(
    user_id: int,
    db: DBSession,
    _: RequireOwner,
) -> List[ProjectMini]:
    stmt = (
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id)
        .order_by(Project.name.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [ProjectMini.model_validate(r) for r in rows]


@router.put("/{user_id}/projects", response_model=List[int])
async def set_user_projects(
    user_id: int,
    data: ProjectAssignments,
    db: DBSession,
    _: RequireOwner,
) -> List[int]:
    """Replace the user's project assignments with the given set.
    Returns the IDs persisted."""
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # Validate all project ids exist so we don't silently accept typos.
    if data.project_ids:
        existing = (
            await db.execute(
                select(Project.id).where(Project.id.in_(data.project_ids))
            )
        ).all()
        existing_ids = {int(r[0]) for r in existing}
        unknown = set(data.project_ids) - existing_ids
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Projet(s) inconnu(s): {sorted(unknown)}",
            )

    # Wipe and reinsert — simpler than computing a diff for a handful of rows.
    await db.execute(
        delete(ProjectMember).where(ProjectMember.user_id == user_id)
    )
    if data.project_ids:
        await db.execute(
            insert(ProjectMember),
            [
                {"user_id": user_id, "project_id": pid}
                for pid in set(data.project_ids)
            ],
        )
    await db.flush()
    return list(set(data.project_ids))
