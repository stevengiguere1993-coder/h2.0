"""Versements (paiements partiels) d'un Achat fournisseur.

    GET    /api/v1/achats/{id}/versements          — liste
    POST   /api/v1/achats/{id}/versements          — ajouter un versement
    DELETE /api/v1/achats/versements/{versement_id} — supprimer

Une facture payée en plusieurs virements est poussée vers QB comme un
Bill + une BillPayment PAR versement (montant + date + compte réels) —
chaque ligne du flux bancaire s'apparie alors à SON paiement. Quand la
somme des versements couvre le TTC, l'achat passe automatiquement en
« payé ».
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.achat import Achat, AchatStatus, PaymentMethod
from app.models.achat_versement import AchatVersement

log = logging.getLogger(__name__)
router = APIRouter(prefix="/achats", tags=["achats-versements"])

_ALLOWED_METHODS = {
    m.value for m in PaymentMethod if m != PaymentMethod.BILL_TO_PAY
}


class VersementCreate(BaseModel):
    amount: float = Field(..., gt=0)
    paid_at: Optional[date] = None
    payment_method: str = Field(..., max_length=32)


class VersementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    achat_id: int
    amount: float
    paid_at: Optional[date]
    payment_method: str
    qbo_bill_payment_id: Optional[str]


def _resync_in_background(achat_id: int) -> None:
    """Re-pousse l'achat vers QB (Bill + BillPayments par versement) sans
    bloquer la réponse. Best-effort : un échec est loggué, pas remonté."""
    from app.api.v1.endpoints.achat_qbo import autopush_achat

    asyncio.create_task(autopush_achat(achat_id))


async def _refresh_paid_state(db, achat: Achat) -> None:
    """Si la somme des versements couvre le TTC, l'achat passe en payé
    (paid_at = date du dernier versement) ; sinon il reste/retombe à
    « received » avec son échéance d'origine intacte."""
    rows = list(
        (
            await db.execute(
                select(AchatVersement).where(
                    AchatVersement.achat_id == achat.id
                )
            )
        )
        .scalars()
        .all()
    )
    total_paye = round(sum(float(v.amount or 0) for v in rows), 2)
    ttc = round(
        float(achat.amount or 0) + float(achat.amount_taxes or 0), 2
    )
    if rows and ttc > 0 and total_paye >= ttc:
        achat.status = AchatStatus.PAID.value
        last = max((v.paid_at for v in rows if v.paid_at), default=None)
        achat.paid_at = (
            datetime.combine(last, time(12, 0), tzinfo=timezone.utc)
            if last
            else datetime.now(timezone.utc)
        )
        achat.due_at = None
    elif achat.status == AchatStatus.PAID.value:
        # Un versement supprimé peut repasser l'achat sous le TTC.
        achat.status = AchatStatus.RECEIVED.value
        achat.paid_at = None


@router.get(
    "/{achat_id}/versements",
    response_model=List[VersementRead],
    summary="Versements (paiements partiels) d'un achat",
)
async def list_versements(
    achat_id: int, db: DBSession, _: CurrentUser
) -> List[VersementRead]:
    rows = list(
        (
            await db.execute(
                select(AchatVersement)
                .where(AchatVersement.achat_id == achat_id)
                .order_by(
                    AchatVersement.paid_at.asc(), AchatVersement.id.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [VersementRead.model_validate(v) for v in rows]


@router.post(
    "/{achat_id}/versements",
    response_model=VersementRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un versement (paiement partiel) à un achat",
)
async def add_versement(
    achat_id: int,
    payload: VersementCreate,
    db: DBSession,
    _: RequireManager,
) -> VersementRead:
    if payload.payment_method not in _ALLOWED_METHODS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Mode de paiement invalide pour un versement : choisis le "
            "mode réel (chèque, carte) — pas « facture à payer ».",
        )
    achat = await db.get(Achat, achat_id)
    if achat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat introuvable.")
    if achat.status == AchatStatus.CANCELLED.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cet achat est annulé.")

    v = AchatVersement(
        achat_id=achat.id,
        amount=round(float(payload.amount), 2),
        paid_at=payload.paid_at,
        payment_method=payload.payment_method,
    )
    db.add(v)
    await db.flush()
    await _refresh_paid_state(db, achat)
    await db.flush()

    _resync_in_background(int(achat.id))
    return VersementRead.model_validate(v)


@router.delete(
    "/versements/{versement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un versement (et sa BillPayment QB si poussée)",
)
async def delete_versement(
    versement_id: int, db: DBSession, _: RequireManager
) -> None:
    v = await db.get(AchatVersement, versement_id)
    if v is None:
        return
    achat = await db.get(Achat, v.achat_id)
    # Supprime aussi la BillPayment QB correspondante (best-effort) pour
    # ne pas laisser un paiement orphelin côté comptable.
    if v.qbo_bill_payment_id:
        try:
            from app.integrations.quickbooks import get_qbo

            qbo = get_qbo()
            if qbo.ready:
                ok = await qbo.delete_bill_payment(str(v.qbo_bill_payment_id))
                if not ok:
                    log.warning(
                        "Versement %s : suppression BillPayment QB %s échouée",
                        v.id,
                        v.qbo_bill_payment_id,
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Versement %s : suppression BillPayment QB échouée : %s",
                v.id,
                exc,
            )
    await db.delete(v)
    await db.flush()
    if achat is not None:
        await _refresh_paid_state(db, achat)
        await db.flush()
