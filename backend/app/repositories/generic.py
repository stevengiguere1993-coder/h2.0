"""Generic CRUD helper used by lightweight business endpoints."""

from typing import Any, Generic, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)
CreateT = TypeVar("CreateT", bound=BaseModel)
UpdateT = TypeVar("UpdateT", bound=BaseModel)


class GenericCrud(Generic[ModelT, CreateT, UpdateT]):
    def __init__(self, db: AsyncSession, model: Type[ModelT]):
        self.db = db
        self.model = model

    async def create(self, data: CreateT) -> ModelT:
        payload: dict[str, Any] = data.model_dump(exclude_unset=True)
        obj = self.model(**payload)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get(self, obj_id: int) -> Optional[ModelT]:
        stmt = select(self.model).where(self.model.id == obj_id)  # type: ignore[attr-defined]
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list(self, skip: int = 0, limit: int = 100) -> Sequence[ModelT]:
        stmt = select(self.model).order_by(self.model.id.desc()).offset(skip).limit(limit)  # type: ignore[attr-defined]
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def update(self, obj: ModelT, data: UpdateT) -> ModelT:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.db.delete(obj)
        await self.db.flush()
