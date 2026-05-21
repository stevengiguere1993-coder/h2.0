"""Partial / full payments applied to a Facture.

    GET    /api/v1/factures/{facture_id}/payments
    POST   /api/v1/factures/{facture_id}/payments
    PATCH  /api/v1/factures/{facture_id}/payments/{payment_id}
    DELETE /api/v1/factures/{facture_id}/payments/{payment_id}

When the sum of payments reaches the facture total, the facture is
auto-marked as PAID (paid_at = date of the last payment). Deleting or
lowering payments reverts the status back to SENT.
"""

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.models.facture import Facture, FactureStatus
from app.models.payment import Payment, PaymentMethod


log = logging.getLogger(__name__)
router = APIRouter(prefix="/factures", tags=["payments"])


async def _send_statement_email(facture_id: int) -> None:
    """Envoie l'état de compte du projet au client, en arrière-plan.
    Best-effort : silencieux s'il n'y a pas de projet, pas de courriel
    client, ou si le mailer n'est pas configuré."""
    from app.db.session import AsyncSessionLocal
    from app.integrations.email_graph import EmailAttachment, get_mailer
    from app.models.client import Client
    from app.services.facture_pdf import render_statement_pdf

    try:
        async with AsyncSessionLocal() as db:
            fa = (
                await db.execute(
                    select(Facture).where(Facture.id == facture_id)
                )
            ).scalar_one_or_none()
            if fa is None or fa.project_id is None or fa.client_id is None:
                return
            client = (
                await db.execute(
                    select(Client).where(Client.id == fa.client_id)
                )
            ).scalar_one_or_none()
            if client is None or not client.email:
                return
            rendered = await render_statement_pdf(db, fa.project_id)
            if rendered is None:
                return
            _project, pdf_bytes = rendered
            mailer = get_mailer()
            if not mailer.ready:
                log.warning(
                    "Envoi état de compte ignoré : mailer non configuré"
                )
                return
            is_en = (getattr(client, "language", "fr") or "fr") == "en"
            subject = (
                "Account statement — Horizon Services Immobiliers"
                if is_en
                else "État de compte — Horizon Services Immobiliers"
            )
            body = (
                "<p>Hello,</p><p>Please find attached the current "
                "account statement for your project.</p>"
                if is_en
                else "<p>Bonjour,</p><p>Vous trouverez ci-joint "
                "l'état de compte à jour de votre projet.</p>"
            )
            await mailer.send(
                to=[client.email],
                subject=subject,
                html_body=body,
                attachments=[
                    EmailAttachment(
                        name="etat-de-compte.pdf",
                        content_bytes=pdf_bytes,
                        content_type="application/pdf",
                    )
                ],
            )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Envoi état de compte échoué (facture %s) : %s",
            facture_id,
            exc,
        )


class PaymentCreate(BaseModel):
    amount: float = Field(..., gt=0)
    method: str = Field(
        default=PaymentMethod.OTHER.value,
        pattern="^(cash|credit_card|debit_card|check|bank_transfer|other)$",
    )
    paid_at: date
    reference: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = None
    # Si vrai, envoie l'état de compte du projet au client par courriel
    # juste après l'enregistrement du paiement.
    send_statement: bool = False


class PaymentUpdate(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    method: Optional[str] = Field(
        default=None,
        pattern="^(cash|credit_card|debit_card|check|bank_transfer|other)$",
    )
    paid_at: Optional[date] = None
    reference: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    facture_id: int
    amount: float
    method: str
    paid_at: date
    reference: Optional[str]
    notes: Optional[str]
    qbo_payment_id: Optional[str]
    created_at: datetime


async def _ensure_facture(db, facture_id: int) -> Facture:
    record = (
        await db.execute(select(Facture).where(Facture.id == facture_id))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture not found")
    return record


async def _recompute_facture_status(db, facture: Facture) -> None:
    """Recompute Facture status + paid_at from the sum of its payments."""
    paid_sum = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.facture_id == facture.id
            )
        )
    ).scalar_one()
    total = float(facture.total or 0)
    paid = float(paid_sum or 0)
    if total > 0 and paid >= total:
        # Fully paid
        last_paid_at = (
            await db.execute(
                select(func.max(Payment.paid_at)).where(
                    Payment.facture_id == facture.id
                )
            )
        ).scalar_one()
        facture.status = FactureStatus.PAID.value
        if last_paid_at:
            facture.paid_at = datetime.combine(
                last_paid_at, datetime.min.time(), tzinfo=timezone.utc
            )
    else:
        # Not fully paid anymore — revert to SENT if it was PAID, keep
        # OVERDUE / DRAFT otherwise so we don't mask a prior state.
        if facture.status == FactureStatus.PAID.value:
            facture.status = FactureStatus.SENT.value
            facture.paid_at = None


@router.get(
    "/{facture_id}/payments",
    response_model=List[PaymentRead],
    summary="List payments applied to a facture",
)
async def list_payments(
    facture_id: int, db: DBSession, _: CurrentUser
) -> List[PaymentRead]:
    await _ensure_facture(db, facture_id)
    rows = (
        await db.execute(
            select(Payment)
            .where(Payment.facture_id == facture_id)
            .order_by(Payment.paid_at.asc(), Payment.id.asc())
        )
    ).scalars().all()
    return [PaymentRead.model_validate(r) for r in rows]


@router.post(
    "/{facture_id}/payments",
    response_model=PaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a payment on a facture",
)
async def create_payment(
    facture_id: int,
    data: PaymentCreate,
    db: DBSession,
    background: BackgroundTasks,
    _: CurrentUser,
) -> PaymentRead:
    fa = await _ensure_facture(db, facture_id)
    p = Payment(
        facture_id=facture_id,
        amount=data.amount,
        method=data.method,
        paid_at=data.paid_at,
        reference=(data.reference.strip() if data.reference else None),
        notes=(data.notes.strip() if data.notes else None),
    )
    db.add(p)
    await db.flush()
    await db.refresh(p)
    await _recompute_facture_status(db, fa)
    await db.flush()
    # Envoi optionnel de l'état de compte au client (en arrière-plan
    # pour ne pas ralentir la réponse).
    if data.send_statement:
        background.add_task(_send_statement_email, facture_id)
    return PaymentRead.model_validate(p)


@router.patch(
    "/{facture_id}/payments/{payment_id}",
    response_model=PaymentRead,
    summary="Update a payment",
)
async def update_payment(
    facture_id: int,
    payment_id: int,
    data: PaymentUpdate,
    db: DBSession,
    _: CurrentUser,
) -> PaymentRead:
    fa = await _ensure_facture(db, facture_id)
    p = (
        await db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.facture_id == facture_id,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    upd = data.model_dump(exclude_unset=True)
    for field, value in upd.items():
        setattr(p, field, value)
    await db.flush()
    await _recompute_facture_status(db, fa)
    await db.flush()
    await db.refresh(p)
    return PaymentRead.model_validate(p)


@router.delete(
    "/{facture_id}/payments/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a payment",
)
async def delete_payment(
    facture_id: int,
    payment_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    fa = await _ensure_facture(db, facture_id)
    p = (
        await db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.facture_id == facture_id,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    await db.delete(p)
    await db.flush()
    await _recompute_facture_status(db, fa)
    await db.flush()
