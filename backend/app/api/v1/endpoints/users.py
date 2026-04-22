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

from app.api.deps import DBSession, RequireOwner
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
