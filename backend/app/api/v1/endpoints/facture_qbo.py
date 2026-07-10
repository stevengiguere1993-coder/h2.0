"""Sync a Facture to QuickBooks Online as an Invoice."""

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.services.facture_qbo import FactureSyncError, sync_facture_to_qbo


router = APIRouter(prefix="/factures", tags=["facture-qbo"])


class QboSyncResult(BaseModel):
    qbo_invoice_id: str
    qbo_doc_number: str
    # Avertissement NON bloquant remonté à l'écran : ex. paiement(s) non
    # enregistré(s) dans QB (avec le motif QBO exact) alors que la facture,
    # elle, est bien synchronisée. Permet à l'utilisateur de voir POURQUOI
    # un paiement n'est pas passé, au lieu d'un échec silencieux.
    sync_warning: Optional[str] = None


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
        # Persiste le motif sur la facture (session fraîche — celle de la
        # requête est invalidée par l'exception) pour l'afficher sur la
        # fiche même après fermeture de la bannière.
        from app.services.facture_qbo import record_facture_sync_error

        await record_facture_sync_error(facture_id, str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return QboSyncResult(
        qbo_invoice_id=str(result.get("qbo_invoice_id") or ""),
        qbo_doc_number=str(result.get("qbo_doc_number") or ""),
        sync_warning=result.get("sync_warning"),
    )
