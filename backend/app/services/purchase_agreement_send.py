"""Envoi d'une PA à l'acheteur interne (étape 1) puis au vendeur (étape 2).

Pattern calqué sur soumission_send.py :
- Génère un token opaque si absent.
- Rend le PDF.
- Envoie via Microsoft Graph avec lien public + PDF en pièce jointe.
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.purchase_agreement import (
    PurchaseAgreement,
    PurchaseAgreementStatus,
)
from app.services.purchase_agreement_pdf import render_purchase_agreement_pdf


log = logging.getLogger(__name__)


def _public_base() -> str:
    return (
        os.getenv("PUBLIC_SITE_URL") or "https://immohorizon.com"
    ).rstrip("/")


class PurchaseAgreementSendError(Exception):
    pass


def _money(n: Optional[float]) -> str:
    if n is None:
        return "—"
    return f"{float(n):,.2f} $".replace(",", " ")


def _shared_intro(intro: Optional[str]) -> str:
    if not intro:
        return ""
    safe = intro.replace("\n", "<br>")
    return f'<p style="margin:0 0 16px 0">{safe}</p>'


def _signature_block(label: str, url: str) -> str:
    return f"""\
  <p style="margin:20px 0 6px 0">
    <a href="{url}"
       style="display:inline-block;background:#d89b3c;color:#111;
              padding:12px 20px;border-radius:8px;font-weight:bold;
              text-decoration:none">{label}</a>
  </p>
  <p style="margin:0 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {url}
  </p>"""


def _buyer_body(pa: PurchaseAgreement, intro: Optional[str]) -> str:
    sign_url = (
        f"{_public_base()}/promesse-achat/acheteur/{pa.buyer_signature_token}"
    )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p style="margin:0 0 16px 0">Bonjour,</p>
  {_shared_intro(intro)}
  <p style="margin:0 0 16px 0">
    Voici la promesse d'achat <strong>{pa.reference}</strong>
    pour la propriété au <em>{pa.property_address or "—"}</em>.
  </p>
  <p style="margin:0 0 8px 0"><strong>Prix offert :</strong> {_money(pa.price)}</p>
  <p style="margin:0 0 8px 0">
    Avant l'envoi au vendeur, l'acheteur doit signer cette PA.
  </p>
  {_signature_block("Réviser et signer (acheteur)", sign_url)}
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers &middot; immohorizon.com
  </p>
</div>
"""


def _seller_body(pa: PurchaseAgreement, intro: Optional[str]) -> str:
    sign_url = (
        f"{_public_base()}/promesse-achat/vendeur/{pa.seller_signature_token}"
    )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p style="margin:0 0 16px 0">Bonjour,</p>
  {_shared_intro(intro)}
  <p style="margin:0 0 16px 0">
    Vous trouverez ci-joint une promesse d'achat
    <strong>{pa.reference}</strong> pour votre propriété au
    <em>{pa.property_address or "—"}</em>, signée par l'acheteur.
  </p>
  <p style="margin:0 0 8px 0"><strong>Prix offert :</strong> {_money(pa.price)}</p>
  <p style="margin:0 0 8px 0">
    Vous avez l'option d'<strong>accepter</strong> ou de
    <strong>refuser</strong> cette offre en ligne.
  </p>
  {_signature_block("Voir et répondre à l'offre", sign_url)}
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers &middot; immohorizon.com
  </p>
</div>
"""


async def _ensure_pa(
    db: AsyncSession, pa_id: int
) -> PurchaseAgreement:
    pa = (
        await db.execute(
            select(PurchaseAgreement).where(PurchaseAgreement.id == pa_id)
        )
    ).scalar_one_or_none()
    if pa is None:
        raise PurchaseAgreementSendError(
            f"Promesse d'achat {pa_id} introuvable."
        )
    return pa


async def _send(
    db: AsyncSession,
    *,
    pa: PurchaseAgreement,
    to: Iterable[str],
    cc: Optional[Iterable[str]],
    subject: str,
    html_body: str,
) -> None:
    mailer = get_mailer()
    if not mailer.ready:
        raise PurchaseAgreementSendError(
            "Microsoft Graph mailer non configuré (AZURE_* / MAIL_FROM_EMAIL)."
        )
    recipients = [a.strip() for a in to if a and a.strip()]
    if not recipients:
        raise PurchaseAgreementSendError("Au moins un destinataire est requis.")
    cc_list = [a.strip() for a in (cc or []) if a and a.strip()]

    pdf_bytes = await render_purchase_agreement_pdf(db, pa.id)
    attachment = EmailAttachment(
        name=f"promesse-achat-{pa.reference}.pdf",
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )
    try:
        await mailer.send(
            to=recipients,
            subject=subject,
            html_body=html_body,
            cc=cc_list or None,
            reply_to=mailer.sender,
            attachments=[attachment],
        )
    except Exception as exc:
        log.exception("Graph send failed for PA %s", pa.id)
        raise PurchaseAgreementSendError(f"Envoi courriel échoué: {exc}") from exc


async def send_to_buyer(
    db: AsyncSession,
    pa_id: int,
    *,
    to: Iterable[str],
    cc: Optional[Iterable[str]] = None,
    subject: Optional[str] = None,
    message: Optional[str] = None,
) -> PurchaseAgreement:
    pa = await _ensure_pa(db, pa_id)
    if not pa.buyer_signature_token:
        pa.buyer_signature_token = secrets.token_urlsafe(32)
        await db.flush()
    pa.status = PurchaseAgreementStatus.PENDING_BUYER_SIGNATURE.value

    subj = subject or f"Promesse d'achat {pa.reference} — signature acheteur"
    body = _buyer_body(pa, message)
    await _send(db, pa=pa, to=to, cc=cc, subject=subj, html_body=body)

    await db.flush()
    await db.refresh(pa)
    return pa


async def send_to_seller(
    db: AsyncSession,
    pa_id: int,
    *,
    to: Iterable[str],
    cc: Optional[Iterable[str]] = None,
    subject: Optional[str] = None,
    message: Optional[str] = None,
) -> PurchaseAgreement:
    pa = await _ensure_pa(db, pa_id)
    if pa.status != PurchaseAgreementStatus.PENDING_SELLER_SIGNATURE.value:
        raise PurchaseAgreementSendError(
            "PA non prête pour l'envoi au vendeur (acheteur doit signer d'abord)."
        )
    if not pa.seller_signature_token:
        pa.seller_signature_token = secrets.token_urlsafe(32)
        await db.flush()
    pa.sent_to_seller_at = datetime.now(timezone.utc)

    subj = subject or f"Offre d'achat — {pa.property_address or pa.reference}"
    body = _seller_body(pa, message)
    await _send(db, pa=pa, to=to, cc=cc, subject=subj, html_body=body)

    await db.flush()
    await db.refresh(pa)
    return pa
