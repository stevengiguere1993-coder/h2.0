"""Envoi par courriel d'un contrat de gestion au Mandant (Microsoft Graph).

Patron calqué sur `nda_send` : génère un token si absent, rend le PDF,
envoie un courriel court avec lien public + PDF en pièce jointe, puis
passe le statut à « envoyé ».
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.contrat_gestion import ContratGestion, ContratGestionStatus
from app.services.contrat_gestion_pdf import (
    contrat_pdf_filename,
    render_contrat_pdf,
)
from app.services.contrat_gestion_service import resolve_body_markdown
from app.services.contrat_gestion_template import MANDATAIRE_NOM
from app.services.public_links import public_base

log = logging.getLogger(__name__)


class ContratGestionSendError(Exception):
    pass


def _body_html(contrat: ContratGestion, sign_url: str) -> str:
    salutation = (
        f"Bonjour {contrat.representant_nom},"
        if (contrat.representant_nom or "").strip()
        else "Bonjour,"
    )
    compagnie = (contrat.compagnie or "").strip()
    ref_compagnie = f" pour <strong>{compagnie}</strong>" if compagnie else ""
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.55;max-width:620px">
  <p style="margin:0 0 16px 0">{salutation}</p>
  <p style="margin:0 0 16px 0">
    <strong>{MANDATAIRE_NOM}</strong> vous transmet la
    <strong>convention de gestion immobilière</strong>{ref_compagnie}
    pour signature électronique. La signature ne prend que quelques
    instants.
  </p>
  <p style="margin:20px 0 6px 0">
    <a href="{sign_url}"
       style="display:inline-block;background:#0f766e;color:#fff;
              padding:14px 24px;border-radius:8px;font-weight:bold;
              text-decoration:none">Consulter et signer la convention</a>
  </p>
  <p style="margin:8px 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {sign_url}
  </p>
  <p style="margin:0 0 16px 0">
    Une copie complète de la convention est également jointe à ce
    courriel en format PDF.
  </p>
  <p style="margin:24px 0 4px 0;color:#555;font-size:12px">
    {MANDATAIRE_NOM} &middot; immohorizon.com
  </p>
</div>
"""


async def _ensure(db: AsyncSession, contrat_id: int) -> ContratGestion:
    contrat = (
        await db.execute(
            select(ContratGestion).where(ContratGestion.id == contrat_id)
        )
    ).scalar_one_or_none()
    if contrat is None:
        raise ContratGestionSendError(f"Contrat {contrat_id} introuvable.")
    return contrat


async def send_contrat_gestion(db: AsyncSession, contrat_id: int) -> ContratGestion:
    """Envoie la convention au Mandant. Génère token + PDF, statut=envoyé."""
    contrat = await _ensure(db, contrat_id)
    if not (contrat.mandant_courriel or "").strip():
        raise ContratGestionSendError("Courriel du Mandant manquant.")
    if not contrat.signature_token:
        contrat.signature_token = secrets.token_urlsafe(32)
        await db.flush()

    mailer = get_mailer()
    if not mailer.ready:
        raise ContratGestionSendError(
            "Microsoft Graph mailer non configuré (AZURE_* / MAIL_FROM_EMAIL)."
        )

    body_md = await resolve_body_markdown(db, contrat)
    try:
        pdf_bytes = render_contrat_pdf(contrat, body_md)
    except Exception as exc:
        log.exception("Rendu PDF échoué pour contrat de gestion %s", contrat.id)
        raise ContratGestionSendError(
            f"Rendu du PDF de la convention échoué : {exc}"
        ) from exc

    attachment = EmailAttachment(
        name=contrat_pdf_filename(contrat),
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )
    sign_url = f"{public_base()}/sign-contrat-gestion/{contrat.signature_token}"
    subject = f"Convention de gestion immobilière — {MANDATAIRE_NOM}"

    try:
        await mailer.send(
            to=[contrat.mandant_courriel],
            subject=subject,
            html_body=_body_html(contrat, sign_url),
            reply_to=mailer.sender,
            attachments=[attachment],
        )
    except Exception as exc:
        log.exception("Graph send failed for contrat de gestion %s", contrat.id)
        raise ContratGestionSendError(f"Envoi courriel échoué: {exc}") from exc

    contrat.status = ContratGestionStatus.ENVOYE.value
    contrat.sent_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(contrat)
    return contrat
