"""Stripe Checkout pour les factures du pôle Développement logiciel.

Flow :

    1. Le client ouvre la page publique /devlog/pay-invoice/{token}.
    2. Il clique « Payer en ligne par carte de crédit ».
    3. Le frontend POST sur /public/devlog/invoices/{token}/checkout-session.
    4. Ce service crée une Stripe Checkout Session en mode `payment`,
       montant = total TTC de la facture (cents), currency = CAD.
    5. Retourne l'URL hostée Stripe ; le frontend redirige.
    6. Stripe POST sur /webhooks/stripe/devlog quand la session est
       payée — `handle_stripe_webhook` marque la facture `payee`.

Sécurité : la signature Stripe (header `Stripe-Signature`) est
vérifiée par `stripe.Webhook.construct_event`. Sans
`STRIPE_WEBHOOK_SECRET` configurée, l'endpoint webhook répond 503.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.devlog_client import DevlogClient
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_invoice_item import DevlogInvoiceItem
from app.services.audit import log_action
from app.services.devlog_invoice_pdf import compute_invoice_totals

log = logging.getLogger(__name__)


class DevlogStripeError(Exception):
    """Erreur métier lors d'un appel Stripe (config absente, montant 0,
    etc.). Le caller convertit en HTTPException 400/503 au besoin."""


def _stripe_module():
    """Import paresseux de la SDK Stripe + injection de la clé secrète.

    On évite d'importer `stripe` au boot — la lib est lourde et tous
    les workers n'en ont pas besoin. Lève DevlogStripeError si la clé
    secrète n'est pas configurée."""

    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret:
        raise DevlogStripeError(
            "Stripe non configuré (STRIPE_SECRET_KEY absente)."
        )
    try:
        import stripe  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise DevlogStripeError(
            "Dépendance `stripe` non installée."
        ) from exc
    stripe.api_key = secret
    return stripe


def _public_base_url() -> str:
    return (
        os.getenv("STRIPE_DEVLOG_SUCCESS_URL_BASE")
        or "https://kratos.immohorizon.com/fr/devlog/pay-invoice"
    ).rstrip("/")


async def create_checkout_session(
    invoice: DevlogInvoice, db: AsyncSession
) -> str:
    """Crée une Stripe Checkout Session pour la facture passée et
    retourne l'URL hostée à laquelle rediriger le client.

    - Mode : `payment` (one-shot, pas d'abonnement).
    - Devise : CAD.
    - Ligne unique : description = « <numéro> — <nom client> »,
      montant = total TTC arrondi au cent.
    - `metadata.invoice_id` = ID interne, utilisé par le webhook
      comme garde-fou si `stripe_session_id` n'a pas été persisté
      à temps (rare mais possible en cas d'erreur réseau).
    """
    stripe = _stripe_module()

    # Calcul du total à charger.
    items = list(
        (
            await db.execute(
                select(DevlogInvoiceItem).where(
                    DevlogInvoiceItem.invoice_id == invoice.id
                )
            )
        ).scalars().all()
    )
    totals = compute_invoice_totals(items)
    total_cad = float(totals.get("total") or 0.0)
    # Fallback : si pas d'items (legacy ou facture libre), prendre
    # invoice.amount (qui peut être HT ou TTC selon le workflow —
    # on l'utilise tel quel faute de mieux).
    if total_cad <= 0:
        total_cad = float(invoice.amount or 0.0)
    if total_cad <= 0:
        raise DevlogStripeError(
            "Montant nul — impossible de créer un paiement Stripe."
        )
    amount_cents = int(round(total_cad * 100))

    # Description ligne Stripe.
    client_name: Optional[str] = None
    if invoice.client_id is not None:
        client = (
            await db.execute(
                select(DevlogClient).where(
                    DevlogClient.id == invoice.client_id
                )
            )
        ).scalar_one_or_none()
        if client is not None:
            client_name = client.name
    label_parts = [invoice.number or f"Facture #{invoice.id}"]
    if client_name:
        label_parts.append(client_name)
    line_label = " — ".join(label_parts)

    base = _public_base_url()
    token = invoice.signature_token or ""
    success_url = f"{base}/{token}?paid=1"
    cancel_url = f"{base}/{token}?cancelled=1"

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": "cad",
                    "unit_amount": amount_cents,
                    "product_data": {
                        "name": line_label[:250],
                        "description": (
                            f"Paiement de la facture {invoice.number}"
                            if invoice.number
                            else "Paiement facture Horizon"
                        )[:500],
                    },
                },
            }
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "invoice_id": str(invoice.id),
            "invoice_number": (invoice.number or "")[:100],
            "kind": "devlog_invoice",
        },
    )

    # Persiste l'ID de session pour le webhook.
    invoice.stripe_session_id = session.id
    await db.flush()

    url = getattr(session, "url", None)
    if not url:
        raise DevlogStripeError(
            "Stripe n'a pas renvoyé d'URL pour la session."
        )
    return str(url)


async def _find_invoice_for_event(
    db: AsyncSession, session_obj: dict
) -> Optional[DevlogInvoice]:
    """Retrouve la facture associée à un event Stripe.

    Priorité : metadata.invoice_id (plus fiable), fallback sur
    stripe_session_id stocké en base."""

    metadata = session_obj.get("metadata") or {}
    invoice_id_str = metadata.get("invoice_id")
    if invoice_id_str:
        try:
            invoice_id = int(invoice_id_str)
        except (TypeError, ValueError):
            invoice_id = None
        if invoice_id is not None:
            inv = (
                await db.execute(
                    select(DevlogInvoice).where(
                        DevlogInvoice.id == invoice_id
                    )
                )
            ).scalar_one_or_none()
            if inv is not None:
                return inv

    session_id = session_obj.get("id")
    if session_id:
        inv = (
            await db.execute(
                select(DevlogInvoice).where(
                    DevlogInvoice.stripe_session_id == session_id
                )
            )
        ).scalar_one_or_none()
        if inv is not None:
            return inv
    return None


async def handle_stripe_webhook(
    payload: bytes, signature: str, db: AsyncSession
) -> dict:
    """Vérifie la signature Stripe puis traite l'event.

    Seul `checkout.session.completed` est actuellement géré. Tout
    autre event est acquitté en silence (200) — Stripe les retentera
    sinon, et on n'a pas envie de pourrir leur queue.

    Lève DevlogStripeError (→ 400) si la signature est invalide.
    """
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise DevlogStripeError(
            "Webhook Stripe non configuré (STRIPE_WEBHOOK_SECRET)."
        )
    stripe = _stripe_module()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature or "",
            secret=webhook_secret,
        )
    except Exception as exc:  # signature invalide / payload mal formé
        raise DevlogStripeError(
            f"Signature Stripe invalide : {exc}"
        ) from exc

    event_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
    data_obj = (
        event.get("data", {}).get("object", {})
        if isinstance(event, dict)
        else getattr(getattr(event, "data", None), "object", {}) or {}
    )

    if event_type != "checkout.session.completed":
        log.info("Stripe webhook ignoré (type=%s)", event_type)
        return {"ok": True, "ignored": event_type}

    # `data_obj` peut être un objet stripe ou un dict — on normalise.
    if not isinstance(data_obj, dict):
        try:
            data_obj = dict(data_obj)
        except Exception:
            data_obj = {}

    # Sécurité : ne marquer payée que si la session a réellement été
    # encaissée. payment_status == 'paid' couvre les paiements carte
    # one-shot ; 'no_payment_required' n'arrive pas en mode `payment`.
    payment_status = data_obj.get("payment_status")
    if payment_status not in ("paid", "no_payment_required"):
        log.info(
            "Stripe checkout.session.completed reçu mais "
            "payment_status=%s — ignoré.",
            payment_status,
        )
        return {"ok": True, "skipped": payment_status}

    invoice = await _find_invoice_for_event(db, data_obj)
    if invoice is None:
        log.warning(
            "Stripe webhook : facture introuvable pour session=%s",
            data_obj.get("id"),
        )
        return {"ok": True, "warning": "invoice_not_found"}

    # Idempotence — si déjà payée, on ne retouche pas.
    if invoice.status == "payee":
        return {"ok": True, "already_paid": invoice.id}

    invoice.status = "payee"
    invoice.paid_at = datetime.now(timezone.utc)
    invoice.payment_method = "stripe"
    payment_intent = data_obj.get("payment_intent")
    if isinstance(payment_intent, str):
        invoice.stripe_payment_intent_id = payment_intent
    # Garantit que stripe_session_id pointe sur la session encaissée
    # (cas où on a retrouvé la facture via metadata.invoice_id).
    session_id_evt = data_obj.get("id")
    if isinstance(session_id_evt, str) and not invoice.stripe_session_id:
        invoice.stripe_session_id = session_id_evt
    await db.flush()

    await log_action(
        db,
        user=None,
        action="devlog_invoice.paid_via_stripe",
        entity_type="devlog_invoice",
        entity_id=invoice.id,
        details={
            "number": invoice.number,
            "amount": float(invoice.amount or 0),
            "stripe_session_id": invoice.stripe_session_id,
            "stripe_payment_intent_id": invoice.stripe_payment_intent_id,
        },
    )

    return {"ok": True, "invoice_id": invoice.id}
