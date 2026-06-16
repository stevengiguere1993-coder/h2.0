"""Alerte « nouveau projet → convertir le sous-client en Projet QBO ».

À chaque création d'un projet construction, la commis comptable reçoit
un courriel avec le nom du sous-client QuickBooks à convertir en
« Projet » (onglet Projets). On ne peut PAS le faire par API sans accès
Premium : Kratos crée le sous-client automatiquement (push QBO), la
commis fait la conversion 1-clic dans QB.

Best-effort : un échec d'envoi ne doit JAMAIS bloquer la création du
projet (on log seulement). Aucun envoi si `BOOKKEEPER_EMAIL` n'est pas
configuré ou si le mailer n'est pas prêt.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.email_graph import get_mailer
from app.models.client import Client
from app.models.project import Project

log = logging.getLogger(__name__)


async def _client_name(db: AsyncSession, client_id: Optional[int]) -> str:
    if not client_id:
        return "—"
    name = (
        await db.execute(select(Client.name).where(Client.id == client_id))
    ).scalar_one_or_none()
    return (name or "—").strip() or "—"


async def notify_new_project_for_qbo(
    db: AsyncSession, project: Project
) -> bool:
    """Envoie l'alerte à la commis comptable. Retourne True si envoyé."""
    to = (settings.bookkeeper_email or "").strip()
    if not to:
        log.info("alerte projet QBO ignorée (BOOKKEEPER_EMAIL non configuré)")
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

    html = f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p>Bonjour,</p>
  <p>Un nouveau projet vient d'être créé dans Kratos. Il faut
  <strong>convertir son sous-client en « Projet »</strong> dans
  QuickBooks (onglet Projets).</p>

  <div style="padding:14px 18px;background:#f4f1ec;border-left:3px solid #d89b3c;margin:16px 0">
    <p style="margin:0 0 6px 0"><strong>Sous-client à convertir :</strong>
      {subcustomer}</p>
    <p style="margin:0"><strong>Client :</strong> {client_name}</p>
  </div>

  <p style="margin:0 0 6px 0"><strong>Étapes (1 fois) :</strong></p>
  <ol style="margin:0 0 12px 18px;padding:0">
    <li>Sur le sous-client : un seul client parent + cocher
      « Facturer avec le client parent ».</li>
    <li>Menu de gauche → <strong>Projets</strong>.</li>
    <li>Flèche du bouton <strong>« Nouveau projet ▾ »</strong> →
      <strong>« Convertir depuis un sous-client »</strong>.</li>
    <li>Choisir <strong>{subcustomer}</strong> → confirmer.</li>
  </ol>
  <p style="font-size:13px;color:#555">Les transactions du sous-client
  (factures, dépenses) suivent automatiquement dans le projet.</p>

  <p style="margin-top:24px;color:#888;font-size:12px">
    Horizon Services Immobiliers — alerte automatique Kratos
  </p>
</div>
"""
    try:
        await mailer.send(
            to=[to],
            subject=f"À convertir en projet QuickBooks : {subcustomer}",
            html_body=html,
        )
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
