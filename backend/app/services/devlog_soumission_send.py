"""Envoi par email d'une soumission devis_dev au client.

Pattern calqué sur ``app.services.offer_send`` :

- Génère un ``signature_token`` opaque si absent
- Envoie via Graph un email court au client avec le lien public
  ``/devlog/sign-soumission/{token}``. Pas de PDF en pièce jointe :
  le client doit cliquer sur le lien pour consulter / signer (le PDF
  reste téléchargeable depuis la page publique)
- Best-effort : si Graph échoue, on log un warning, on ne fait pas
  échouer l'opération côté caller (à l'inverse de l'offre d'achat,
  où le mail est plus critique)
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import get_mailer
from app.models.devlog_client import DevlogClient
from app.models.devlog_lead import DevlogLead
from app.models.devlog_soumission import DevlogSoumission
from app.services.devlog_soumission_pdf import BUYER_ENTITY_NAME
from app.services.public_links import public_base


log = logging.getLogger(__name__)


class DevlogSoumissionSendError(Exception):
    pass


@dataclass
class _Recipient:
    """Destinataire d'une soumission. Peut etre un client deja existant
    OU un prospect (lead) qui n'a pas encore ete converti — la conversion
    n'a lieu qu'a la signature publique."""

    name: Optional[str]
    email: Optional[str]


async def _load_recipient(
    db: AsyncSession, soumission: DevlogSoumission
) -> Optional[_Recipient]:
    """Charge le destinataire : priorite au client, fallback au lead."""
    if soumission.client_id is not None:
        client = (
            await db.execute(
                select(DevlogClient).where(
                    DevlogClient.id == soumission.client_id
                )
            )
        ).scalar_one_or_none()
        if client is not None:
            return _Recipient(name=client.name, email=client.email)
    if soumission.lead_id is not None:
        lead = (
            await db.execute(
                select(DevlogLead).where(DevlogLead.id == soumission.lead_id)
            )
        ).scalar_one_or_none()
        if lead is not None:
            return _Recipient(name=lead.name, email=lead.email)
    return None


def _client_body(
    soumission: DevlogSoumission,
    recipient: Optional[_Recipient],
    sign_url: str,
) -> str:
    """Email court et engageant au client (ou prospect)."""
    salutation = (
        f"Bonjour {recipient.name},"
        if recipient is not None and recipient.name
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
    - Envoie via Graph un courriel court avec le lien public
      (sans PDF en pièce jointe)
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

    recipient = await _load_recipient(db, soumission)
    if recipient is None or not (recipient.email or "").strip():
        raise DevlogSoumissionSendError(
            "Adresse courriel du destinataire manquante — impossible "
            "d'envoyer la soumission. Renseigne l'email du prospect "
            "ou du client avant de réessayer."
        )

    if not getattr(soumission, "signature_token", None):
        soumission.signature_token = secrets.token_urlsafe(32)
        await db.flush()

    # Pas de PDF en pièce jointe : le client doit cliquer sur le lien
    # public pour consulter / télécharger / signer la soumission. Le PDF
    # reste accessible via la page publique (bouton télécharger).
    sign_url = (
        f"{public_base()}/devlog/sign-soumission/{soumission.signature_token}"
    )
    subject = "Soumission de développement — Horizon Services Immobiliers"
    body = _client_body(soumission, recipient, sign_url)

    mailer = get_mailer()
    if mailer.ready:
        try:
            await mailer.send(
                to=[recipient.email],
                subject=subject,
                html_body=body,
                reply_to=mailer.sender,
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

