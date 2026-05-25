"""Endpoints photos d'un projet Dev Logiciel.

    GET    /api/v1/devlog/projects/{project_id}/photos
    POST   /api/v1/devlog/projects/{project_id}/photos          multipart
    GET    /api/v1/devlog/projects/{project_id}/photos/{id}/image
    PATCH  /api/v1/devlog/projects/{project_id}/photos/{id}     caption
    DELETE /api/v1/devlog/projects/{project_id}/photos/{id}

Tous proteges par le guard admin/owner du pole (applique au router
parent dans api/v1/router.py) et loguent les mutations dans audit_logs.
Pattern aligne sur ``endpoints/project_photos.py`` (Construction).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_photo import DevlogProjectPhoto
from app.schemas.devlog import (
    DevlogProjectPhotoCaptionUpdate,
    DevlogProjectPhotoRead,
)
from app.services.audit import log_action


router = APIRouter(prefix="/devlog/projects", tags=["devlog-project-photos"])


_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/gif",
    "application/pdf",
}
_MAX_BYTES = 15 * 1024 * 1024  # 15 Mo


async def _get_project_or_404(db, project_id: int) -> DevlogProject:
    obj = (
        await db.execute(
            select(DevlogProject).where(DevlogProject.id == project_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable")
    return obj


@router.get(
    "/{project_id}/photos",
    response_model=List[DevlogProjectPhotoRead],
)
async def list_photos(
    project_id: int, db: DBSession, _: CurrentUser
) -> List[DevlogProjectPhotoRead]:
    await _get_project_or_404(db, project_id)
    rows = (
        await db.execute(
            select(DevlogProjectPhoto)
            .where(DevlogProjectPhoto.project_id == project_id)
            .order_by(DevlogProjectPhoto.created_at.desc())
        )
    ).scalars().all()
    return [DevlogProjectPhotoRead.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/photos",
    response_model=DevlogProjectPhotoRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_photo(
    project_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(default=None),
) -> DevlogProjectPhotoRead:
    await _get_project_or_404(db, project_id)
    ct = (file.content_type or "").lower()
    if ct not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Format non supporte (JPG, PNG, WEBP, HEIC, GIF, PDF).",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(blob) > _MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Fichier trop gros (> {_MAX_BYTES // (1024 * 1024)} Mo).",
        )
    photo = DevlogProjectPhoto(
        project_id=project_id,
        image=blob,
        content_type=ct,
        filename=(file.filename or None),
        size_bytes=len(blob),
        caption=(caption.strip() if caption else None),
        uploaded_by_user_id=user.id,
        uploaded_by_email=user.email,
    )
    db.add(photo)
    await db.flush()
    await db.refresh(photo)
    await log_action(
        db,
        user=user,
        action="devlog_project_photo.created",
        entity_type="devlog_project_photo",
        entity_id=photo.id,
        details={
            "project_id": project_id,
            "filename": photo.filename,
            "content_type": ct,
            "size_bytes": photo.size_bytes,
        },
    )
    return DevlogProjectPhotoRead.model_validate(photo)


@router.get("/{project_id}/photos/{photo_id}/image")
async def get_photo_image(
    project_id: int,
    photo_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    photo = (
        await db.execute(
            select(DevlogProjectPhoto).where(
                DevlogProjectPhoto.id == photo_id,
                DevlogProjectPhoto.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo introuvable")
    await db.refresh(photo, attribute_names=["image"])
    if not photo.image:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo introuvable.")
    ext = (
        "pdf"
        if photo.content_type == "application/pdf"
        else (photo.content_type.split("/")[-1] or "bin")
    )
    filename = photo.filename or f"photo-{photo.id}.{ext}"
    return Response(
        content=bytes(photo.image),
        media_type=photo.content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.patch(
    "/{project_id}/photos/{photo_id}",
    response_model=DevlogProjectPhotoRead,
)
async def update_photo_caption(
    project_id: int,
    photo_id: int,
    data: DevlogProjectPhotoCaptionUpdate,
    db: DBSession,
    user: CurrentUser,
) -> DevlogProjectPhotoRead:
    photo = (
        await db.execute(
            select(DevlogProjectPhoto).where(
                DevlogProjectPhoto.id == photo_id,
                DevlogProjectPhoto.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo introuvable")
    photo.caption = (data.caption.strip() if data.caption else None)
    await db.flush()
    await db.refresh(photo)
    await log_action(
        db,
        user=user,
        action="devlog_project_photo.updated",
        entity_type="devlog_project_photo",
        entity_id=photo.id,
        details={"project_id": project_id, "caption": photo.caption},
    )
    return DevlogProjectPhotoRead.model_validate(photo)


@router.delete(
    "/{project_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_photo(
    project_id: int,
    photo_id: int,
    db: DBSession,
    user: CurrentUser,
) -> Response:
    photo = (
        await db.execute(
            select(DevlogProjectPhoto).where(
                DevlogProjectPhoto.id == photo_id,
                DevlogProjectPhoto.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo introuvable")
    await db.delete(photo)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="devlog_project_photo.deleted",
        entity_type="devlog_project_photo",
        entity_id=photo_id,
        details={"project_id": project_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
