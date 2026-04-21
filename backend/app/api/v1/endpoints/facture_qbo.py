"""Sync a Facture to QuickBooks Online as an Invoice."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.services.facture_qbo import FactureSyncError, sync_facture_to_qbo


router = APIRouter(prefix="/factures", tags=["facture-qbo"])


class QboSyncResult(BaseModel):
    qbo_invoice_id: str
    qbo_doc_number: str


@router.post(
    "/{facture_id}/qbo/sync",
    response_model=QboSyncResult,
    summary="Push / update the QBO Invoice for this facture",
)
async def sync_facture(
    facture_id: int,
    db: DBSession,
    _: CurrentUser,
) -> QboSyncResult:
    try:
        result = await sync_facture_to_qbo(db, facture_id)
    except FactureSyncError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return QboSyncResult(**result)
