"""
Project endpoints.

CRUD operations for projects with role-based access control.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DBSession
from app.schemas.project import (
    ProjectCreate,
    ProjectRead,
    ProjectReadWithClient,
    ProjectUpdate,
)
from app.services.project import ProjectService


router = APIRouter(prefix="/projects", tags=["projects"])


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
    """List projects with optional client / status filter."""
    service = ProjectService(db)
    projects = await service.list(
        skip=skip,
        limit=limit,
        client_id=client_id,
        status_filter=status_filter,
    )
    return [ProjectRead.model_validate(p) for p in projects]


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
    """Get a project with its client. Requires authentication."""
    service = ProjectService(db)
    project = await service.get_by_id(project_id, with_client=True)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return ProjectReadWithClient.model_validate(project)


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
