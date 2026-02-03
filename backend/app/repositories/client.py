"""
Client Repository for database operations.
"""

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client import Client
from app.schemas.client import ClientCreate, ClientUpdate


class ClientRepository:
    """Repository for Client database operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: ClientCreate) -> Client:
        """Create a new client."""
        client = Client(name=data.name)
        self.db.add(client)
        await self.db.flush()
        await self.db.refresh(client)
        return client

    async def get_by_id(
        self, client_id: int, with_projects: bool = False
    ) -> Optional[Client]:
        """Get a client by ID."""
        query = select(Client).where(Client.id == client_id)
        if with_projects:
            query = query.options(selectinload(Client.projects))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self, skip: int = 0, limit: int = 100
    ) -> Sequence[Client]:
        """List all clients with pagination."""
        query = (
            select(Client)
            .order_by(Client.name)
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def update(
        self, client: Client, data: ClientUpdate
    ) -> Client:
        """Update a client."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(client, field, value)
        await self.db.flush()
        await self.db.refresh(client)
        return client

    async def delete(self, client: Client) -> None:
        """Delete a client."""
        await self.db.delete(client)
        await self.db.flush()
