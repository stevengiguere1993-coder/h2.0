"""Courriel d'accueil envoyé automatiquement quand un compte
utilisateur est créé (via auto-création à la création d'un employé,
ou via /api/v1/auth/register depuis /app/utilisateurs).

Le corps donne les identifiants et redirige vers /changer-mot-de-passe
— l'utilisateur sera de toute façon forcé de changer son mdp au
premier login grâce au flag must_change_password.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.integrations.email_graph import get_mailer


log = logging.getLogger(__name__)


def _portal_url() -> str:
    """URL publique du portail (basée sur NEXT_PUBLIC_SITE_URL ou
    fallback immohorizon.com). Utilisé pour fabriquer le lien de
    login dans le courriel."""
    base = getattr(settings, "public_site_url", None)
    if not base:
        # Best-effort — settings.public_site_url n'est pas toujours
        # défini selon les déploiements, on fallback sur le domaine
        # principal.
        base = "https://immohorizon.com"
    return base.rstrip("/")


async def send_welcome_email(
    *,
    to_email: str,
    temporary_password: str,
    full_name: Optional[str] = None,
    role: Optional[str] = None,
    created_by: Optional[str] = None,
) -> bool:
    """Envoie le courriel d'accueil. Retourne True si le send a
    réussi, False sinon (l'échec ne doit pas bloquer la création du
    compte — on log juste)."""
    mailer = get_mailer()
    if not mailer.ready or not to_email:
        log.info("welcome email skipped (mailer not ready or no email)")
        return False

    first = (full_name or "").split(" ")[0] or "bonjour"
    portal = _portal_url()

    role_label = {
        "owner": "Propriétaire",
        "admin": "Administrateur",
        "manager": "Gestionnaire",
        "employee": "Employé",
    }.get(role or "", "Employé")

    html = f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p>Bonjour {first},</p>
  <p>Un compte <strong>{role_label}</strong> vient d'être créé pour toi
  sur le portail Horizon Services Immobiliers.</p>

  <div style="padding:14px 18px;background:#f4f1ec;border-left:3px solid #d89b3c;margin:16px 0">
    <p style="margin:0 0 6px 0"><strong>Courriel :</strong> {to_email}</p>
    <p style="margin:0"><strong>Mot de passe temporaire :</strong>
      <code style="background:#fff;padding:2px 6px;border:1px solid #ddd">{temporary_password}</code>
    </p>
  </div>

  <p>
    <a href="{portal}/fr/connexion"
       style="display:inline-block;background:#d89b3c;color:#111;
              padding:10px 18px;border-radius:6px;text-decoration:none;
              font-weight:bold">
      Se connecter au portail
    </a>
  </p>

  <p style="font-size:13px;color:#555">
    Au premier login, l'application te demandera automatiquement de
    choisir un nouveau mot de passe. Le mot de passe ci-dessus ne sera
    plus valable après cette étape — garde-le uniquement pour la
    première connexion.
  </p>

  <p style="font-size:13px;color:#555">
    Si tu n'attendais pas ce compte, ignore ce courriel et préviens
    {created_by or "l&apos;équipe Horizon"}.
  </p>

  <p style="margin-top:24px;color:#888;font-size:12px">
    Horizon Services Immobiliers<br>
    RBQ 5868-5991-01 — info@immohorizon.com
  </p>
</div>
"""
    try:
        await mailer.send(
            to=[to_email],
            subject="Bienvenue sur le portail Horizon — identifiants de connexion",
            html_body=html,
        )
        log.info("welcome email sent to %s", to_email)
        return True
    except Exception as exc:
        log.exception("welcome email failed for %s: %s", to_email, exc)
        return False
