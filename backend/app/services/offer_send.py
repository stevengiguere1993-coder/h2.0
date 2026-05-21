"""Envoi par email d'une Offre d'achat au vendeur via Microsoft Graph.

Pattern calqué sur purchase_agreement_send.py :
- Génère un token de signature opaque si absent
- Rend le PDF
- Envoie un email court au vendeur avec lien public + PDF en pièce
  jointe
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.offer import Offer, OfferStatus
from app.models.prospection_deal import ProspectionDeal
from app.services.offer_pdf import render_offer_pdf
from app.services.offer_template import BUYER_ENTITY_NAME, format_money


log = logging.getLogger(__name__)


def _public_base() -> str:
    return (
        os.getenv("PUBLIC_SITE_URL") or "https://immohorizon.com"
    ).rstrip("/")


class OfferSendError(Exception):
    pass


def _seller_body(offer: Offer, deal: Optional[ProspectionDeal]) -> str:
    """Email court et direct au vendeur."""
    sign_url = f"{_public_base()}/sign-offer/{offer.signature_token}"
    salutation = (
        f"Bonjour {offer.vendeur_nom},"
        if offer.vendeur_nom and offer.vendeur_nom.strip()
        else "Bonjour,"
    )
    address = deal.address if deal else "votre propriété"
    deadline = (
        offer.date_limite_reponse.strftime("%Y-%m-%d")
        if offer.date_limite_reponse
        else "—"
    )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.55;max-width:620px">
  <p style="margin:0 0 16px 0">{salutation}</p>
  <p style="margin:0 0 16px 0">
    <strong>{BUYER_ENTITY_NAME}</strong> vous transmet une offre
    d'achat pour la propriété située au <em>{address}</em>.
  </p>
  <p style="margin:0 0 16px 0">
    <strong>Prix offert :</strong> {format_money(offer.prix_offert)}
  </p>
  <p style="margin:0 0 16px 0">
    Vous pouvez consulter l'offre complète et la signer en ligne (ou la
    refuser) en cliquant sur le bouton ci-dessous. Le détail des
    conditions et la copie PDF sont également ci-joints.
  </p>
  <p style="margin:20px 0 6px 0">
    <a href="{sign_url}"
       style="display:inline-block;background:#2f7d32;color:#fff;
              padding:14px 24px;border-radius:8px;font-weight:bold;
              text-decoration:none">Consulter et signer l'offre</a>
  </p>
  <p style="margin:8px 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {sign_url}
  </p>
  <p style="margin:0 0 16px 0">
    L'offre est valide jusqu'au <strong>{deadline}</strong>.
  </p>
  <p style="margin:24px 0 4px 0;color:#555;font-size:12px">
    {BUYER_ENTITY_NAME} &middot; immohorizon.com
  </p>
</div>
"""


async def _ensure_offer(db: AsyncSession, offer_id: int) -> Offer:
    offer = (
        await db.execute(select(Offer).where(Offer.id == offer_id))
    ).scalar_one_or_none()
    if offer is None:
        raise OfferSendError(f"Offre {offer_id} introuvable.")
    return offer


async def _load_deal(db: AsyncSession, deal_id: int) -> Optional[ProspectionDeal]:
    return (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()


async def send_offer_to_seller(
    db: AsyncSession, offer_id: int
) -> Offer:
    """Envoie l'offre au vendeur — utilise `offer.vendeur_email`.

    - Génère un signature_token si absent
    - Génère le PDF
    - Envoie via Graph
    - Met status=envoye et sent_at=now()
    """
    offer = await _ensure_offer(db, offer_id)
    if not offer.vendeur_email:
        raise OfferSendError("Adresse courriel du vendeur manquante.")
    if not offer.signature_token:
        offer.signature_token = secrets.token_urlsafe(32)
        await db.flush()

    mailer = get_mailer()
    if not mailer.ready:
        raise OfferSendError(
            "Microsoft Graph mailer non configuré (AZURE_* / MAIL_FROM_EMAIL)."
        )

    deal = await _load_deal(db, offer.deal_id)
    pdf_bytes = await render_offer_pdf(db, offer.id)
    attachment = EmailAttachment(
        name=f"offre-achat-{offer.id}.pdf",
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )

    subject_addr = deal.address if deal else "votre propriété"
    subject = f"Offre d'achat pour {subject_addr}"
    body = _seller_body(offer, deal)

    try:
        await mailer.send(
            to=[offer.vendeur_email],
            subject=subject,
            html_body=body,
            reply_to=mailer.sender,
            attachments=[attachment],
        )
    except Exception as exc:
        log.exception("Graph send failed for offer %s", offer.id)
        raise OfferSendError(f"Envoi courriel échoué: {exc}") from exc

    offer.status = OfferStatus.ENVOYE.value
    offer.sent_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(offer)
    return offer
