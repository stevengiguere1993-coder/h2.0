"""Sync a Facture to QuickBooks Online as an Invoice."""

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.services.permissions_service import user_has_capability
from app.services.facture_qbo import (
    FactureSyncError,
    detacher_facture_qbo,
    sync_facture_to_qbo,
)


router = APIRouter(prefix="/factures", tags=["facture-qbo"])


class QboSyncResult(BaseModel):
    qbo_invoice_id: str
    qbo_doc_number: str
    # Avertissement NON bloquant remonté à l'écran : ex. paiement(s) non
    # enregistré(s) dans QB (avec le motif QBO exact) alors que la facture,
    # elle, est bien synchronisée. Permet à l'utilisateur de voir POURQUOI
    # un paiement n'est pas passé, au lieu d'un échec silencieux.
    sync_warning: Optional[str] = None
    #: Information (pas un échec) : ex. facture QB liée à un devis d'un
    #: autre sous-client → client QB conservé ; numéro changé parce que
    #: QB l'avait déjà pour une autre facture.
    sync_note: Optional[str] = None
    #: Numéro de la facture après la synchro (il change si QB avait déjà
    #: ce numéro pour une autre facture).
    reference: Optional[str] = None


@router.post(
    "/{facture_id}/qbo/sync",
    response_model=QboSyncResult,
    summary="Push / update the QBO Invoice for this facture",
)
async def sync_facture(
    facture_id: int,
    db: DBSession,
    user: CurrentUser,
) -> QboSyncResult:
    if not await user_has_capability(db, user, "qbo.push"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour cette action.",
        )
    try:
        result = await sync_facture_to_qbo(db, facture_id)
    except FactureSyncError as exc:
        # Persiste le motif sur la facture (session fraîche) pour l'afficher
        # sur la fiche même après fermeture de la bannière. On annule
        # d'abord la transaction de la requête : une renumérotation en
        # cours y verrouille la ligne de la facture, et la session fraîche
        # l'attendrait sans fin.
        from app.services.facture_qbo import record_facture_sync_error

        await db.rollback()
        await record_facture_sync_error(facture_id, str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return QboSyncResult(
        qbo_invoice_id=str(result.get("qbo_invoice_id") or ""),
        qbo_doc_number=str(result.get("qbo_doc_number") or ""),
        sync_warning=result.get("sync_warning"),
        sync_note=result.get("sync_note"),
        reference=result.get("reference") or None,
    )


class QboDetachResult(BaseModel):
    detache: bool
    paiements_detaches: int = 0
    qbo_invoice_id: Optional[str] = None
    qbo_doc_number: Optional[str] = None


@router.post(
    "/{facture_id}/qbo/detacher",
    response_model=QboDetachResult,
    summary="Oublier le lien avec l'Invoice QuickBooks (sans toucher à QB)",
)
async def detach_facture(
    facture_id: int,
    db: DBSession,
    user: CurrentUser,
) -> QboDetachResult:
    """Quand Kratos s'est accroché à la MAUVAISE Invoice QB (même numéro,
    autre facture) : on détache ici, on renumérote la facture (crayon),
    puis « Envoyer vers QuickBooks » crée une nouvelle Invoice. QuickBooks
    n'est pas modifié."""
    if not await user_has_capability(db, user, "qbo.push"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour cette action.",
        )
    try:
        res = await detacher_facture_qbo(db, facture_id)
    except FactureSyncError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    return QboDetachResult(**res)
