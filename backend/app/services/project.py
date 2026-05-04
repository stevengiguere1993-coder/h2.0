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
        """Create a new project.

        client_id is optional now; if provided, we verify it exists.
        Returns None only when client_id is given but doesn't match.
        """
        if data.client_id is not None:
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
        status_filter: Optional[str] = None,
    ) -> Sequence[Project]:
        """List projects with optional filtering."""
        return await self.repo.list(
            skip, limit, client_id, status_filter=status_filter
        )

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
        """Delete a project. Returns True if deleted, False if not found.

        Si le projet est rattaché à une soumission, on marque celle-ci
        avec `project_skip_backfill=True` pour empêcher le backfill au
        prochain démarrage de re-provisionner un projet (cf. main.py ·
        lifespan · backfill_accepted_soumissions). Sans ça, le projet
        ressuscite à chaque cold-start Render."""
        project = await self.repo.get_by_id(project_id)
        if project is None:
            return False
        soumission_id = project.soumission_id
        if soumission_id is not None:
            from sqlalchemy import update as _update

            from app.models.soumission import Soumission

            await self.db.execute(
                _update(Soumission)
                .where(Soumission.id == soumission_id)
                .values(project_skip_backfill=True)
            )
        await self.repo.delete(project)
        return True
