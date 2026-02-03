"""
Client Service for business logic.
"""

from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.repositories.client import ClientRepository
from app.schemas.client import ClientCreate, ClientUpdate


class ClientService:
    """Service for Client business operations."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ClientRepository(db)

    async def create(self, data: ClientCreate) -> Client:
        """Create a new client."""
        return await self.repo.create(data)

    async def get_by_id(
        self, client_id: int, with_projects: bool = False
    ) -> Optional[Client]:
        """Get a client by ID."""
        return await self.repo.get_by_id(client_id, with_projects)

    async def list(
        self, skip: int = 0, limit: int = 100
    ) -> Sequence[Client]:
        """List all clients."""
        return await self.repo.list(skip, limit)

    async def update(
        self, client_id: int, data: ClientUpdate
    ) -> Optional[Client]:
        """Update a client."""
        client = await self.repo.get_by_id(client_id)
        if client is None:
            return None
        return await self.repo.update(client, data)

    async def delete(self, client_id: int) -> bool:
        """Delete a client. Returns True if deleted, False if not found."""
        client = await self.repo.get_by_id(client_id)
        if client is None:
            return False
        await self.repo.delete(client)
        return True
