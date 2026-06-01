"""Achat — actions de paiement.

    POST /api/v1/achats/{id}/mark-paid    — bouton « Marquer paye »

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
