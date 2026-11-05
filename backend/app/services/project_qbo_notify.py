"""Alerte « nouveau projet → convertir le sous-client en Projet QBO ».

À chaque création d'un projet construction, la commis comptable reçoit
un courriel avec le nom du sous-client QuickBooks à convertir en
« Projet » (onglet Projets). On ne peut PAS le faire par API sans accès
Premium : Kratos crée le sous-client automatiquement (push QBO), la
commis fait la conversion 1-clic dans QB.

Best-effort : un échec d'envoi ne doit JAMAIS bloquer la création du
projet (on log seulement). Aucun envoi si l'alerte est coupée, sans
destinataire, ou si le mailer n'est pas prêt.

Réglage (Steven 2026-11-04) : Paramètres → Entreprises → « Courriel à la
technicienne comptable » (activer / couper + courriel destinataire),
stocké dans `automation_settings` sous la clé `projet_qbo_alerte`
(config JSON `{"actif": bool, "destinataire": str}`). Tant que la page
n'a jamais été enregistrée, l'ancienne variable `BOOKKEEPER_EMAIL` sert
de repli (renseignée = active).
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.email_graph import get_mailer
from app.models.client import Client
from app.models.project import Project

log = logging.getLogger(__name__)

#: Clé du réglage dans `automation_settings` (et du catalogue).
CLE_REGLAGE = "projet_qbo_alerte"

_COURRIEL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def courriel_valide(valeur: str) -> bool:
    return bool(_COURRIEL_RE.match((valeur or "").strip()))


def _env_destinataire() -> str:
    return (settings.bookkeeper_email or "").strip()


def reglage_depuis_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Réglage effectif à partir de la config enregistrée (dict, possiblement
    vide). `source` : « parametres » (page enregistrée), « variable »
    (repli BOOKKEEPER_EMAIL) ou « aucun »."""
    env = _env_destinataire()
    if isinstance(cfg, dict) and "actif" in cfg:
        dest = str(cfg.get("destinataire") or "").strip()
        return {
            "actif": bool(cfg.get("actif")),
            "destinataire": dest,
            "source": "parametres",
        }
    return {
        "actif": bool(env),
        "destinataire": env,
        "source": "variable" if env else "aucun",
    }


async def lire_reglage() -> dict[str, Any]:
    """Réglage effectif de l'alerte (session courte, fail-safe)."""
    from app.services.automation_state import get_automation_config

    return reglage_depuis_config(await get_automation_config(CLE_REGLAGE))


async def _client_name(db: AsyncSession, client_id: Optional[int]) -> str:
    if not client_id:
        return "—"
    name = (
        await db.execute(select(Client.name).where(Client.id == client_id))
    ).scalar_one_or_none()
    return (name or "—").strip() or "—"


def construire_courriel(
    subcustomer: str, client_name: str, *, essai: bool = False
) -> tuple[str, str]:
    """(sujet, html) de l'alerte. `essai` ajoute un bandeau « courriel
    d'essai » (bouton de la page Paramètres)."""
    brut = subcustomer
    subcustomer = html.escape(subcustomer)
    client_name = html.escape(client_name)
    # Liste des conversions en attente dans Kratos (Steven 2026-10-14) ;
    # pas de préfixe de langue : next-intl est en « as-needed ».
    page_kratos = (
        f"{settings.frontend_url.rstrip('/')}/entreprises/comptabilite/projets-quickbooks"
    )

    bandeau = (
        '<p style="padding:8px 12px;background:#fff4d6;border:1px solid #d89b3c;'
        'color:#5a3d00"><strong>Courriel d\'essai</strong> envoyé depuis '
        "Kratos → Paramètres pour vérifier l'adresse. Aucun projet à "
        "convertir.</p>"
        if essai
        else ""
    )
    corps = f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  {bandeau}<p>Bonjour,</p>
  <p>Un nouveau projet vient d'être créé dans Kratos. Il faut
  <strong>convertir son sous-client en « Projet »</strong> dans
  QuickBooks (onglet Projets).</p>

  <div style="padding:14px 18px;background:#f4f1ec;border-left:3px solid #d89b3c;margin:16px 0">
    <p style="margin:0 0 6px 0"><strong>Sous-client à convertir :</strong>
      {subcustomer}</p>
    <p style="margin:0"><strong>Client :</strong> {client_name}</p>
  </div>

  <p><strong>Le plus simple :</strong> ouvre
  <a href="{page_kratos}">Kratos → Comptabilité → Projets QB</a>, puis la
  page Projets de ton QuickBooks avec l'extension Chrome Horizon installée :
  elle convertit les sous-clients en attente (bouton « Convertir
  maintenant » du panneau Horizon) et Kratos raye la ligne tout seul.</p>

  <p style="margin:0 0 6px 0"><strong>À la main, sinon :</strong></p>
  <ol style="margin:0 0 12px 18px;padding:0">
    <li>Sur le sous-client : un seul client parent + cocher
      « Facturer avec le client parent ».</li>
    <li>Menu de gauche → <strong>Projets</strong>.</li>
    <li>Flèche du bouton <strong>« Nouveau projet ▾ »</strong> →
      <strong>« Convertir à partir d'un client rattaché »</strong>.</li>
    <li>Choisir <strong>{subcustomer}</strong> → confirmer.</li>
  </ol>
  <p style="font-size:13px;color:#555">Les transactions du sous-client
  (factures, dépenses) suivent automatiquement dans le projet.</p>

  <p style="margin-top:24px;color:#888;font-size:12px">
    Horizon Services Immobiliers — alerte automatique Kratos
  </p>
</div>
"""
    sujet = f"À convertir en projet QuickBooks : {brut}"
    if essai:
        sujet = f"[Essai] {sujet}"
    return sujet, corps


async def notify_new_project_for_qbo(
    db: AsyncSession, project: Project
) -> bool:
    """Envoie l'alerte à la technicienne comptable. Retourne True si envoyé."""
    reglage = await lire_reglage()
    to = reglage["destinataire"]
    if not reglage["actif"] or not to:
        log.info(
            "alerte projet QBO ignorée (coupée ou sans destinataire, "
            "Paramètres → Courriel à la technicienne comptable)"
        )
        return False
    mailer = get_mailer()
    if not mailer.ready:
        log.info("alerte projet QBO ignorée (mailer non prêt)")
        return False

    # Nom du sous-client QBO = adresse du chantier (identité du projet),
    # sinon le nom interne. Identique à ce qu'utilise la synchro QBO.
    subcustomer = (project.address or project.name or "").strip() or (
        f"Projet #{project.id}"
    )
    client_name = await _client_name(db, project.client_id)
    sujet, corps = construire_courriel(subcustomer, client_name)
    try:
        await mailer.send(to=[to], subject=sujet, html_body=corps)
        log.info(
            "alerte projet QBO envoyée à %s (projet #%s)", to, project.id
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "alerte projet QBO échouée pour le projet #%s: %s",
            project.id,
            exc,
        )
        return False
