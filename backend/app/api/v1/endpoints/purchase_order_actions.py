"""Endpoints d'action sur un PurchaseOrder (envoi par courriel +
conversion en Achat). Le CRUD basique du PO est géré par le router
générique `purchase_orders_router` dans business.py.

    POST /api/v1/purchase-orders/{id}/send-po
    POST /api/v1/purchase-orders/{id}/convert-to-achat
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat, AchatStatus
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus
from app.schemas.business import AchatRead, PurchaseOrderRead
from app.services.purchase_order_send import (
    PurchaseOrderSendError,
    send_purchase_order,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


class SendPoRequest(BaseModel):
    extra_message: Optional[str] = Field(default=None, max_length=2000)


@router.post(
    "/{po_id}/send-po",
    response_model=PurchaseOrderRead,
    summary="Envoyer le PO par courriel à l'employé assigné",
)
async def send_po_endpoint(
    po_id: int,
    data: SendPoRequest,
    db: DBSession,
    _: CurrentUser,
) -> PurchaseOrderRead:
    try:
        po = await send_purchase_order(
            db, po_id, extra_message=data.extra_message
        )
    except PurchaseOrderSendError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return PurchaseOrderRead.model_validate(po)


class ConvertToAchatRequest(BaseModel):
    """Champs réels au moment où l'employé revient avec sa facture
    fournisseur. Tous optionnels — ce qui n'est pas fourni est repris
    du PO source."""

    amount: Optional[float] = Field(default=None, ge=0)
    supplier_invoice_number: Optional[str] = Field(default=None, max_length=64)
    invoice_date: Optional[str] = None  # ISO date string
    payment_method: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = None
    notes: Optional[str] = None


@router.post(
    "/{po_id}/convert-to-achat",
    response_model=AchatRead,
    summary="Créer un Achat à partir de ce PO",
)
async def convert_po_to_achat(
    po_id: int,
    data: ConvertToAchatRequest,
    db: DBSession,
    _: CurrentUser,
    defer_sync: bool = False,
) -> AchatRead:
    """Crée un Achat (transaction comptable) lié à ce PO. Pré-remplit
    fournisseur, projet et mode de paiement depuis le PO ; l'utilisateur
    n'a qu'à fournir le montant réel + le # de facture fournisseur.

    Marque le PO comme `fulfilled` et crée l'Achat en statut `received`.
    L'auto-push QBO démarre en arrière-plan (selon le mode de paiement).

    `defer_sync=true` saute le push automatique pour permettre au client
    d'uploader la facture en pièce jointe AVANT de pousser dans QB. Le
    client doit ensuite appeler POST /achats/{id}/qbo/sync.
    """

    po = (
        await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    ).scalar_one_or_none()
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PO introuvable")
    if po.status == PurchaseOrderStatus.CANCELLED.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Ce PO est annulé — recrée un nouveau PO si besoin.",
        )

    invoice_dt = None
    if data.invoice_date:
        try:
            from datetime import date as _date

            invoice_dt = _date.fromisoformat(data.invoice_date[:10])
        except Exception:
            invoice_dt = None

    # Description : si l'utilisateur n'a rien fourni, on essaie de
    # concaténer les articles du PO (« 70 tubes caulking · 2 boîtes
    # de vis 2 1/2 · ... »). Sinon fallback sur la description du PO.
    description = data.description
    if not description:
        from app.models.purchase_order_item import PurchaseOrderItem

        items = (
            await db.execute(
                select(PurchaseOrderItem)
                .where(PurchaseOrderItem.purchase_order_id == po.id)
                .order_by(
                    PurchaseOrderItem.position.asc(),
                    PurchaseOrderItem.id.asc(),
                )
            )
        ).scalars().all()
        if items:
            parts = []
            for it in items:
                qty_int = (
                    int(it.quantity)
                    if float(it.quantity).is_integer()
                    else float(it.quantity)
                )
                qty_str = f"{qty_int}"
                if it.unit:
                    qty_str = f"{qty_str} {it.unit}"
                parts.append(f"{qty_str} × {it.description}")
            description = " · ".join(parts)
        else:
            description = po.description

    achat = Achat(
        purchase_order_id=po.id,
        fournisseur_id=po.fournisseur_id,
        project_id=po.project_id,
        description=description,
        amount=(data.amount if data.amount is not None else po.amount_max),
        supplier_invoice_number=data.supplier_invoice_number,
        invoice_date=invoice_dt,
        payment_method=(data.payment_method or po.payment_method),
        status=AchatStatus.RECEIVED.value,
        received_at=datetime.now(timezone.utc),
        notes=data.notes,
    )
    db.add(achat)
    await db.flush()
    await db.refresh(achat)

    # Marque le PO comme accompli (un Achat l'a consommé). Reste
    # cliquable pour consulter, mais visuellement « terminé ».
    po.status = PurchaseOrderStatus.FULFILLED.value
    await db.flush()

    # Auto-push vers QBO en arrière-plan, sauf si on diffère pour
    # permettre l'upload d'une pièce jointe avant le push.
    if not defer_sync:
        try:
            import asyncio

            from app.api.v1.endpoints.achat_qbo import autopush_achat

            asyncio.create_task(autopush_achat(int(achat.id)))
        except Exception as exc:
            log.warning("Auto-push QBO planning échoué: %s", exc)

    return AchatRead.model_validate(achat)
