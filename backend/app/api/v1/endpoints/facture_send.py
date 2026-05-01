"""Send a facture to a client by email (PDF attached).
Also exposes GET /pdf for direct preview."""

import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, DBSession
from app.schemas.business import FactureRead
from app.services.facture_pdf import render_facture_pdf
from app.services.facture_send import FactureSendError, send_facture


log = logging.getLogger(__name__)
router = APIRouter(prefix="/factures", tags=["factures"])


async def _autopush_to_qbo(facture_id: int) -> None:
    """Auto-push de la facture vers QBO Invoice en arrière-plan,
    juste après l'envoi au client. Silencieux : si QBO n'est pas
    connecté ou si la sync échoue, on log mais on ne bloque pas
    l'envoi du courriel."""
    from app.db.session import AsyncSessionLocal
    from app.services.facture_qbo import sync_facture_to_qbo

    try:
        async with AsyncSessionLocal() as db:
            await sync_facture_to_qbo(db, facture_id)
            await db.commit()
        log.info("Auto-push QBO facture %s ok", facture_id)
    except Exception as exc:
        log.warning(
            "Auto-push QBO facture %s a échoué (silencieux): %s",
            facture_id,
            exc,
        )


class FactureSendRequest(BaseModel):
    to: List[EmailStr] = Field(..., min_length=1)
    cc: Optional[List[EmailStr]] = None
    subject: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = Field(default=None, max_length=4000)
    include_statement: bool = Field(
        default=False,
        description=(
            "Si True, joint en plus de la facture une page « État de "
            "compte » récapitulant toutes les factures et paiements "
            "du projet."
        ),
    )


@router.post(
    "/{facture_id}/send",
    response_model=FactureRead,
    summary="Send a facture to a client (PDF attached)",
)
async def send_facture_endpoint(
    facture_id: int,
    data: FactureSendRequest,
    db: DBSession,
    background: BackgroundTasks,
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
            include_statement=data.include_statement,
        )
    except FactureSendError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Auto-push vers QBO Invoice après l'envoi (background pour ne
    # pas ralentir la réponse).
    background.add_task(_autopush_to_qbo, fa.id)

    return FactureRead.model_validate(fa)


@router.get(
    "/{facture_id}/pdf",
    summary="Download the PDF preview of a facture",
)
async def get_facture_pdf(
    facture_id: int,
    db: DBSession,
    _: CurrentUser,
    include_statement: bool = False,
) -> Response:
    """Avec ``?include_statement=true``, l'état de compte du projet
    (toutes les factures + paiements) est appendé après la facture
    dans un PDF unique."""
    rendered = await render_facture_pdf(
        db, facture_id, include_statement=include_statement,
    )
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture not found")
    fa, pdf_bytes = rendered
    filename = (
        f"facture-{fa.reference}-avec-etat.pdf"
        if include_statement
        else f"facture-{fa.reference}.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
