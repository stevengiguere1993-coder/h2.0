"""Envoi par email d'une soumission devis_dev au client.

Pattern calqué sur ``app.services.offer_send`` :

- Génère un ``signature_token`` opaque si absent
- Rend le PDF (vue client uniquement)
- Envoie via Graph un email court au client avec le lien public
  ``/devlog/sign-soumission/{token}`` et le PDF en pièce jointe
- Best-effort : si Graph échoue, on log un warning, on ne fait pas
  échouer l'opération côté caller (à l'inverse de l'offre d'achat,
  où le mail est plus critique)
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
from app.models.devlog_client import DevlogClient
from app.models.devlog_soumission import DevlogSoumission
from app.services.devlog_soumission_pdf import (
    BUYER_ENTITY_NAME,
    generate_devis_pdf,
)


log = logging.getLogger(__name__)


def _public_base() -> str:
    return (
        os.getenv("PUBLIC_SITE_URL") or "https://immohorizon.com"
    ).rstrip("/")


class DevlogSoumissionSendError(Exception):
    pass


async def _load_client(
    db: AsyncSession, client_id: Optional[int]
) -> Optional[DevlogClient]:
    if client_id is None:
        return None
    return (
        await db.execute(
            select(DevlogClient).where(DevlogClient.id == client_id)
        )
    ).scalar_one_or_none()


def _client_body(
    soumission: DevlogSoumission,
    client: Optional[DevlogClient],
    sign_url: str,
) -> str:
    """Email court et engageant au client."""
    salutation = (
        f"Bonjour {client.name},"
        if client is not None and client.name
        else "Bonjour,"
    )
    project_label = soumission.title or "votre projet"
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.55;max-width:620px">
  <p style="margin:0 0 16px 0">{salutation}</p>
  <p style="margin:0 0 16px 0">
    L'équipe Développement logiciel de <strong>{BUYER_ENTITY_NAME}</strong>
    vous transmet la soumission pour <em>{project_label}</em>.
  </p>
  <p style="margin:0 0 16px 0">
    Vous pouvez la consulter en détail (deux sections — frais
    mensuels récurrents et investissement initial), télécharger le PDF
    et la signer électroniquement (ou la refuser) en cliquant sur le
    bouton ci-dessous.
  </p>
  <p style="margin:20px 0 6px 0">
    <a href="{sign_url}"
       style="display:inline-block;background:#1e40af;color:#fff;
              padding:14px 24px;border-radius:8px;font-weight:bold;
              text-decoration:none">Consulter et signer la soumission</a>
  </p>
  <p style="margin:8px 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {sign_url}
  </p>
  <p style="margin:0 0 16px 0">
    Une copie PDF est également jointe à ce courriel.
  </p>
  <p style="margin:24px 0 4px 0;color:#555;font-size:12px">
    {BUYER_ENTITY_NAME} &middot; Pôle Développement logiciel &middot;
    immohorizon.com
  </p>
</div>
"""


async def send_devis_email(
    db: AsyncSession, soumission_id: int
) -> DevlogSoumission:
    """Envoi de la soumission devis_dev au client.

    - Vérifie que la soumission est en mode ``is_devis_dev``
    - Vérifie que le statut autorise l'envoi (``brouillon`` ou
      ``envoyee`` — renvoi possible si le client a perdu l'email)
    - Génère / réutilise le ``signature_token``
    - Génère le PDF
    - Envoie via Graph (best-effort)
    - Passe ``status=envoyee`` et ``sent_at=now()``
    """
    soumission = (
        await db.execute(
            select(DevlogSoumission).where(DevlogSoumission.id == soumission_id)
        )
    ).scalar_one_or_none()
    if soumission is None:
        raise DevlogSoumissionSendError(
            f"Soumission {soumission_id} introuvable."
        )
    if not getattr(soumission, "is_devis_dev", False):
        raise DevlogSoumissionSendError(
            "Seules les soumissions au nouveau format devis_dev "
            "peuvent être envoyées par ce flow."
        )
    if soumission.status not in ("brouillon", "envoyee"):
        raise DevlogSoumissionSendError(
            f"Soumission au statut « {soumission.status} » — "
            "envoi impossible."
        )

    client = await _load_client(db, soumission.client_id)
    if client is None or not (client.email or "").strip():
        raise DevlogSoumissionSendError(
            "Adresse courriel du client manquante — impossible "
            "d'envoyer la soumission."
        )

    if not getattr(soumission, "signature_token", None):
        soumission.signature_token = secrets.token_urlsafe(32)
        await db.flush()

    pdf_bytes = await generate_devis_pdf(db, soumission_id)
    attachment = EmailAttachment(
        name=f"soumission-devlog-{soumission.id}.pdf",
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )

    sign_url = (
        f"{_public_base()}/devlog/sign-soumission/{soumission.signature_token}"
    )
    subject = "Soumission de développement — Horizon Services Immobiliers"
    body = _client_body(soumission, client, sign_url)

    mailer = get_mailer()
    if mailer.ready:
        try:
            await mailer.send(
                to=[client.email],
                subject=subject,
                html_body=body,
                reply_to=mailer.sender,
                attachments=[attachment],
            )
        except Exception as exc:  # best-effort
            log.warning(
                "Graph send failed for devlog soumission %s: %s",
                soumission.id,
                exc,
            )
    else:
        log.warning(
            "Graph mailer non configuré — soumission %s marquée "
            "comme envoyée sans courriel.",
            soumission.id,
        )

    soumission.status = "envoyee"
    soumission.sent_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(soumission)
    return soumission
