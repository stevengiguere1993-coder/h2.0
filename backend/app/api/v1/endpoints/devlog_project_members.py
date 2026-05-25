"""Endpoints des membres d'un projet Dev Logiciel.

    GET    /api/v1/devlog/projects/{project_id}/members
    POST   /api/v1/devlog/projects/{project_id}/members
    PATCH  /api/v1/devlog/projects/{project_id}/members/{member_id}
    DELETE /api/v1/devlog/projects/{project_id}/members/{member_id}

Un membre est soit un User interne (employe / dev), soit un
DevlogSousTraitant (freelance). L'un des deux doit etre fourni.
Tous proteges par le guard admin/owner du pole (au router parent)
et loguent les mutations dans audit_logs.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_member import DevlogProjectMember
from app.models.devlog_sous_traitant import DevlogSousTraitant
from app.models.user import User
from app.schemas.devlog import (
    DevlogProjectMemberCreate,
    DevlogProjectMemberRead,
    DevlogProjectMemberUpdate,
)
from app.services.audit import log_action


router = APIRouter(prefix="/devlog/projects", tags=["devlog-project-members"])


async def _get_project_or_404(db, project_id: int) -> DevlogProject:
    obj = (
        await db.execute(
            select(DevlogProject).where(DevlogProject.id == project_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable")
    return obj


async def _validate_membership(
    db, project_id: int, user_id, sous_traitant_id, exclude_member_id=None
) -> None:
    """Verifie qu'exactement un des deux refs est fourni, qu'il existe
    et qu'il n'y a pas deja un membre actif pour ce ref sur ce projet."""
    if (user_id is None) == (sous_traitant_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Fournir exactement user_id OU sous_traitant_id",
        )
    if user_id is not None:
        exists = (
            await db.execute(select(User.id).where(User.id == user_id))
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Utilisateur introuvable",
            )
    if sous_traitant_id is not None:
        exists = (
            await db.execute(
                select(DevlogSousTraitant.id).where(
                    DevlogSousTraitant.id == sous_traitant_id
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Sous-traitant introuvable",
            )
    # Pas de doublon (meme user/sous-traitant deja membre du projet).
    dup_stmt = select(DevlogProjectMember.id).where(
        DevlogProjectMember.project_id == project_id
    )
    if user_id is not None:
        dup_stmt = dup_stmt.where(DevlogProjectMember.user_id == user_id)
    else:
        dup_stmt = dup_stmt.where(
            DevlogProjectMember.sous_traitant_id == sous_traitant_id
        )
    if exclude_member_id is not None:
        dup_stmt = dup_stmt.where(DevlogProjectMember.id != exclude_member_id)
    dup = (await db.execute(dup_stmt)).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce membre est deja assigne au projet",
        )


@router.get(
    "/{project_id}/members",
    response_model=List[DevlogProjectMemberRead],
)
async def list_members(
    project_id: int, db: DBSession, _: CurrentUser
) -> List[DevlogProjectMemberRead]:
    await _get_project_or_404(db, project_id)
    rows = (
        await db.execute(
            select(DevlogProjectMember)
            .where(DevlogProjectMember.project_id == project_id)
            .order_by(DevlogProjectMember.added_at.asc())
        )
    ).scalars().all()
    return [DevlogProjectMemberRead.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/members",
    response_model=DevlogProjectMemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    project_id: int,
    data: DevlogProjectMemberCreate,
    db: DBSession,
    user: CurrentUser,
) -> DevlogProjectMemberRead:
    await _get_project_or_404(db, project_id)
    await _validate_membership(
        db, project_id, data.user_id, data.sous_traitant_id
    )
    obj = DevlogProjectMember(
        project_id=project_id,
        user_id=data.user_id,
        sous_traitant_id=data.sous_traitant_id,
        role=(data.role.strip() if data.role else None),
        hourly_rate=data.hourly_rate,
        added_by_user_id=user.id,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_project_member.created",
        entity_type="devlog_project_member",
        entity_id=obj.id,
        details={
            "project_id": project_id,
            "user_id": data.user_id,
            "sous_traitant_id": data.sous_traitant_id,
            "role": obj.role,
        },
    )
    return DevlogProjectMemberRead.model_validate(obj)


@router.patch(
    "/{project_id}/members/{member_id}",
    response_model=DevlogProjectMemberRead,
)
async def update_member(
    project_id: int,
    member_id: int,
    data: DevlogProjectMemberUpdate,
    db: DBSession,
    user: CurrentUser,
) -> DevlogProjectMemberRead:
    await _get_project_or_404(db, project_id)
    obj = (
        await db.execute(
            select(DevlogProjectMember).where(
                DevlogProjectMember.id == member_id,
                DevlogProjectMember.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membre introuvable")
    fields = data.model_dump(exclude_unset=True)
    if "role" in fields and isinstance(fields["role"], str):
        fields["role"] = fields["role"].strip() or None
    for field, value in fields.items():
        setattr(obj, field, value)
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_project_member.updated",
        entity_type="devlog_project_member",
        entity_id=obj.id,
        details={"project_id": project_id, **fields},
    )
    return DevlogProjectMemberRead.model_validate(obj)


@router.delete(
    "/{project_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    project_id: int,
    member_id: int,
    db: DBSession,
    user: CurrentUser,
) -> None:
    await _get_project_or_404(db, project_id)
    obj = (
        await db.execute(
            select(DevlogProjectMember).where(
                DevlogProjectMember.id == member_id,
                DevlogProjectMember.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membre introuvable")
    await db.delete(obj)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="devlog_project_member.deleted",
        entity_type="devlog_project_member",
        entity_id=member_id,
        details={"project_id": project_id},
    )
