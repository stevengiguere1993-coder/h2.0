"""Send a facture to a client by email (PDF attached).
Also exposes GET /pdf for direct preview."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, DBSession
from app.schemas.business import FactureRead
from app.services.facture_pdf import render_facture_pdf
from app.services.facture_send import FactureSendError, send_facture


router = APIRouter(prefix="/factures", tags=["factures"])


class FactureSendRequest(BaseModel):
    to: List[EmailStr] = Field(..., min_length=1)
    cc: Optional[List[EmailStr]] = None
    subject: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = Field(default=None, max_length=4000)


@router.post(
    "/{facture_id}/send",
    response_model=FactureRead,
    summary="Send a facture to a client (PDF attached)",
)
async def send_facture_endpoint(
    facture_id: int,
    data: FactureSendRequest,
    db: DBSession,
    _: CurrentUser,
) -> FactureRead:
    try:
        fa = await send_facture(
            db,
            facture_id,
            to=[str(a) for a in data.to],
            cc=[str(a) for a in (data.cc or [])],
            subject=data.subject,
            message=data.message,
        )
    except FactureSendError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return FactureRead.model_validate(fa)


@router.get(
    "/{facture_id}/pdf",
    summary="Download the PDF preview of a facture",
)
async def get_facture_pdf(
    facture_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    rendered = await render_facture_pdf(db, facture_id)
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture not found")
    fa, pdf_bytes = rendered
    filename = f"facture-{fa.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
