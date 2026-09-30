"""Envoi d'un AVENANT au client pour signature (PDF joint + lien public),
même mécanique que ``soumission_send`` (Microsoft Graph)."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.soumission import Soumission
from app.models.soumission_avenant import SoumissionAvenant
from app.services.avenant_pdf import (
    avenant_pdf_filename,
    load_avenant,
    montants_avenant,
    render_avenant_pdf,
)
from app.services.public_links import public_base

log = logging.getLogger(__name__)


class AvenantSendError(Exception):
    pass


def _money(n: float) -> str:
    return f"{n:,.2f} $ CAD".replace(",", " ")


def _body_html(av: SoumissionAvenant, sm: Soumission, montants: dict, intro: Optional[str]) -> str:
    intro_html = ""
    if intro:
        intro_html = f"<p style=\"margin:0 0 16px 0\">{intro.replace(chr(10), '<br>')}</p>"
    sign_url = f"{public_base()}/avenant/{av.signature_token}"
    impact = montants["impact"]
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p style="margin:0 0 16px 0">Bonjour,</p>
  {intro_html}
  <p style="margin:0 0 16px 0">
    Vous trouverez ci-joint l'avenant <strong>{av.reference}</strong> à votre
    soumission <strong>{sm.reference}</strong> — <em>{sm.title}</em>.
    {("<br>" + av.note.replace(chr(10), "<br>")) if av.note else ""}
  </p>
  <p style="margin:0 0 8px 0"><strong>Impact :</strong> {"+" if impact >= 0 else "−"}{_money(abs(impact))} (avant taxes)</p>
  <p style="margin:0 0 8px 0"><strong>Nouveau total du contrat :</strong> {_money(montants["total_apres"])} (taxes incluses)</p>
  <p style="margin:20px 0 6px 0">
    <a href="{sign_url}"
       style="display:inline-block;background:#d89b3c;color:#111;
              padding:12px 20px;border-radius:8px;font-weight:bold;
              text-decoration:none">Voir et signer l'avenant en ligne</a>
  </p>
  <p style="margin:0 0 16px 0;font-size:12px;color:#555">Ou copiez ce lien : {sign_url}</p>
  <p style="margin:16px 0 0 0">N'hésitez pas à me contacter pour toute question.</p>
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>RBQ 5868-5991-01<br>info@immohorizon.com &middot; immohorizon.com
  </p>
</div>
"""


async def send_avenant(
    db: AsyncSession,
    avenant_id: int,
    *,
    to: Iterable[str],
    cc: Optional[Iterable[str]] = None,
    message: Optional[str] = None,
) -> SoumissionAvenant:
    mailer = get_mailer()
    if not mailer.ready:
        raise AvenantSendError("Microsoft Graph mailer is not configured (AZURE_* / MAIL_FROM_EMAIL).")
    av = await load_avenant(db, avenant_id)
    if av is None:
        raise AvenantSendError(f"Avenant {avenant_id} introuvable.")
    if av.signature_status == "signe":
        raise AvenantSendError("Cet avenant est déjà signé par le client.")
    recipients = [a.strip() for a in to if a and a.strip()]
    if not recipients:
        raise AvenantSendError("Au moins un destinataire est requis.")
    # Jeton généré au premier envoi, jamais régénéré (un lien déjà
    # transmis reste valide).
    if not av.signature_token:
        av.signature_token = secrets.token_urlsafe(32)
        await db.flush()
    rendered = await render_avenant_pdf(db, avenant_id)
    if rendered is None:
        raise AvenantSendError("Soumission de l'avenant introuvable.")
    av, sm, pdf_bytes = rendered
    montants = await montants_avenant(db, av)
    cc_list = [a.strip() for a in (cc or []) if a and a.strip()]
    try:
        await mailer.send(
            to=recipients,
            subject=f"Avenant {av.reference} à votre soumission {sm.reference} — {sm.title}"[:255],
            html_body=_body_html(av, sm, montants, message),
            cc=cc_list or None,
            reply_to=mailer.sender,
            attachments=[EmailAttachment(
                name=avenant_pdf_filename(av, sm), content_bytes=pdf_bytes, content_type="application/pdf",
            )],
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Graph send failed for avenant %s", avenant_id)
        raise AvenantSendError(f"Envoi courriel échoué : {exc}") from exc
    av.signature_status = "envoye"
    av.sent_at = datetime.now(timezone.utc)
    av.sent_to = ", ".join(recipients)[:320]
    av.declined_at = None
    av.decline_reason = None
    await db.flush()
    return av
