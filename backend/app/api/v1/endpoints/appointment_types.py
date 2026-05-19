"""Types de rendez-vous — durée par défaut, buffer prép, rôles
autorisés.

Endpoints :
  GET   /api/v1/appointment-types               — liste (tous users)
  GET   /api/v1/appointment-types/{id}          — détail
  POST  /api/v1/appointment-types               — créer (admin)
  PATCH /api/v1/appointment-types/{id}          — éditer (admin)
  DELETE /api/v1/appointment-types/{id}         — désactiver (admin)
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, CurrentUser, DBSession
from app.models.appointment_type import AppointmentType


router = APIRouter(prefix="/appointment-types", tags=["appointment-types"])


class AppointmentTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    label: str
    description: Optional[str]
    default_duration_min: int
    prep_buffer_min: int
    allowed_roles_csv: Optional[str]
    color: str
    requires_travel: bool
    active: bool


class AppointmentTypeCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=64)
    label: str = Field(..., min_length=2, max_length=120)
    description: Optional[str] = None
    default_duration_min: int = Field(default=60, ge=5, le=480)
    prep_buffer_min: int = Field(default=0, ge=0, le=240)
    allowed_roles_csv: Optional[str] = Field(default=None, max_length=255)
    color: str = Field(default="0ea5e9", max_length=8)
    requires_travel: bool = False
    active: bool = True


class AppointmentTypeUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = None
    default_duration_min: Optional[int] = Field(default=None, ge=5, le=480)
    prep_buffer_min: Optional[int] = Field(default=None, ge=0, le=240)
    allowed_roles_csv: Optional[str] = Field(default=None, max_length=255)
    color: Optional[str] = Field(default=None, max_length=8)
    requires_travel: Optional[bool] = None
    active: Optional[bool] = None


@router.get(
    "",
    response_model=List[AppointmentTypeRead],
    summary="Liste les types de RV (filtré active par défaut)",
)
async def list_types(
    _: CurrentUser,
    db: DBSession,
    include_inactive: bool = False,
) -> List[AppointmentTypeRead]:
    stmt = select(AppointmentType).order_by(AppointmentType.label)
    if not include_inactive:
        stmt = stmt.where(AppointmentType.active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [AppointmentTypeRead.model_validate(r) for r in rows]


@router.get(
    "/{type_id}",
    response_model=AppointmentTypeRead,
    summary="Détail d'un type",
)
async def get_type(
    type_id: int, _: CurrentUser, db: DBSession
) -> AppointmentTypeRead:
    row = (
        await db.execute(
            select(AppointmentType).where(AppointmentType.id == type_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="appointment_type_not_found")
    return AppointmentTypeRead.model_validate(row)


@router.post(
    "",
    response_model=AppointmentTypeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un nouveau type (admin)",
)
async def create_type(
    payload: AppointmentTypeCreate, _: CurrentAdmin, db: DBSession
) -> AppointmentTypeRead:
    existing = (
        await db.execute(
            select(AppointmentType).where(AppointmentType.slug == payload.slug)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409, detail=f"slug déjà utilisé : {payload.slug}"
        )
    t = AppointmentType(**payload.model_dump())
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return AppointmentTypeRead.model_validate(t)


@router.patch(
    "/{type_id}",
    response_model=AppointmentTypeRead,
    summary="Édite un type (admin)",
)
async def update_type(
    type_id: int,
    payload: AppointmentTypeUpdate,
    _: CurrentAdmin,
    db: DBSession,
) -> AppointmentTypeRead:
    t = (
        await db.execute(
            select(AppointmentType).where(AppointmentType.id == type_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="appointment_type_not_found")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(t, k, v)
    await db.flush()
    return AppointmentTypeRead.model_validate(t)


@router.delete(
    "/{type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Désactive un type (admin) — soft delete via active=False",
)
async def deactivate_type(
    type_id: int, _: CurrentAdmin, db: DBSession
) -> None:
    t = (
        await db.execute(
            select(AppointmentType).where(AppointmentType.id == type_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="appointment_type_not_found")
    t.active = False
    await db.flush()
