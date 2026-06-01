"""
Project endpoints.

CRUD operations for projects with role-based access control.
"""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_project_ids
from app.schemas.project import (
    ProjectCreate,
    ProjectRead,
    ProjectReadWithClient,
    ProjectUpdate,
)
from app.services.project import ProjectService


router = APIRouter(prefix="/projects", tags=["projects"])


def _billing_kind(kind: Optional[str], pricing_kind: Optional[str]) -> str:
    """Type de facturation d'un projet d'après sa soumission liée :
    "contrat" (contrat APCHQ), sinon le pricing_kind ("forfaitaire" /
    "estime"). Détermine le défaut « refacturable » des achats."""
    if (kind or "") == "contract":
        return "contrat"
    return pricing_kind or "forfaitaire"


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project (admin only)",
)
async def create_project(
    data: ProjectCreate,
    db: DBSession,
    current_user: CurrentUser,
) -> ProjectRead:
    """Create a new project. Requires admin privileges."""
    service = ProjectService(db)
    project = await service.create(data)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client not found",
        )
    return ProjectRead.model_validate(project)


@router.get(
    "",
    response_model=List[ProjectRead],
    summary="List all projects",
)
async def list_projects(
    db: DBSession,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    client_id: Optional[int] = Query(default=None, gt=0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
) -> List[ProjectRead]:
    """List projects with optional client / status filter.

    For employees (role=employee), only projects they've been assigned
    to via project_members are returned. Manager+ roles see everything.
    """
    service = ProjectService(db)
    visible = await visible_project_ids(db, current_user)
    projects = await service.list(
        skip=skip,
        limit=limit,
        client_id=client_id,
        status_filter=status_filter,
    )
    if visible is not None:
        projects = [p for p in projects if p.id in visible]

    # Enrichit chaque projet avec le total de sa soumission liée
    # (1 seule requête batch) — sert de fallback dans le kanban quand
    # `budget` est null mais qu'une soumission acceptée a un total.
    sm_ids = [p.soumission_id for p in projects if p.soumission_id]
    sm_totals: dict[int, Decimal] = {}
    sm_billing: dict[int, str] = {}
    if sm_ids:
        from sqlalchemy import select
        from app.models.soumission import Soumission

        rows = (
            await db.execute(
                select(
                    Soumission.id,
                    Soumission.total,
                    Soumission.kind,
                    Soumission.pricing_kind,
                ).where(Soumission.id.in_(set(sm_ids)))
            )
        ).all()
        for sid, total, kind, pricing_kind in rows:
            if total is not None:
                sm_totals[sid] = total
            sm_billing[sid] = _billing_kind(kind, pricing_kind)

    out: List[ProjectRead] = []
    for p in projects:
        d = ProjectRead.model_validate(p)
        if p.soumission_id and p.soumission_id in sm_totals:
            d.soumission_total = sm_totals[p.soumission_id]
        if p.soumission_id and p.soumission_id in sm_billing:
            d.billing_kind = sm_billing[p.soumission_id]
        out.append(d)
    return out


@router.get(
    "/{project_id}",
    response_model=ProjectReadWithClient,
    summary="Get a project by ID",
)
async def get_project(
    project_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> ProjectReadWithClient:
    """Get a project with its client. Employees must be members of
    the project; manager+ can access any project."""
    visible = await visible_project_ids(db, current_user)
    if visible is not None and project_id not in visible:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    service = ProjectService(db)
    project = await service.get_by_id(project_id, with_client=True)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    out = ProjectReadWithClient.model_validate(project)
    if project.soumission_id:
        from sqlalchemy import select
        from app.models.soumission import Soumission

        sm = (
            await db.execute(
                select(Soumission.kind, Soumission.pricing_kind).where(
                    Soumission.id == project.soumission_id
                )
            )
        ).first()
        if sm is not None:
            out.billing_kind = _billing_kind(sm[0], sm[1])
    return out


@router.put(
    "/{project_id}",
    response_model=ProjectRead,
    summary="Update a project (admin only)",
)
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> ProjectRead:
    """Update a project. Requires admin privileges."""
    service = ProjectService(db)
    project = await service.update(project_id, data)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or invalid client_id",
        )
    return ProjectRead.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project (admin only)",
)
async def delete_project(
    project_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> None:
    """Delete a project. Requires admin privileges."""
    service = ProjectService(db)
    deleted = await service.delete(project_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
