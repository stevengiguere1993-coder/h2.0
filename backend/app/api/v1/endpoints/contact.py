"""
Contact request endpoints.
"""

from typing import List, Optional

from datetime import datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.integrations.monday_bridge import push_contact_to_monday
from app.models.contact_request import ContactRequestStatus, ProjectType
from app.models.contact_request_photo import ContactRequestPhoto
from app.schemas.contact_request import (
    ContactRequestCreate,
    ContactRequestPublicAck,
    ContactRequestRead,
    ContactRequestUpdate,
)
from app.services.contact_request import ContactRequestService


router = APIRouter(prefix="/contact", tags=["contact"])

MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}


@router.post(
    "",
    response_model=ContactRequestPublicAck,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a contact request (public, multipart/form-data)",
)
async def submit_contact(
    request: Request,
    db: DBSession,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    email: str = Form(...),
    message: str = Form(...),
    gdpr_consent: bool = Form(...),
    phone: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    project_type: str = Form("autre"),
    budget_range: Optional[str] = Form(None),
    locale: str = Form("fr"),
    source: Optional[str] = Form(None),
    marketing_consent: bool = Form(False),
    photos: List[UploadFile] = File(default=[]),
) -> ContactRequestPublicAck:
    if not gdpr_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent is required to submit a contact request.",
        )

    try:
        data = ContactRequestCreate(
            name=name,
            email=email,
            phone=phone or None,
            address=address or None,
            project_type=ProjectType(project_type) if project_type else ProjectType.AUTRE,
            budget_range=budget_range or None,
            message=message,
            locale=locale if locale in ("fr", "en") else "fr",
            source=source or None,
            gdpr_consent=gdpr_consent,
            marketing_consent=marketing_consent,
        )
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

    ip_address = _client_ip(request)
    user_agent = request.headers.get("user-agent")

    service = ContactRequestService(db)
    try:
        record = await service.submit_public(
            data=data, ip_address=ip_address, user_agent=user_agent
        )
    except ValueError as exc:
        if str(exc) == "rate_limited":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many submissions. Please try again later.",
            )
        raise

    reference = ContactRequestService.build_reference(record)

    photo_payloads: list[tuple[str, bytes, str]] = []
    if photos:
        for up in photos[:MAX_PHOTOS]:
            ct = (up.content_type or "").lower()
            if ct not in ALLOWED_CONTENT_TYPES:
                continue
            content = await up.read(MAX_PHOTO_BYTES + 1)
            if not content or len(content) > MAX_PHOTO_BYTES:
                continue
            photo_payloads.append((up.filename or "photo.jpg", content, ct))

    # Persist the validated photos alongside the contact request so
    # the admin zone can display them in the prospect's Documents tab
    # (independent of the Monday.com push, which is best-effort).
    for filename, content, ct in photo_payloads:
        db.add(
            ContactRequestPhoto(
                contact_request_id=record.id,
                image=content,
                content_type=ct,
                filename=filename,
            )
        )
    if photo_payloads:
        await db.flush()

    background_tasks.add_task(
        push_contact_to_monday, record, reference, None, photo_payloads or None
    )

    return ContactRequestPublicAck(reference=reference)


@router.get(
    "",
    response_model=List[ContactRequestRead],
    summary="List contact requests (staff)",
)
async def list_contact_requests(
    db: DBSession,
    current_user: RequireManager,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=1000),
    status_filter: Optional[ContactRequestStatus] = Query(default=None, alias="status"),
) -> List[ContactRequestRead]:
    service = ContactRequestService(db)
    records = await service.list(
        skip=skip,
        limit=limit,
        status=status_filter.value if status_filter else None,
    )
    return [ContactRequestRead.model_validate(r) for r in records]


@router.get(
    "/{request_id}",
    response_model=ContactRequestRead,
    summary="Get a contact request by ID (staff)",
)
async def get_contact_request(
    request_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> ContactRequestRead:
    service = ContactRequestService(db)
    record = await service.get(request_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return ContactRequestRead.model_validate(record)


@router.patch(
    "/{request_id}",
    response_model=ContactRequestRead,
    summary="Update a contact request (staff)",
)
async def update_contact_request(
    request_id: int,
    data: ContactRequestUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> ContactRequestRead:
    service = ContactRequestService(db)
    record = await service.update(request_id, data)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return ContactRequestRead.model_validate(record)


@router.delete(
    "/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a contact request (staff)",
)
async def delete_contact_request(
    request_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> None:
    service = ContactRequestService(db)
    deleted = await service.delete(request_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


# ---------- Photos attached to a prospect contact request ----------


class ContactPhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_request_id: int
    content_type: str
    filename: Optional[str]
    created_at: datetime


@router.get(
    "/{request_id}/photos",
    response_model=List[ContactPhotoRead],
    summary="List photos attached to a contact request (staff)",
)
async def list_contact_photos(
    request_id: int, db: DBSession, _: CurrentUser
) -> List[ContactPhotoRead]:
    rows = (
        await db.execute(
            select(ContactRequestPhoto)
            .where(ContactRequestPhoto.contact_request_id == request_id)
            .order_by(ContactRequestPhoto.created_at.asc())
        )
    ).scalars().all()
    return [ContactPhotoRead.model_validate(r) for r in rows]


@router.get(
    "/{request_id}/photos/{photo_id}/image",
    summary="Stream the photo bytes inline (staff)",
)
async def stream_contact_photo(
    request_id: int, photo_id: int, db: DBSession, _: CurrentUser
) -> Response:
    p = (
        await db.execute(
            select(ContactRequestPhoto).where(
                ContactRequestPhoto.id == photo_id,
                ContactRequestPhoto.contact_request_id == request_id,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo introuvable."
        )
    await db.refresh(p, attribute_names=["image"])
    if not p.image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo vide."
        )
    return Response(
        content=bytes(p.image),
        media_type=p.content_type,
        headers={
            "Content-Disposition": (
                f'inline; filename="{p.filename or f"photo-{p.id}"}"'
            )
        },
    )


@router.delete(
    "/{request_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a photo from a contact request (staff)",
)
async def delete_contact_photo(
    request_id: int, photo_id: int, db: DBSession, _: CurrentUser
) -> None:
    p = (
        await db.execute(
            select(ContactRequestPhoto).where(
                ContactRequestPhoto.id == photo_id,
                ContactRequestPhoto.contact_request_id == request_id,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo introuvable."
        )
    await db.delete(p)
    await db.flush()
