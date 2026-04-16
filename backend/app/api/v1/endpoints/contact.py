"""
Contact request endpoints.

Public POST (no auth) for the landing-form submission.
Authenticated GET/PATCH for internal CRM triage.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.deps import CurrentUser, DBSession
from app.models.contact_request import ContactRequestStatus
from app.schemas.contact_request import (
    ContactRequestCreate,
    ContactRequestPublicAck,
    ContactRequestRead,
    ContactRequestUpdate,
)
from app.services.contact_request import ContactRequestService


router = APIRouter(prefix="/contact", tags=["contact"])


@router.post(
    "",
    response_model=ContactRequestPublicAck,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a contact request (public)",
)
async def submit_contact(
    data: ContactRequestCreate,
    request: Request,
    db: DBSession,
) -> ContactRequestPublicAck:
    """Public endpoint used by the landing page form.

    Enforces explicit consent, basic per-IP rate-limit, and stores the
    request in the internal CRM. The response is intentionally minimal.
    """
    if not data.gdpr_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent is required to submit a contact request.",
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

    return ContactRequestPublicAck(reference=ContactRequestService.build_reference(record))


@router.get(
    "",
    response_model=List[ContactRequestRead],
    summary="List contact requests (staff)",
)
async def list_contact_requests(
    db: DBSession,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
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


def _client_ip(request: Request) -> Optional[str]:
    """Extract the best-effort client IP, respecting a single proxy hop."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None
