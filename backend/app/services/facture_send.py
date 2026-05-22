"""Send a Facture to a client: generate PDF + email via Microsoft Graph."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.facture import Facture, FactureStatus
from app.services.facture_pdf import render_facture_pdf

log = logging.getLogger(__name__)


class FactureSendError(Exception):
    pass


def _public_base() -> str:
    return (
        os.getenv("PUBLIC_SITE_URL") or "https://immohorizon.com"
    ).rstrip("/")


def _default_subject(fa: Facture) -> str:
    ref = fa.reference or ""
    return f"Facture {ref} — Horizon Services Immobiliers".strip(" —")


def _default_body_html(fa: Facture, intro: Optional[str]) -> str:
    intro_html = ""
    if intro:
        safe = intro.replace("\n", "<br>")
        intro_html = f"<p style=\"margin:0 0 16px 0\">{safe}</p>"
    total_line = ""
    if fa.total is not None:
        total_line = (
            f"<p style=\"margin:0 0 8px 0\"><strong>Total :</strong> "
            f"{float(fa.total):,.2f} $ CAD</p>".replace(",", " ")
        )
    due_line = ""
    if fa.due_at:
        due_line = (
            f"<p style=\"margin:0 0 8px 0\"><strong>Échéance :</strong> "
            f"{fa.due_at.date().isoformat()}</p>"
        )
    # Facture finale : bloc d'invitation à signer en ligne.
    sign_block = ""
    if fa.is_final and fa.signature_token:
        sign_url = f"{_public_base()}/facture/{fa.signature_token}"
        sign_block = f"""\
  <p style="margin:8px 0 16px 0">
    Cette <strong>facture finale</strong> confirme l'achèvement des
    travaux de la soumission de base. Merci de la réviser et de la
    signer en ligne :
  </p>
  <p style="margin:0 0 6px 0">
    <a href="{sign_url}"
       style="display:inline-block;background:#d89b3c;color:#111;
              padding:12px 20px;border-radius:8px;font-weight:bold;
              text-decoration:none">Voir et signer la facture</a>
  </p>
  <p style="margin:0 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {sign_url}
  </p>"""
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p style="margin:0 0 16px 0">Bonjour,</p>
  {intro_html}
  <p style="margin:0 0 16px 0">
    Vous trouverez ci-joint la facture <strong>{fa.reference}</strong>.
  </p>
  {total_line}
  {due_line}
  {sign_block}
  <p style="margin:16px 0 0 0">
    Merci de confirmer la réception. Pour toute question, n'hésitez pas
    à nous joindre.
  </p>
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>
    RBQ 5868-5991-01<br>
    info@immohorizon.com &middot; immohorizon.com
  </p>
</div>
"""


async def send_facture(
    db: AsyncSession,
    facture_id: int,
    *,
    to: Iterable[str],
    cc: Optional[Iterable[str]] = None,
    subject: Optional[str] = None,
    message: Optional[str] = None,
    include_statement: bool = False,
) -> Facture:
    mailer = get_mailer()
    if not mailer.ready:
        raise FactureSendError(
            "Microsoft Graph mailer is not configured (AZURE_* / MAIL_FROM_EMAIL)."
        )

    rendered = await render_facture_pdf(
        db, facture_id, include_statement=include_statement,
    )
    if rendered is None:
        raise FactureSendError(f"Facture {facture_id} introuvable.")
    fa, pdf_bytes = rendered

    recipients = [a.strip() for a in to if a and a.strip()]
    if not recipients:
        raise FactureSendError("Au moins un destinataire est requis.")

    # Facture finale : jeton de signature généré au premier envoi
    # (jamais régénéré, pour ne pas invalider un lien déjà transmis).
    if fa.is_final and not fa.signature_token:
        fa.signature_token = secrets.token_urlsafe(32)
        await db.flush()

    cc_list = [a.strip() for a in (cc or []) if a and a.strip()]
    subj = subject or _default_subject(fa)
    body_html = _default_body_html(fa, message)
    attachment_name = (
        f"facture-{fa.reference}-avec-etat.pdf"
        if include_statement
        else f"facture-{fa.reference}.pdf"
    )
    attachment = EmailAttachment(
        name=attachment_name,
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )

    try:
        await mailer.send(
            to=recipients,
            subject=subj,
            html_body=body_html,
            cc=cc_list or None,
            reply_to=mailer.sender,
            attachments=[attachment],
        )
    except Exception as exc:
        log.exception("Graph send failed for facture %s", facture_id)
        raise FactureSendError(f"Envoi courriel échoué: {exc}") from exc

    fa.status = FactureStatus.SENT.value
    # « Émise le » = dernière fois où la facture a été envoyée au
    # client. On remet à jour à CHAQUE envoi (y compris les renvois)
    # pour que la date affichée soit la date réelle d'expédition.
    fa.issued_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(fa)
    return fa
