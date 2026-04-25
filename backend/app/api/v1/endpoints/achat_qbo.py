"""Push an Achat (PO) to QuickBooks Online as a Bill or Purchase.

    POST /api/v1/achats/{id}/qbo/sync   — push manuel
    POST /api/v1/achats/{id}/send-po    — envoie le PO par courriel
    autopush_achat(achat_id)            — utilisé par les hooks auto

Le routage Bill vs Purchase est déterminé par achat.payment_method
(voir services/achat_qbo.py).
"""

from __future__ import annotations

import logging

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBSession
from app.schemas.business import AchatRead
from app.services.achat_qbo import AchatSyncError, sync_achat_to_qbo
from app.services.achat_send import AchatSendError, send_achat_po


log = logging.getLogger(__name__)
router = APIRouter(prefix="/achats", tags=["achats-qbo"])


class AchatQboSyncResult(BaseModel):
    ok: bool
    qbo_bill_id: str
    qbo_doc_number: str
    qbo_vendor_id: str


@router.post(
    "/{achat_id}/qbo/sync",
    response_model=AchatQboSyncResult,
    summary="Push this PO/achat to QuickBooks Online as a Bill",
)
async def push_achat_to_qbo(
    achat_id: int, db: DBSession, _: CurrentUser
) -> AchatQboSyncResult:
    try:
        result = await sync_achat_to_qbo(db, achat_id)
    except AchatSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"QBO sync failed: {exc}",
        )
    return AchatQboSyncResult(**result)


class SendPoRequest(BaseModel):
    extra_message: Optional[str] = Field(default=None, max_length=2000)


@router.post(
    "/{achat_id}/send-po",
    response_model=AchatRead,
    summary="Envoyer le PO par courriel à l'employé assigné",
)
async def send_po_endpoint(
    achat_id: int,
    data: SendPoRequest,
    db: DBSession,
    _: CurrentUser,
) -> AchatRead:
    try:
        achat = await send_achat_po(
            db, achat_id, extra_message=data.extra_message
        )
    except AchatSendError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return AchatRead.model_validate(achat)


async def autopush_achat(achat_id: int) -> None:
    """Auto-push silencieux — appelé par le hook qui détecte la
    transition status → received. Ouvre sa propre session DB. Si QBO
    n'est pas connecté ou que la sync rate, on log mais on n'échoue
    pas la requête utilisateur (qui a juste sauvegardé un statut).
    """
    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await sync_achat_to_qbo(db, achat_id)
            await db.commit()
        log.info("Auto-push QBO achat %s ok", achat_id)
    except Exception as exc:
        log.warning(
            "Auto-push QBO achat %s a échoué (silencieux): %s",
            achat_id,
            exc,
        )
