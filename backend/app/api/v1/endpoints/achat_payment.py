"""Achat — actions de paiement.

    POST /api/v1/achats/{id}/mark-paid    — bouton « Marquer paye »
    POST /api/v1/achats/sync-from-qbo     — pull QB Bills -> Kratos

Quand un achat etait facture fournisseur (bill_to_pay) et qu'on le
paye finalement, on enregistre le mode reel + la date. Le statut
passe a `paid` et l'echeance disparait.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import DBSession, RequireManager
from app.models.achat import Achat, AchatStatus, PaymentMethod
from app.services.achat_payment import mark_achat_paid
from app.services.achat_qbo_pull import QboPullError, pull_new_bills_from_qbo


router = APIRouter(prefix="/achats", tags=["achats-payment"])


_ALLOWED_METHODS = {m.value for m in PaymentMethod}


class MarkPaidPayload(BaseModel):
    payment_method: str = Field(..., max_length=32)
    paid_at: Optional[datetime] = None


class AchatPaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    payment_method: Optional[str]
    paid_at: Optional[datetime]
    due_at: Optional[datetime] = None


@router.post(
    "/{achat_id}/mark-paid",
    response_model=AchatPaymentRead,
    summary="Marquer un achat comme paye (set status, paid_at, methode)",
)
async def mark_paid(
    achat_id: int,
    payload: MarkPaidPayload,
    db: DBSession,
    _: RequireManager,
) -> AchatPaymentRead:
    if payload.payment_method not in _ALLOWED_METHODS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Mode de paiement invalide : {payload.payment_method}",
        )
    if payload.payment_method == PaymentMethod.BILL_TO_PAY.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Pour marquer paye, choisis le mode reel de paiement "
            "(cheque, carte) — pas 'facture a payer'.",
        )
    achat = await db.get(Achat, achat_id)
    if achat is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Achat introuvable."
        )
    if achat.status == AchatStatus.CANCELLED.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cet achat est annule.",
        )
    await mark_achat_paid(
        db,
        achat,
        payment_method=payload.payment_method,
        paid_at=payload.paid_at,
    )
    await db.flush()
    return AchatPaymentRead.model_validate(achat)


class QboPullResult(BaseModel):
    imported: int
    unmatched_project: int
    imported_paid: int
    skipped_existing: int
    total_qbo_bills: int


@router.post(
    "/sync-from-qbo",
    response_model=QboPullResult,
    summary="Importe les Bills QuickBooks absents de Kratos",
)
async def sync_from_qbo(
    db: DBSession,
    _: RequireManager,
    since_days: int = 180,
) -> QboPullResult:
    """Pull les Bills QB recents qui n'ont pas encore d'Achat
    Kratos correspondant. Garde anti-doublon via qbo_bill_id.

    - Cree un Fournisseur Kratos si le vendor QB est inconnu.
    - Tente de matcher le projet via la Class QB (= adresse).
    - Marque l'Achat paye s'il existe une BillPayment QB liee.
    - is_billable forcement False (refacturation reste pilotee
      depuis Kratos).
    """
    try:
        stats = await pull_new_bills_from_qbo(db, since_days=since_days)
    except QboPullError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        )
    return QboPullResult(**stats)
