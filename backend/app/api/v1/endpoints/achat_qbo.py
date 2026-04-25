"""Push an Achat (PO) to QuickBooks Online as a Bill.

    POST /api/v1/achats/{id}/qbo/sync   — push manuel
    autopush_achat(achat_id)            — utilisé par les hooks auto

Le module expose `autopush_achat` pour être appelé silencieusement
par le hook update du CRUD générique quand on fait passer un achat
en statut "received" (cas usuel: facture fournisseur reçue).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.services.achat_qbo import AchatSyncError, sync_achat_to_qbo


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
