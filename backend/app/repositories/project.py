"""
Project Repository for database operations.
"""

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectRepository:
    """Repository for Project database operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: ProjectCreate) -> Project:
        """Create a new project with every optional field accepted."""
        payload = data.model_dump(exclude_unset=True)
        if not payload.get("status"):
            payload["status"] = "planned"
        project = Project(**payload)
        self.db.add(project)
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def get_by_id(
        self, project_id: int, with_client: bool = False
    ) -> Optional[Project]:
        """Get a project by ID."""
        query = select(Project).where(Project.id == project_id)
        if with_client:
            query = query.options(selectinload(Project.client))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        client_id: Optional[int] = None,
        status_filter: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> Sequence[Project]:
        """List projects with optional client / status / kind filters.

        Sans `kind`, on EXCLUT les bons de travail pour ne pas polluer la
        vue projets de construction. Avec `kind`, on filtre dessus.
        """
        from sqlalchemy import or_

        query = select(Project).order_by(Project.created_at.desc())
        if client_id is not None:
            query = query.where(Project.client_id == client_id)
        if status_filter is not None:
            query = query.where(Project.status == status_filter)
        if kind is not None:
            query = query.where(Project.kind == kind)
        else:
            query = query.where(
                or_(Project.kind.is_(None), Project.kind != "bon_travail")
            )
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def update(
        self, project: Project, data: ProjectUpdate
    ) -> Project:
        """Update a project."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(project, field, value)
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def delete(self, project: Project) -> None:
        """Delete a project."""
        await self.db.delete(project)
        await self.db.flush()
