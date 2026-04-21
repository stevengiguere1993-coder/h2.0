"""Send a soumission to a client by email (PDF attached)."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, DBSession
from app.schemas.business import SoumissionRead
from app.services.soumission_pdf import render_soumission_pdf
from app.services.soumission_send import SoumissionSendError, send_soumission


router = APIRouter(prefix="/soumissions", tags=["soumissions"])


class SoumissionSendRequest(BaseModel):
    to: List[EmailStr] = Field(..., min_length=1)
    cc: Optional[List[EmailStr]] = None
    subject: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = Field(default=None, max_length=4000)


@router.post(
    "/{soumission_id}/send",
    response_model=SoumissionRead,
    summary="Send a soumission to a client (PDF attached)",
)
async def send_soumission_endpoint(
    soumission_id: int,
    data: SoumissionSendRequest,
    db: DBSession,
    _: CurrentUser,
) -> SoumissionRead:
    try:
        sm = await send_soumission(
            db,
            soumission_id,
            to=[str(a) for a in data.to],
            cc=[str(a) for a in (data.cc or [])],
            subject=data.subject,
            message=data.message,
        )
    except SoumissionSendError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return SoumissionRead.model_validate(sm)


@router.get(
    "/{soumission_id}/pdf",
    summary="Download the PDF preview of a soumission",
)
async def get_soumission_pdf(
    soumission_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    rendered = await render_soumission_pdf(db, soumission_id)
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Soumission not found")
    sm, pdf_bytes = rendered
    filename = f"soumission-{sm.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
