"""Invitation d'un investisseur au portail.

Contrairement aux comptes employés (mot de passe temporaire commun
« Horizon »), un investisseur externe reçoit un mot de passe ALÉATOIRE
généré à l'invitation, avec changement forcé à la première connexion.
Le compte créé est volontairement minimal : rôle `employee`, volet
`investisseur` UNIQUEMENT (pas de fiche Employé miroir).
"""

from __future__ import annotations

import json
import logging
import secrets

from app.integrations.email_graph import get_mailer
from app.services.public_links import public_base

log = logging.getLogger(__name__)

# Alphabet sans caractères ambigus (0/O, 1/l/I).
_PW_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


class InvestInviteError(Exception):
    pass


def generate_password(length: int = 12) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def investor_volets_json() -> str:
    return json.dumps(["investisseur"])


async def send_investor_invitation(
    *,
    to_email: str,
    first_name: str,
    temporary_password: str,
    invited_by: str | None = None,
) -> None:
    """Courriel d'invitation au portail. Lève InvestInviteError si le
    mailer n'est pas prêt ou que l'envoi échoue (l'appelant décide s'il
    annule la création ou remonte l'erreur)."""
    mailer = get_mailer()
    if not mailer.ready:
        raise InvestInviteError(
            "Courriel non configuré (AZURE_* / MAIL_FROM_EMAIL) — "
            "communiquez le mot de passe manuellement."
        )
    portal = f"{public_base()}/connexion"
    salutation = f"Bonjour {first_name}," if first_name else "Bonjour,"
    html = f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.55;max-width:620px">
  <p style="margin:0 0 16px 0">{salutation}</p>
  <p style="margin:0 0 16px 0">
    Votre accès au <strong>Portail investisseur Horizon</strong> est
    prêt. Vous y retrouverez en tout temps la valeur de vos parts,
    l'avancement de vos projets et vos documents.
  </p>
  <p style="margin:0 0 6px 0">Vos identifiants :</p>
  <table style="margin:0 0 16px 0;border-collapse:collapse;font-size:14px">
    <tr><td style="padding:4px 12px 4px 0;color:#555">Courriel</td>
        <td style="padding:4px 0"><strong>{to_email}</strong></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#555">Mot de passe temporaire</td>
        <td style="padding:4px 0"><strong style="font-family:monospace">{temporary_password}</strong></td></tr>
  </table>
  <p style="margin:0 0 16px 0;font-size:13px;color:#555">
    Un nouveau mot de passe vous sera demandé à la première connexion.
  </p>
  <p style="margin:20px 0 6px 0">
    <a href="{portal}"
       style="display:inline-block;background:#1d4ed8;color:#fff;
              padding:14px 24px;border-radius:8px;font-weight:bold;
              text-decoration:none">Accéder à mon portail</a>
  </p>
  <p style="margin:8px 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {portal}
  </p>
  <p style="margin:24px 0 4px 0;color:#555;font-size:12px">
    Horizon Services Immobiliers &middot; immohorizon.com
  </p>
</div>
"""
    try:
        await mailer.send(
            to=[to_email],
            subject="Votre accès au Portail investisseur Horizon",
            html_body=html,
            reply_to=mailer.sender,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Invitation investisseur échouée (%s)", to_email)
        raise InvestInviteError(f"Envoi courriel échoué : {exc}") from exc
