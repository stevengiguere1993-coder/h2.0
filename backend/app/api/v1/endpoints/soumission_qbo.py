"""
Soumission-specific endpoints beyond the generic CRUD:
  POST /api/v1/soumissions/{id}/qbo/sync

Pushes the soumission to QuickBooks Online as an Estimate and persists
the resulting QBO ids on the row.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.services.permissions_service import user_has_capability
from app.services.soumission_qbo import (
    SoumissionSyncError,
    sync_soumission_to_qbo,
)

router = APIRouter(prefix="/soumissions", tags=["soumission-qbo"])


class QboSyncResult(BaseModel):
    ok: bool
    qbo_estimate_id: str
    qbo_doc_number: str
    qbo_customer_id: str


@router.post(
    "/{soumission_id}/qbo/sync",
    response_model=QboSyncResult,
    summary="Push this soumission to QuickBooks Online as an Estimate",
)
async def qbo_sync(
    soumission_id: int, db: DBSession, user: CurrentUser
) -> QboSyncResult:
    if not await user_has_capability(db, user, "qbo.push"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour cette action.",
        )
    try:
        result = await sync_soumission_to_qbo(db, soumission_id)
    except SoumissionSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"QBO sync failed: {exc}",
        )
    return QboSyncResult(**result)
