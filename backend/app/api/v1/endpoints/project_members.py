"""Project members — which users are assigned to a project.

    GET /api/v1/projects/{id}/members   → list of users on this project
    PUT /api/v1/projects/{id}/members   → replace the full member set
    DELETE /api/v1/projects/{id}/members/{user_id} → remove one

C'est le miroir de /users/{id}/projects mais du point de vue projet :
quand l'admin ouvre la fiche projet, il voit directement qui y est
assigné et peut ajouter/retirer des gens sans devoir ouvrir chaque
fiche utilisateur.

La présence d'au moins un membre fait passer la bande projet de
l'agenda de rouge (personne assigné) à vert (équipe en place).
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, insert, select

from app.api.deps import DBSession, RequireManager
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User


router = APIRouter(prefix="/projects", tags=["project-members"])


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str


class MembersUpdate(BaseModel):
    user_ids: List[int]


async def _ensure_project(db, project_id: int) -> Project:
    p = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


@router.get(
    "/{project_id}/members",
    response_model=List[MemberRead],
)
async def list_members(
    project_id: int, db: DBSession, _: RequireManager
) -> List[MemberRead]:
    await _ensure_project(db, project_id)
    stmt = (
        select(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.email.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [MemberRead.model_validate(r) for r in rows]


@router.put(
    "/{project_id}/members",
    response_model=List[MemberRead],
)
async def set_members(
    project_id: int,
    body: MembersUpdate,
    db: DBSession,
    _: RequireManager,
) -> List[MemberRead]:
    await _ensure_project(db, project_id)

    # Validate user IDs
    if body.user_ids:
        existing = (
            await db.execute(
                select(User.id).where(User.id.in_(body.user_ids))
            )
        ).all()
        existing_ids = {int(r[0]) for r in existing}
        unknown = set(body.user_ids) - existing_ids
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Utilisateur(s) inconnu(s) : {sorted(unknown)}",
            )

    # Wipe and re-insert — simpler than computing diff for a handful.
    await db.execute(
        delete(ProjectMember).where(ProjectMember.project_id == project_id)
    )
    if body.user_ids:
        await db.execute(
            insert(ProjectMember),
            [
                {"project_id": project_id, "user_id": uid}
                for uid in set(body.user_ids)
            ],
        )
    await db.flush()

    return await list_members(project_id, db, _)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    project_id: int, user_id: int, db: DBSession, _: RequireManager
) -> None:
    await _ensure_project(db, project_id)
    await db.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    await db.flush()
