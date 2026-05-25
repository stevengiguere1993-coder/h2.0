"""Endpoints publics (no auth) — consultation d'une facture devlog.

Flow client :

    GET  /api/v1/public/devlog/invoices/{token}                       -> JSON
    GET  /api/v1/public/devlog/invoices/{token}/pdf                   -> PDF
    POST /api/v1/public/devlog/invoices/{token}/checkout-session      -> {url}

Le token est opaque (32 octets URL-safe) et fait office
d'authentification. Pas d'expiration (contrairement à une soumission,
une facture reste consultable indéfiniment par le client).

Paiement en ligne via Stripe Checkout hosted depuis le chantier #4
(mai 2026) — voir `app.services.devlog_stripe`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.core.config import settings
from app.models.devlog_client import DevlogClient
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_invoice_item import DevlogInvoiceItem
from app.services.audit import log_action
from app.services.devlog_invoice_pdf import (
    PAYMENT_INSTRUCTIONS,
    compute_invoice_totals,
    generate_invoice_pdf,
)
from app.services.devlog_stripe import (
    DevlogStripeError,
    create_checkout_session,
)


router = APIRouter(prefix="/public/devlog/invoices", tags=["devlog-public"])


# --------------------------- Schemas ---------------------------


class _PublicInvoiceItem(BaseModel):
    description: str
    unit: Optional[str]
    quantity: float
    unit_price: float
    total: float


class PublicInvoice(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: Optional[str]
    status: str
    issued_date: Optional[date]
    due_date: Optional[date]
    sent_at: Optional[datetime]
    paid_at: Optional[datetime]
    client_name: Optional[str]
    client_email: Optional[str]
    client_address: Optional[str]
    notes: Optional[str]
    items: list[_PublicInvoiceItem]
    sous_total: float
    tps: float
    tvq: float
    total: float
    payment_instructions: str
    # Méthodes de paiement disponibles (exposées à la page publique).
    # Stripe est cachée derrière un feature flag (Settings.stripe_enabled).
    # Quand False, le bouton "Payer par carte" n'est pas rendu côté
    # frontend et seul le bloc Interac/chèque s'affiche.
    stripe_enabled: bool
    # Email destinataire pour les virements Interac affiché en gros sur
    # la page publique (copiable au clic).
    interac_email: str


# --------------------------- Helpers ---------------------------


async def _load_by_token(
    db: AsyncSession, token: str
) -> DevlogInvoice:
    invoice = (
        await db.execute(
            select(DevlogInvoice).where(
                DevlogInvoice.signature_token == token
            )
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Lien invalide."
        )
    return invoice


async def _load_client(
    db: AsyncSession, client_id: Optional[int]
) -> Optional[DevlogClient]:
    if client_id is None:
        return None
    return (
        await db.execute(
            select(DevlogClient).where(DevlogClient.id == client_id)
        )
    ).scalar_one_or_none()


async def _load_items(
    db: AsyncSession, invoice_id: int
) -> list[DevlogInvoiceItem]:
    return list(
        (
            await db.execute(
                select(DevlogInvoiceItem)
                .where(DevlogInvoiceItem.invoice_id == invoice_id)
                .order_by(
                    DevlogInvoiceItem.position.asc(),
                    DevlogInvoiceItem.id.asc(),
                )
            )
        ).scalars().all()
    )


async def _to_public(
    db: AsyncSession, invoice: DevlogInvoice
) -> PublicInvoice:
    client = await _load_client(db, invoice.client_id)
    items = await _load_items(db, invoice.id)
    totals = compute_invoice_totals(items)
    return PublicInvoice(
        id=invoice.id,
        number=invoice.number,
        status=invoice.status,
        issued_date=invoice.issued_date,
        due_date=invoice.due_date,
        sent_at=getattr(invoice, "sent_at", None),
        paid_at=getattr(invoice, "paid_at", None),
        client_name=(client.name if client else None),
        client_email=(client.email if client else None),
        client_address=(client.address if client else None),
        notes=invoice.notes,
        items=[
            _PublicInvoiceItem(
                description=it.description or "",
                unit=it.unit,
                quantity=float(it.quantity or 0),
                unit_price=float(it.unit_price or 0),
                total=float(it.total or 0),
            )
            for it in items
        ],
        sous_total=totals["sous_total"],
        tps=totals["tps"],
        tvq=totals["tvq"],
        total=totals["total"],
        payment_instructions=PAYMENT_INSTRUCTIONS,
        stripe_enabled=settings.stripe_enabled,
        interac_email=settings.devlog_interac_email,
    )


# --------------------------- Routes ---------------------------


@router.get(
    "/{token}",
    response_model=PublicInvoice,
    summary="Détails publics d'une facture (page de consultation client)",
)
async def read_public_invoice(
    token: str, db: DBSession
) -> PublicInvoice:
    invoice = await _load_by_token(db, token)
    return await _to_public(db, invoice)


@router.get(
    "/{token}/pdf",
    summary="PDF inline (page publique)",
)
async def public_invoice_pdf(
    token: str, db: DBSession
) -> Response:
    invoice = await _load_by_token(db, token)
    pdf_bytes = await generate_invoice_pdf(db, invoice.id)
    label = invoice.number or f"facture-{invoice.id}"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{label}.pdf"'},
    )


# --------------------------- Stripe Checkout ---------------------------


class _CheckoutResponse(BaseModel):
    url: str


@router.post(
    "/{token}/checkout-session",
    response_model=_CheckoutResponse,
    summary=(
        "Crée une Stripe Checkout Session pour la facture et retourne "
        "l'URL hostée vers laquelle rediriger le client."
    ),
)
async def create_invoice_checkout_session(
    token: str, db: DBSession
) -> _CheckoutResponse:
    # Feature flag : tant que stripe_enabled=False (défaut depuis
    # mai 2026), on refuse les tentatives de création de session même
    # si quelqu'un POST directement. Le frontend, lui, cache le bouton.
    if not settings.stripe_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Paiement par carte temporairement désactivé.",
        )
    invoice = await _load_by_token(db, token)
    if invoice.status == "payee":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette facture est déjà payée.",
        )
    if invoice.status == "annulee":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette facture est annulée.",
        )
    try:
        url = await create_checkout_session(invoice, db)
    except DevlogStripeError as exc:
        # 503 si Stripe n'est pas configuré, 400 sinon (montant nul…).
        msg = str(exc)
        if "non configuré" in msg or "non installée" in msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=msg,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        ) from exc

    await log_action(
        db,
        user=None,
        action="devlog_invoice.stripe_checkout_started",
        entity_type="devlog_invoice",
        entity_id=invoice.id,
        details={
            "number": invoice.number,
            "stripe_session_id": invoice.stripe_session_id,
        },
    )
    return _CheckoutResponse(url=url)
