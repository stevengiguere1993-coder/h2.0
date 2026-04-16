"""
ContactRequest repository — database operations.
"""

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact_request import ContactRequest
from app.schemas.contact_request import ContactRequestCreate, ContactRequestUpdate


class ContactRequestRepository:
    """Repository for ContactRequest database operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        data: ContactRequestCreate,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> ContactRequest:
        record = ContactRequest(
            name=data.name.strip(),
            email=data.email.lower().strip(),
            phone=(data.phone or None),
            address=(data.address or None),
            project_type=data.project_type.value,
            budget_range=data.budget_range,
            message=data.message.strip(),
            locale=data.locale,
            source=data.source,
            ip_address=ip_address,
            user_agent=(user_agent[:500] if user_agent else None),
            gdpr_consent=data.gdpr_consent,
            marketing_consent=data.marketing_consent,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def get_by_id(self, request_id: int) -> Optional[ContactRequest]:
        query = select(ContactRequest).where(ContactRequest.id == request_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
    ) -> Sequence[ContactRequest]:
        query = select(ContactRequest).order_by(ContactRequest.created_at.desc())
        if status:
            query = query.where(ContactRequest.status == status)
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def update(
        self, record: ContactRequest, data: ContactRequestUpdate
    ) -> ContactRequest:
        update_data = data.model_dump(exclude_unset=True)
        if "status" in update_data and update_data["status"] is not None:
            update_data["status"] = update_data["status"].value
        for field, value in update_data.items():
            setattr(record, field, value)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def count_recent_from_ip(self, ip_address: str, minutes: int = 10) -> int:
        """Used for basic abuse rate-limiting."""
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import func

        threshold = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        query = select(func.count(ContactRequest.id)).where(
            ContactRequest.ip_address == ip_address,
            ContactRequest.created_at >= threshold,
        )
        result = await self.db.execute(query)
        return int(result.scalar() or 0)
