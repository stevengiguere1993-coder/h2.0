"""Send a soumission to a client by email (PDF attached)."""

import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, DBSession
from app.services.permissions_service import user_has_capability
from app.schemas.business import SoumissionRead
from app.services.soumission_pdf import render_soumission_pdf
from app.services.soumission_send import SoumissionSendError, send_soumission


log = logging.getLogger(__name__)
router = APIRouter(prefix="/soumissions", tags=["soumissions"])


async def _autopush_to_qbo(soumission_id: int) -> None:
    """Auto-push de la soumission vers QBO en arrière-plan, juste
    après l'envoi au client. Silencieux côté staff : si QBO n'est pas
    connecté, ou si la sync échoue, on log mais on ne bloque pas
    l'envoi du courriel (qui a déjà réussi)."""
    from app.db.session import AsyncSessionLocal
    from app.services.soumission_qbo import sync_soumission_to_qbo

    try:
        async with AsyncSessionLocal() as db:
            await sync_soumission_to_qbo(db, soumission_id)
            await db.commit()
        log.info("Auto-push QBO soumission %s ok", soumission_id)
    except Exception as exc:
        log.warning(
            "Auto-push QBO soumission %s a échoué (silencieux): %s",
            soumission_id,
            exc,
        )


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
    background: BackgroundTasks,
    user: CurrentUser,
) -> SoumissionRead:
    if not await user_has_capability(db, user, "soumission.send"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour cette action.",
        )
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

    # Démarre la cadence de suivi : « Confirmer réception » dans 24 h.
    try:
        from app.services.follow_up import schedule_first_followup

        await schedule_first_followup(
            db,
            subject_type="soumission",
            subject_id=sm.id,
            performed_by_user_id=_.id,
        )
    except Exception:
        pass

    # Auto-push vers QBO Estimate après l'envoi (background pour ne
    # pas ralentir la réponse).
    background.add_task(_autopush_to_qbo, sm.id)

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
    prefix = "contrat" if getattr(sm, "kind", "quote") == "contract" else "soumission"
    filename = f"{prefix}-{sm.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
