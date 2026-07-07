"""Send a BonTravail to a client: PDF + email (Microsoft Graph) with
a public signature link."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.bon_travail import BonTravail, BonTravailStatus
from app.services.bon_pdf import render_bon_pdf

log = logging.getLogger(__name__)


def _public_base() -> str:
    return (os.getenv("PUBLIC_SITE_URL") or "https://immohorizon.com").rstrip("/")


class BonSendError(Exception):
    pass


def _default_subject(bon: BonTravail) -> str:
    ref = bon.reference or ""
    title = bon.title or "Bon de travail"
    return f"Bon de travail {ref} — {title}".strip(" —")


def _default_body_html(bon: BonTravail, intro: Optional[str]) -> str:
    intro_html = ""
    if intro:
        safe = intro.replace("\n", "<br>")
        intro_html = f"<p style=\"margin:0 0 16px 0\">{safe}</p>"
    amount_line = ""
    if bon.amount is not None:
        amount_line = (
            f"<p style=\"margin:0 0 8px 0\"><strong>Montant :</strong> "
            f"{float(bon.amount):,.2f} $ CAD</p>".replace(",", " ")
        )
    sign_block = ""
    if bon.signature_token:
        url = f"{_public_base()}/bon/{bon.signature_token}"
        sign_block = f"""\
  <p style="margin:20px 0 6px 0">
    <a href="{url}"
       style="display:inline-block;background:#d89b3c;color:#111;
              padding:12px 20px;border-radius:8px;font-weight:bold;
              text-decoration:none">Voir et signer en ligne</a>
  </p>
  <p style="margin:0 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {url}
  </p>"""
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p style="margin:0 0 16px 0">Bonjour,</p>
  {intro_html}
  <p style="margin:0 0 16px 0">
    Vous trouverez ci-joint le bon de travail
    <strong>{bon.reference}</strong> — <em>{bon.title}</em>.
  </p>
  {amount_line}
  {sign_block}
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>
    RBQ 5868-5991-01<br>
    info@immohorizon.com
  </p>
</div>
"""


async def send_bon(
    db: AsyncSession,
    bon_id: int,
    *,
    to: Iterable[str],
    cc: Optional[Iterable[str]] = None,
    subject: Optional[str] = None,
    message: Optional[str] = None,
) -> BonTravail:
    mailer = get_mailer()
    if not mailer.ready:
        raise BonSendError(
            "Microsoft Graph mailer is not configured (AZURE_* / MAIL_FROM_EMAIL)."
        )

    # Ensure token
    bon = (
        await db.execute(select(BonTravail).where(BonTravail.id == bon_id))
    ).scalar_one_or_none()
    if bon is None:
        raise BonSendError(f"Bon {bon_id} introuvable.")
    if not bon.signature_token:
        bon.signature_token = secrets.token_urlsafe(32)
        await db.flush()

    rendered = await render_bon_pdf(db, bon_id)
    if rendered is None:
        raise BonSendError(f"Bon {bon_id} introuvable.")
    bon, pdf_bytes = rendered

    recipients = [a.strip() for a in to if a and a.strip()]
    if not recipients:
        raise BonSendError("Au moins un destinataire est requis.")
    cc_list = [a.strip() for a in (cc or []) if a and a.strip()]

    attachment = EmailAttachment(
        name=f"bon-{bon.reference}.pdf",
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )

    try:
        await mailer.send(
            to=recipients,
            subject=subject or _default_subject(bon),
            html_body=_default_body_html(bon, message),
            cc=cc_list or None,
            reply_to=mailer.sender,
            attachments=[attachment],
        )
    except Exception as exc:
        log.exception("Graph send failed for bon %s", bon_id)
        raise BonSendError(f"Envoi courriel échoué: {exc}") from exc

    # Garde d'état : on ne (re)bascule en SENT que depuis un état
    # « ouvert » (brouillon / déjà envoyé). Renvoyer un bon déjà SIGNÉ,
    # annulé ou avancé dans son cycle interne (planifié, à refacturer,
    # facturé) n'écrase PAS son statut — sinon on ferait régresser le bon
    # dans son flux. Le courriel part toujours ; on garde le dernier
    # destinataire à jour uniquement quand on met aussi à jour le statut.
    if bon.status in (
        BonTravailStatus.DRAFT.value,
        BonTravailStatus.SENT.value,
    ):
        bon.status = BonTravailStatus.SENT.value
        bon.sent_at = datetime.now(timezone.utc)
        bon.sent_to_email = recipients[0]
        await db.flush()
    await db.refresh(bon)
    return bon
