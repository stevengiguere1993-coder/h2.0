"""Envoi d'un bail au locataire pour signature électronique.

Mirroir léger de `bon_send` : génère un token, envoie un courriel avec un
lien public `/bail/{token}` où le locataire consulte et signe. Pas de PDF
pour l'instant (la page publique affiche les conditions essentielles).
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import get_mailer
from app.models.immobilier import Bail, Locataire

log = logging.getLogger(__name__)


def _public_base() -> str:
    return (os.getenv("PUBLIC_SITE_URL") or "https://immohorizon.com").rstrip("/")


class BailSendError(Exception):
    pass


def _body_html(bail: Bail, locataire_name: str, url: str) -> str:
    first = (locataire_name or "").strip().split(" ")[0] or "Bonjour"
    loyer = f"{float(bail.loyer_mensuel):,.2f} $".replace(",", " ")
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p>Bonjour {first},</p>
  <p>Votre bail est prêt à être signé en ligne. Loyer mensuel :
     <strong>{loyer}</strong> · du <strong>{bail.date_debut}</strong> au
     <strong>{bail.date_fin}</strong>.</p>
  <p style="margin:20px 0 6px 0">
    <a href="{url}" style="display:inline-block;background:#d89b3c;color:#111;
       padding:12px 20px;border-radius:8px;font-weight:bold;
       text-decoration:none">Consulter et signer mon bail</a>
  </p>
  <p style="margin:0 0 16px 0;font-size:12px;color:#555">Ou copiez ce lien : {url}</p>
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>info@immohorizon.com
  </p>
</div>
"""


async def send_bail_for_signature(
    db: AsyncSession,
    bail_id: int,
    *,
    to: Optional[Iterable[str]] = None,
) -> Bail:
    mailer = get_mailer()
    if not mailer.ready:
        raise BailSendError("Mailer non configuré (AZURE_* / MAIL_FROM_EMAIL).")

    bail = (
        await db.execute(select(Bail).where(Bail.id == bail_id))
    ).scalar_one_or_none()
    if bail is None:
        raise BailSendError(f"Bail {bail_id} introuvable.")

    locataire = await db.get(Locataire, bail.locataire_id)
    loc_name = locataire.full_name if locataire else ""
    recipients = [a.strip() for a in (to or []) if a and a.strip()]
    if not recipients and locataire and locataire.email:
        recipients = [locataire.email.strip()]
    if not recipients:
        raise BailSendError(
            "Aucun courriel destinataire (ajoute un courriel au locataire)."
        )

    if not bail.signature_token:
        bail.signature_token = secrets.token_urlsafe(32)
        await db.flush()
    url = f"{_public_base()}/bail/{bail.signature_token}"

    try:
        await mailer.send(
            to=recipients,
            subject="Votre bail à signer — Horizon Services Immobiliers",
            html_body=_body_html(bail, loc_name, url),
            reply_to=mailer.sender,
        )
    except Exception as exc:  # pragma: no cover - réseau
        log.exception("Envoi bail %s échoué", bail_id)
        raise BailSendError(f"Envoi courriel échoué : {exc}") from exc

    bail.sent_at = datetime.now(timezone.utc)
    bail.sent_to_email = recipients[0]
    await db.flush()
    await db.refresh(bail)
    return bail
