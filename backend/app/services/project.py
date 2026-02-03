"""
Project Service for business logic.
"""

from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.repositories.client import ClientRepository
from app.repositories.project import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectService:
    """Service for Project business operations."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ProjectRepository(db)
        self.client_repo = ClientRepository(db)

    async def create(self, data: ProjectCreate) -> Optional[Project]:
        """
        Create a new project.

        Returns None if client_id doesn't exist.
        """
        # Validate client exists
        client = await self.client_repo.get_by_id(data.client_id)
        if client is None:
            return None
        return await self.repo.create(data)

    async def get_by_id(
        self, project_id: int, with_client: bool = False
    ) -> Optional[Project]:
        """Get a project by ID."""
        return await self.repo.get_by_id(project_id, with_client)

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        client_id: Optional[int] = None,
    ) -> Sequence[Project]:
        """List projects with optional filtering."""
        return await self.repo.list(skip, limit, client_id)

    async def update(
        self, project_id: int, data: ProjectUpdate
    ) -> Optional[Project]:
        """
        Update a project.

        Returns None if project not found or new client_id doesn't exist.
        """
        project = await self.repo.get_by_id(project_id)
        if project is None:
            return None

        # Validate new client_id if provided
        if data.client_id is not None:
            client = await self.client_repo.get_by_id(data.client_id)
            if client is None:
                return None

        return await self.repo.update(project, data)

    async def delete(self, project_id: int) -> bool:
        """Delete a project. Returns True if deleted, False if not found."""
        project = await self.repo.get_by_id(project_id)
        if project is None:
            return False
        await self.repo.delete(project)
        return True
