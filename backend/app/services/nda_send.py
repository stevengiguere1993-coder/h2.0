"""Envoi par email d'un NDA à un investisseur via Microsoft Graph.

Pattern strictement calqué sur `offer_send.py` :
- Génère un token de signature opaque si absent
- Rend le PDF
- Envoie un email court à l'investisseur avec lien public + PDF
  en pièce jointe
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
from app.models.nda import NDA, NDAStatus
from app.models.prospection_deal import ProspectionDeal
from app.services.nda_pdf import render_nda_pdf
from app.services.nda_template import ISSUER_ENTITY_NAME


log = logging.getLogger(__name__)


def _public_base() -> str:
    return (
        os.getenv("PUBLIC_SITE_URL") or "https://immohorizon.com"
    ).rstrip("/")


class NDASendError(Exception):
    pass


def _investor_body(nda: NDA, deal: Optional[ProspectionDeal]) -> str:
    """Email court et direct à l'investisseur."""
    sign_url = f"{_public_base()}/sign-nda/{nda.signature_token}"
    salutation = (
        f"Bonjour {nda.investor_name},"
        if nda.investor_name and nda.investor_name.strip()
        else "Bonjour,"
    )
    address = deal.address if deal else "une propriété"
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.55;max-width:620px">
  <p style="margin:0 0 16px 0">{salutation}</p>
  <p style="margin:0 0 16px 0">
    <strong>{ISSUER_ENTITY_NAME}</strong> souhaite vous transmettre
    des informations confidentielles concernant une opportunité
    d'investissement immobilier située au <em>{address}</em>.
  </p>
  <p style="margin:0 0 16px 0">
    Avant de partager les détails financiers de l'opportunité, nous
    avons besoin que vous signiez la présente entente de
    confidentialité (NDA). Cela ne prend que quelques secondes.
  </p>
  <p style="margin:20px 0 6px 0">
    <a href="{sign_url}"
       style="display:inline-block;background:#1d4ed8;color:#fff;
              padding:14px 24px;border-radius:8px;font-weight:bold;
              text-decoration:none">Consulter et signer l'entente</a>
  </p>
  <p style="margin:8px 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {sign_url}
  </p>
  <p style="margin:0 0 16px 0">
    Une copie complète de l'entente est également jointe à ce
    courriel en format PDF.
  </p>
  <p style="margin:24px 0 4px 0;color:#555;font-size:12px">
    {ISSUER_ENTITY_NAME} &middot; immohorizon.com
  </p>
</div>
"""


async def _ensure_nda(db: AsyncSession, nda_id: int) -> NDA:
    nda = (
        await db.execute(select(NDA).where(NDA.id == nda_id))
    ).scalar_one_or_none()
    if nda is None:
        raise NDASendError(f"NDA {nda_id} introuvable.")
    return nda


async def _load_deal(
    db: AsyncSession, deal_id: int
) -> Optional[ProspectionDeal]:
    return (
        await db.execute(
            select(ProspectionDeal).where(ProspectionDeal.id == deal_id)
        )
    ).scalar_one_or_none()


async def send_nda_to_investor(db: AsyncSession, nda_id: int) -> NDA:
    """Envoie l'entente à l'investisseur — utilise `nda.investor_email`.

    - Génère un signature_token si absent
    - Génère le PDF
    - Envoie via Graph
    - Met status=envoye et sent_at=now()
    """
    nda = await _ensure_nda(db, nda_id)
    if not nda.investor_email:
        raise NDASendError("Adresse courriel de l'investisseur manquante.")
    if not nda.signature_token:
        nda.signature_token = secrets.token_urlsafe(32)
        await db.flush()

    mailer = get_mailer()
    if not mailer.ready:
        raise NDASendError(
            "Microsoft Graph mailer non configuré (AZURE_* / MAIL_FROM_EMAIL)."
        )

    deal = await _load_deal(db, nda.deal_id)
    pdf_bytes = await render_nda_pdf(db, nda.id)
    attachment = EmailAttachment(
        name=f"entente-confidentialite-{nda.id}.pdf",
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )

    subject_addr = deal.address if deal else "une opportunité"
    subject = f"Entente de confidentialité — {subject_addr}"
    body = _investor_body(nda, deal)

    try:
        await mailer.send(
            to=[nda.investor_email],
            subject=subject,
            html_body=body,
            reply_to=mailer.sender,
            attachments=[attachment],
        )
    except Exception as exc:
        log.exception("Graph send failed for NDA %s", nda.id)
        raise NDASendError(f"Envoi courriel échoué: {exc}") from exc

    nda.status = NDAStatus.ENVOYE.value
    nda.sent_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(nda)
    return nda
