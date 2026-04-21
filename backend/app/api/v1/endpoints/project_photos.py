"""Photos attached to a Project: upload, list, download, delete.

    GET    /api/v1/projects/{id}/photos
    POST   /api/v1/projects/{id}/photos         multipart file
    GET    /api/v1/projects/{id}/photos/{pid}/image   inline image/pdf
    DELETE /api/v1/projects/{id}/photos/{pid}
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.project import Project
from app.models.project_photo import ProjectPhoto


router = APIRouter(prefix="/projects", tags=["project-photos"])


_ALLOWED = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "image/heic", "image/heif", "application/pdf",
}
_MAX_BYTES = 15 * 1024 * 1024  # 15 MB


class PhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    content_type: str
    caption: Optional[str]
    uploaded_by_email: Optional[str]
    created_at: datetime


async def _ensure_project(db, project_id: int) -> Project:
    p = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


@router.get(
    "/{project_id}/photos",
    response_model=List[PhotoRead],
    summary="List photos attached to a project",
)
async def list_photos(
    project_id: int, db: DBSession, _: CurrentUser
) -> List[PhotoRead]:
    await _ensure_project(db, project_id)
    rows = (
        await db.execute(
            select(ProjectPhoto)
            .where(ProjectPhoto.project_id == project_id)
            .order_by(ProjectPhoto.created_at.desc())
        )
    ).scalars().all()
    return [PhotoRead.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/photos",
    response_model=PhotoRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a photo (or PDF) to a project",
)
async def upload_photo(
    project_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(default=None),
) -> PhotoRead:
    await _ensure_project(db, project_id)
    ct = (file.content_type or "").lower()
    if ct not in _ALLOWED:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Format non supporté (JPG, PNG, WEBP, HEIC, PDF).",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(blob) > _MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Fichier trop gros (> {_MAX_BYTES // (1024*1024)} Mo).",
        )

    photo = ProjectPhoto(
        project_id=project_id,
        image=blob,
        content_type=ct,
        caption=(caption.strip() if caption else None),
        uploaded_by_email=user.email,
    )
    db.add(photo)
    await db.flush()
    await db.refresh(photo)
    return PhotoRead.model_validate(photo)


@router.get(
    "/{project_id}/photos/{photo_id}/image",
    summary="Stream the photo bytes inline",
)
async def get_photo_image(
    project_id: int,
    photo_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    photo = (
        await db.execute(
            select(ProjectPhoto).where(
                ProjectPhoto.id == photo_id,
                ProjectPhoto.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    # Force-load the deferred column
    await db.refresh(photo, attribute_names=["image"])
    if not photo.image:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo introuvable.")
    ext = (
        "pdf"
        if photo.content_type == "application/pdf"
        else (photo.content_type.split("/")[-1] or "bin")
    )
    filename = f"photo-{photo.id}.{ext}"
    return Response(
        content=bytes(photo.image),
        media_type=photo.content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.delete(
    "/{project_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a photo",
)
async def delete_photo(
    project_id: int,
    photo_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    photo = (
        await db.execute(
            select(ProjectPhoto).where(
                ProjectPhoto.id == photo_id,
                ProjectPhoto.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    await db.delete(photo)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
