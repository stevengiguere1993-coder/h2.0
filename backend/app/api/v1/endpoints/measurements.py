"""Measurement snapshots — saved polygon measurements for a client
or prospect, captured during site visits and reusable across many
soumissions.

    GET    /api/v1/measurements?client_id=...&contact_request_id=...
    POST   /api/v1/measurements
    PATCH  /api/v1/measurements/{id}
    DELETE /api/v1/measurements/{id}
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.measurement import MeasurementSnapshot


router = APIRouter(prefix="/measurements", tags=["measurements"])


class MeasurementCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    kind: str = Field(
        default="horizontal",
        pattern="^(horizontal|vertical|checklist|photo)$",
    )
    area_ft2: float = Field(..., ge=0)
    perimeter_ft: Optional[float] = Field(default=None, ge=0)
    wall_height_ft: Optional[float] = Field(default=None, ge=0)
    coords_json: Optional[str] = None
    address: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = None
    client_id: Optional[int] = None
    contact_request_id: Optional[int] = None
    template_type: Optional[str] = Field(default=None, max_length=32)
    template_data_json: Optional[str] = None


class MeasurementUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=255)
    notes: Optional[str] = None
    wall_height_ft: Optional[float] = Field(default=None, ge=0)
    area_ft2: Optional[float] = Field(default=None, ge=0)
    template_data_json: Optional[str] = None


class MeasurementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: Optional[int]
    contact_request_id: Optional[int]
    label: str
    notes: Optional[str]
    kind: str
    area_ft2: float
    perimeter_ft: Optional[float]
    wall_height_ft: Optional[float]
    coords_json: Optional[str]
    address: Optional[str]
    captured_by_user_id: Optional[int]
    captured_at: datetime
    created_at: datetime
    template_type: Optional[str] = None
    template_data_json: Optional[str] = None


@router.get("", response_model=List[MeasurementRead])
async def list_measurements(
    db: DBSession,
    _: CurrentUser,
    client_id: Optional[int] = Query(default=None),
    contact_request_id: Optional[int] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> List[MeasurementRead]:
    stmt = select(MeasurementSnapshot)
    if client_id is not None:
        stmt = stmt.where(MeasurementSnapshot.client_id == client_id)
    if contact_request_id is not None:
        stmt = stmt.where(
            MeasurementSnapshot.contact_request_id == contact_request_id
        )
    stmt = stmt.order_by(MeasurementSnapshot.captured_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [MeasurementRead.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=MeasurementRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_measurement(
    data: MeasurementCreate,
    db: DBSession,
    user: CurrentUser,
) -> MeasurementRead:
    if data.client_id is None and data.contact_request_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Une mesure doit être liée à un client ou à un prospect.",
        )
    m = MeasurementSnapshot(
        client_id=data.client_id,
        contact_request_id=data.contact_request_id,
        label=data.label.strip(),
        notes=(data.notes.strip() if data.notes else None),
        kind=data.kind,
        area_ft2=data.area_ft2,
        perimeter_ft=data.perimeter_ft,
        wall_height_ft=data.wall_height_ft,
        coords_json=data.coords_json,
        address=(data.address.strip() if data.address else None),
        template_type=data.template_type,
        template_data_json=data.template_data_json,
        captured_by_user_id=user.id,
    )
    db.add(m)
    await db.flush()
    await db.refresh(m)
    return MeasurementRead.model_validate(m)


@router.patch("/{mid}", response_model=MeasurementRead)
async def update_measurement(
    mid: int,
    data: MeasurementUpdate,
    db: DBSession,
    _: CurrentUser,
) -> MeasurementRead:
    m = (
        await db.execute(
            select(MeasurementSnapshot).where(MeasurementSnapshot.id == mid)
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mesure introuvable.")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    await db.flush()
    await db.refresh(m)
    return MeasurementRead.model_validate(m)


@router.delete("/{mid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_measurement(
    mid: int, db: DBSession, _: CurrentUser
) -> None:
    m = (
        await db.execute(
            select(MeasurementSnapshot).where(MeasurementSnapshot.id == mid)
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mesure introuvable.")
    await db.delete(m)
    await db.flush()


# ---------- Photos attached to a measurement ----------

from fastapi import File, Form, UploadFile
from fastapi.responses import Response

from app.models.measurement_photo import MeasurementPhoto


_ALLOWED_PHOTO = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "image/heic", "image/heif",
}
_MAX_PHOTO_BYTES = 15 * 1024 * 1024


class MeasurementPhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    measurement_id: int
    content_type: str
    caption: Optional[str]
    annotations_json: Optional[str]
    uploaded_by_user_id: Optional[int]
    created_at: datetime


async def _ensure_measurement(db, mid: int) -> MeasurementSnapshot:
    m = (
        await db.execute(
            select(MeasurementSnapshot).where(MeasurementSnapshot.id == mid)
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mesure introuvable.")
    return m


@router.get(
    "/{mid}/photos",
    response_model=List[MeasurementPhotoRead],
)
async def list_photos(
    mid: int, db: DBSession, _: CurrentUser
) -> List[MeasurementPhotoRead]:
    await _ensure_measurement(db, mid)
    rows = (
        await db.execute(
            select(MeasurementPhoto)
            .where(MeasurementPhoto.measurement_id == mid)
            .order_by(MeasurementPhoto.created_at.desc())
        )
    ).scalars().all()
    return [MeasurementPhotoRead.model_validate(r) for r in rows]


@router.post(
    "/{mid}/photos",
    response_model=MeasurementPhotoRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_photo(
    mid: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(default=None),
    annotations_json: Optional[str] = Form(default=None),
) -> MeasurementPhotoRead:
    await _ensure_measurement(db, mid)
    ct = (file.content_type or "").lower()
    if ct not in _ALLOWED_PHOTO:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Format image non supporté (JPG, PNG, WEBP, HEIC).",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(blob) > _MAX_PHOTO_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Fichier trop gros (>{_MAX_PHOTO_BYTES // (1024 * 1024)} Mo).",
        )
    p = MeasurementPhoto(
        measurement_id=mid,
        image=blob,
        content_type=ct,
        caption=(caption.strip() if caption else None),
        annotations_json=annotations_json,
        uploaded_by_user_id=user.id,
    )
    db.add(p)
    await db.flush()
    await db.refresh(p)
    return MeasurementPhotoRead.model_validate(p)


@router.get("/{mid}/photos/{pid}/image")
async def stream_photo(
    mid: int, pid: int, db: DBSession, _: CurrentUser
) -> Response:
    p = (
        await db.execute(
            select(MeasurementPhoto).where(
                MeasurementPhoto.id == pid,
                MeasurementPhoto.measurement_id == mid,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo introuvable.")
    await db.refresh(p, attribute_names=["image"])
    if not p.image:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo vide.")
    return Response(
        content=bytes(p.image),
        media_type=p.content_type,
        headers={
            "Content-Disposition": f'inline; filename="photo-{p.id}.jpg"'
        },
    )


class PhotoPatch(BaseModel):
    caption: Optional[str] = None
    annotations_json: Optional[str] = None


@router.patch(
    "/{mid}/photos/{pid}",
    response_model=MeasurementPhotoRead,
)
async def patch_photo(
    mid: int,
    pid: int,
    body: PhotoPatch,
    db: DBSession,
    _: CurrentUser,
) -> MeasurementPhotoRead:
    p = (
        await db.execute(
            select(MeasurementPhoto).where(
                MeasurementPhoto.id == pid,
                MeasurementPhoto.measurement_id == mid,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo introuvable.")
    if body.caption is not None:
        p.caption = body.caption.strip() or None
    if body.annotations_json is not None:
        p.annotations_json = body.annotations_json
    await db.flush()
    await db.refresh(p)
    return MeasurementPhotoRead.model_validate(p)


@router.delete(
    "/{mid}/photos/{pid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_photo(
    mid: int, pid: int, db: DBSession, _: CurrentUser
) -> None:
    p = (
        await db.execute(
            select(MeasurementPhoto).where(
                MeasurementPhoto.id == pid,
                MeasurementPhoto.measurement_id == mid,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo introuvable.")
    await db.delete(p)
    await db.flush()


# ---------- PDF export of a measurement (checklist + photos) ----------

@router.get("/{mid}/pdf")
async def measurement_pdf(
    mid: int, db: DBSession, _: CurrentUser
) -> Response:
    from app.services.measurement_pdf import render_measurement_pdf

    m = await _ensure_measurement(db, mid)
    pdf_bytes = await render_measurement_pdf(db, m)
    filename = f"releve-{m.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
