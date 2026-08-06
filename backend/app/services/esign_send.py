"""eSign — envoi des courriels (invitations, relances, PDF final).

Pattern calqué sur `nda_send.py` : Microsoft Graph via `get_mailer()`,
lien public opaque `{public_base()}/esign/{token}`, erreurs converties
en `EsignSendError` pour que les endpoints renvoient un 502 explicite.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.esign import EsignDocument, EsignSigner
from app.services.public_links import public_base

log = logging.getLogger(__name__)


class EsignSendError(Exception):
    pass


def _full_name(s: EsignSigner) -> str:
    return f"{(s.first_name or '').strip()} {(s.last_name or '').strip()}".strip()


def ensure_token(signer: EsignSigner) -> None:
    if not signer.signature_token:
        signer.signature_token = secrets.token_urlsafe(32)


def signers_to_invite(
    doc: EsignDocument, signers: Sequence[EsignSigner]
) -> list[EsignSigner]:
    """Signataires à inviter MAINTENANT.

    - Mode parallèle : tous ceux qui n'ont pas encore signé/refusé.
    - Mode séquentiel : uniquement ceux du plus petit `order_index`
      encore en attente (plusieurs signataires peuvent partager un
      même rang).
    """
    pending = [s for s in signers if not s.signed_at and not s.declined_at]
    if not pending:
        return []
    if not doc.use_signing_order:
        return pending
    next_rank = min(s.order_index for s in pending)
    return [s for s in pending if s.order_index == next_rank]


def _invitation_body(
    doc: EsignDocument,
    signer: EsignSigner,
    entreprise_name: Optional[str],
    reminder: bool,
) -> str:
    sign_url = f"{public_base()}/esign/{signer.signature_token}"
    salutation = f"Bonjour {_full_name(signer) or ''},".replace(" ,", ",")
    intro = (
        "Petit rappel : un document attend toujours votre signature."
        if reminder
        else "Un document attend votre signature électronique."
    )
    ent_line = (
        f"<p style=\"margin:0 0 16px 0\">Émis pour : "
        f"<strong>{entreprise_name}</strong></p>"
        if entreprise_name
        else ""
    )
    message_html = (
        f"<p style=\"margin:0 0 16px 0;white-space:pre-line\">"
        f"{doc.message}</p>"
        if (doc.message or "").strip()
        else ""
    )
    sms_note = (
        "<p style=\"margin:0 0 16px 0;font-size:13px;color:#555\">"
        "Pour des raisons de sécurité, un code de validation vous sera "
        "envoyé par SMS avant la signature.</p>"
        if signer.require_sms_auth
        else ""
    )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.55;max-width:620px">
  <p style="margin:0 0 16px 0">{salutation}</p>
  <p style="margin:0 0 16px 0">{intro}</p>
  <p style="margin:0 0 16px 0">Document : <strong>{doc.title}</strong></p>
  {ent_line}
  {message_html}
  <p style="margin:20px 0 6px 0">
    <a href="{sign_url}"
       style="display:inline-block;background:#1d4ed8;color:#fff;
              padding:14px 24px;border-radius:8px;font-weight:bold;
              text-decoration:none">Consulter et signer le document</a>
  </p>
  <p style="margin:8px 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {sign_url}
  </p>
  {sms_note}
  <p style="margin:24px 0 4px 0;color:#555;font-size:12px">
    Horizon Services Immobiliers &middot; immohorizon.com
  </p>
</div>
"""


async def send_signer_invitation(
    db: AsyncSession,
    doc: EsignDocument,
    signer: EsignSigner,
    entreprise_name: Optional[str] = None,
    reminder: bool = False,
) -> None:
    """Envoie (ou relance) l'invitation à UN signataire."""
    if not signer.email:
        raise EsignSendError(f"Signataire {signer.id} sans courriel.")
    ensure_token(signer)
    await db.flush()

    mailer = get_mailer()
    if not mailer.ready:
        raise EsignSendError(
            "Microsoft Graph mailer non configuré (AZURE_* / MAIL_FROM_EMAIL)."
        )

    subject = (
        f"Rappel — signature requise : {doc.title}"
        if reminder
        else f"Signature requise : {doc.title}"
    )
    try:
        await mailer.send(
            to=[signer.email],
            subject=subject,
            html_body=_invitation_body(doc, signer, entreprise_name, reminder),
            reply_to=mailer.sender,
        )
    except Exception as exc:
        log.exception(
            "eSign : envoi invitation échoué (doc %s, signataire %s)",
            doc.id, signer.id,
        )
        raise EsignSendError(f"Envoi courriel échoué : {exc}") from exc

    signer.sent_at = datetime.now(timezone.utc)
    await db.flush()


def _completion_body(doc: EsignDocument, recipient_name: str) -> str:
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.55;max-width:620px">
  <p style="margin:0 0 16px 0">Bonjour {recipient_name},</p>
  <p style="margin:0 0 16px 0">
    Le document <strong>{doc.title}</strong> a été signé par toutes
    les parties. Vous trouverez en pièce jointe la version finale,
    accompagnée du certificat de signature (horodatages, adresses IP
    et empreinte d'intégrité).
  </p>
  <p style="margin:24px 0 4px 0;color:#555;font-size:12px">
    Horizon Services Immobiliers &middot; immohorizon.com
  </p>
</div>
"""


async def send_completion_emails(
    doc: EsignDocument,
    signers: Sequence[EsignSigner],
    final_pdf: bytes,
    filename: str,
    extra_recipients: Sequence[str] = (),
) -> None:
    """Envoie le PDF final à tous les signataires (+ destinataires
    internes). Best-effort PAR destinataire : un courriel qui échoue
    n'empêche pas les autres."""
    mailer = get_mailer()
    if not mailer.ready:
        log.warning("eSign : mailer non configuré — PDF final non envoyé.")
        return

    attachment = EmailAttachment(
        name=filename,
        content_bytes=final_pdf,
        content_type="application/pdf",
    )
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    for s in signers:
        email = (s.email or "").strip().lower()
        if email and email not in seen:
            seen.add(email)
            targets.append((email, _full_name(s) or "—"))
    for email in extra_recipients:
        e = (email or "").strip().lower()
        if e and e not in seen:
            seen.add(e)
            targets.append((e, "—"))

    for email, name in targets:
        try:
            await mailer.send(
                to=[email],
                subject=f"Document signé : {doc.title}",
                html_body=_completion_body(doc, name),
                reply_to=mailer.sender,
                attachments=[attachment],
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "eSign : envoi PDF final échoué (doc %s → %s)",
                doc.id, email,
            )
