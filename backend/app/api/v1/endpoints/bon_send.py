"""Send a bon de travail to a client + PDF preview."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, DBSession
from app.schemas.business import BonTravailRead
from app.services.bon_pdf import render_bon_pdf
from app.services.bon_send import BonSendError, send_bon


router = APIRouter(prefix="/bons-travail", tags=["bon-send"])


class BonSendRequest(BaseModel):
    to: List[EmailStr] = Field(..., min_length=1)
    cc: Optional[List[EmailStr]] = None
    subject: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = Field(default=None, max_length=4000)


@router.post(
    "/{bon_id}/send",
    response_model=BonTravailRead,
    summary="Send a bon to a client (PDF + signature link)",
)
async def send_bon_endpoint(
    bon_id: int,
    data: BonSendRequest,
    db: DBSession,
    _: CurrentUser,
) -> BonTravailRead:
    try:
        bon = await send_bon(
            db,
            bon_id,
            to=[str(a) for a in data.to],
            cc=[str(a) for a in (data.cc or [])],
            subject=data.subject,
            message=data.message,
        )
    except BonSendError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return BonTravailRead.model_validate(bon)


@router.get("/{bon_id}/pdf", summary="Inline PDF preview")
async def get_bon_pdf(
    bon_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    rendered = await render_bon_pdf(db, bon_id)
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bon not found")
    bon, pdf_bytes = rendered
    filename = f"bon-{bon.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{bon_id}/ensure-project")
async def ensure_bon_project(
    bon_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """Garantit qu'un bon de travail a un PROJET lié (kind=bon_travail)
    pour porter ses achats / heures / facture. Idempotent : renvoie le
    projet existant si déjà lié, sinon en crée un (titre/client/assigné
    repris du bon)."""
    from app.models.bon_travail import BonTravail
    from app.models.project import Project, ProjectStatus

    bon = await db.get(BonTravail, bon_id)
    if bon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bon introuvable.")
    if bon.project_id:
        return {"project_id": bon.project_id}
    proj = Project(
        name=bon.title or f"Bon {bon.reference}",
        client_id=bon.client_id,
        kind="bon_travail",
        responsible_user_id=getattr(bon, "assignee_user_id", None),
        status=ProjectStatus.IN_PROGRESS.value,
    )
    db.add(proj)
    await db.flush()
    bon.project_id = proj.id
    await db.flush()
    return {"project_id": proj.id}
