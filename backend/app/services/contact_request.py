"""
ContactRequest service — business logic for the public contact form
and the internal CRM triage.
"""

from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact_request import ContactRequest
from app.repositories.contact_request import ContactRequestRepository
from app.schemas.contact_request import ContactRequestCreate, ContactRequestUpdate


class ContactRequestService:
    """Business-logic layer for ContactRequest."""

    RATE_LIMIT_PER_IP_PER_10_MIN = 5

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ContactRequestRepository(db)

    async def submit_public(
        self,
        data: ContactRequestCreate,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> ContactRequest:
        """Create a contact request from the public form.

        Raises ValueError on rate-limit breach so the endpoint can return 429.
        """
        if ip_address:
            recent = await self.repo.count_recent_from_ip(ip_address, minutes=10)
            if recent >= self.RATE_LIMIT_PER_IP_PER_10_MIN:
                raise ValueError("rate_limited")
        return await self.repo.create(data, ip_address=ip_address, user_agent=user_agent)

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
    ) -> Sequence[ContactRequest]:
        return await self.repo.list(skip=skip, limit=limit, status=status)

    async def get(self, request_id: int) -> Optional[ContactRequest]:
        return await self.repo.get_by_id(request_id)

    async def update(
        self, request_id: int, data: ContactRequestUpdate
    ) -> Optional[ContactRequest]:
        record = await self.repo.get_by_id(request_id)
        if record is None:
            return None
        return await self.repo.update(record, data)

    @staticmethod
    def build_reference(record: ContactRequest) -> str:
        """Return a short human-readable reference string, e.g. 'HSI-2026-000123'."""
        return f"HSI-{record.created_at.year}-{record.id:06d}"
