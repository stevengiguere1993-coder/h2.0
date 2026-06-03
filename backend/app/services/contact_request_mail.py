"""Accusé de réception automatique pour les leads construction.

Quand un prospect envoie une demande de soumission via le formulaire
public, on lui confirme tout de suite la réception et on annonce qu'un
membre de l'équipe le rappellera bientôt (en attendant la prise de
rendez-vous automatique une fois les calendriers branchés).

Best-effort : un échec d'envoi ne doit jamais faire planter la
soumission du formulaire.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.integrations.email_graph import get_mailer
from app.models.contact_request import ContactRequest

log = logging.getLogger(__name__)


def _body(name: str, locale: str) -> tuple[str, str]:
    """Retourne (sujet, html) selon la langue du prospect."""
    brand = settings.mail_from_name
    first = (name or "").strip().split(" ")[0] or name or ""
    if locale == "en":
        subject = f"We received your request — {brand}"
        html = f"""
        <div style="font-family:system-ui,Segoe UI,Arial,sans-serif;color:#0f172a">
          <p>Hello {first},</p>
          <p>Thank you — we have received your quote request. A member of
             our team will <strong>call you shortly</strong> to discuss
             your project.</p>
          <p>If it's easier, simply reply to this email.</p>
          <p style="margin-top:18px;color:#64748b;font-size:13px">
             {brand}<br>info@immohorizon.com</p>
        </div>
        """
    else:
        subject = f"Nous avons bien reçu votre demande — {brand}"
        html = f"""
        <div style="font-family:system-ui,Segoe UI,Arial,sans-serif;color:#0f172a">
          <p>Bonjour {first},</p>
          <p>Merci — nous avons bien reçu votre demande de soumission. Un
             membre de notre équipe vous <strong>téléphonera sous
             peu</strong> pour discuter de votre projet.</p>
          <p>Au besoin, vous pouvez simplement répondre à ce courriel.</p>
          <p style="margin-top:18px;color:#64748b;font-size:13px">
             {brand}<br>info@immohorizon.com</p>
        </div>
        """
    return subject, html


async def send_contact_acknowledgment(record: ContactRequest) -> bool:
    """Envoie l'accusé de réception au prospect. True si envoyé."""
    mailer = get_mailer()
    if not mailer.ready or not record.email:
        return False
    subject, html = _body(record.name or "", record.locale or "fr")
    try:
        await mailer.send(
            to=[record.email],
            subject=subject,
            html_body=html,
        )
        return True
    except Exception as exc:  # pragma: no cover - best-effort
        log.warning(
            "Accusé de réception lead échoué (cr=%s): %s", record.id, exc
        )
        return False
