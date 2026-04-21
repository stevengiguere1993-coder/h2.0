"""Send a Soumission to a client: generate PDF + email via Microsoft Graph."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.soumission import Soumission, SoumissionStatus
from app.services.soumission_pdf import render_soumission_pdf

log = logging.getLogger(__name__)


class SoumissionSendError(Exception):
    pass


def _default_subject(sm: Soumission) -> str:
    ref = sm.reference or ""
    title = sm.title or "Soumission"
    return f"Soumission {ref} — {title}".strip(" —")


def _default_body_html(sm: Soumission, intro: Optional[str]) -> str:
    intro_html = ""
    if intro:
        safe = intro.replace("\n", "<br>")
        intro_html = f"<p style=\"margin:0 0 16px 0\">{safe}</p>"
    total_line = ""
    if sm.total is not None:
        total_line = (
            f"<p style=\"margin:0 0 8px 0\"><strong>Total :</strong> "
            f"{float(sm.total):,.2f} $ CAD</p>".replace(",", " ")
        )
    valid_line = ""
    if sm.valid_until:
        valid_line = (
            f"<p style=\"margin:0 0 8px 0\"><strong>Valide jusqu'au :</strong> "
            f"{sm.valid_until.date().isoformat()}</p>"
        )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p style="margin:0 0 16px 0">Bonjour,</p>
  {intro_html}
  <p style="margin:0 0 16px 0">
    Vous trouverez ci-joint la soumission
    <strong>{sm.reference}</strong> —
    <em>{sm.title}</em>.
  </p>
  {total_line}
  {valid_line}
  <p style="margin:16px 0 0 0">
    N'hésitez pas à me contacter pour toute question ou pour confirmer votre
    accord.
  </p>
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>
    RBQ 5868-5991-01<br>
    info@immohorizon.com &middot; immohorizon.com
  </p>
</div>
"""


async def send_soumission(
    db: AsyncSession,
    soumission_id: int,
    *,
    to: Iterable[str],
    cc: Optional[Iterable[str]] = None,
    subject: Optional[str] = None,
    message: Optional[str] = None,
) -> Soumission:
    mailer = get_mailer()
    if not mailer.ready:
        raise SoumissionSendError(
            "Microsoft Graph mailer is not configured (AZURE_* / MAIL_FROM_EMAIL)."
        )

    rendered = await render_soumission_pdf(db, soumission_id)
    if rendered is None:
        raise SoumissionSendError(f"Soumission {soumission_id} introuvable.")
    sm, pdf_bytes = rendered

    recipients = [a.strip() for a in to if a and a.strip()]
    if not recipients:
        raise SoumissionSendError("Au moins un destinataire est requis.")

    cc_list = [a.strip() for a in (cc or []) if a and a.strip()]
    subj = subject or _default_subject(sm)
    body_html = _default_body_html(sm, message)
    attachment = EmailAttachment(
        name=f"soumission-{sm.reference}.pdf",
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
        log.exception("Graph send failed for soumission %s", soumission_id)
        raise SoumissionSendError(f"Envoi courriel échoué: {exc}") from exc

    sm.status = SoumissionStatus.SENT.value
    sm.sent_at = datetime.now(timezone.utc)

    # Propagate to the linked prospect in the CRM: the soumission has
    # been delivered so the prospect is at "quoted" stage. If the
    # prospect was in a later stage by mistake, this brings it back
    # in line with the soumission workflow.
    if sm.contact_request_id:
        cr = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == sm.contact_request_id
                )
            )
        ).scalar_one_or_none()
        if cr is not None:
            cr.status = ContactRequestStatus.QUOTED.value

    await db.flush()
    await db.refresh(sm)
    return sm
