"""Cron quotidien : envoi du formulaire NPS post-livraison.

Tourne 1x/jour (à 10h heure Montréal). Cherche les projets passés en
``status='livre'`` il y a entre 7 et 8 jours (delivered_at posé par
l'event listener du modèle ``DevlogProject``) qui n'ont pas encore de
``DevlogNpsResponse``, crée la row + envoie un email avec un lien vers
la page publique ``/devlog/nps/{token}``.

Idempotent : si une row existe déjà pour le projet, on saute.

Usage (HTTP trigger, cf. ``api/v1/endpoints/cron_runner.py``) :
    POST /api/v1/cron/run/devlog-nps-dispatch
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.integrations.email_graph import get_mailer
from app.models.devlog_client import DevlogClient
from app.models.devlog_nps_response import DevlogNpsResponse
from app.models.devlog_project import DevlogProject
from app.services.audit import log_action


log = logging.getLogger(__name__)


def _public_base() -> str:
    """URL de base du frontend public, alignée sur ``devlog_invoice_send``."""
    return (
        os.getenv("PUBLIC_SITE_URL")
        or getattr(settings, "frontend_url", None)
        or "https://immohorizon.com"
    )


def _build_email_html(
    project_name: str, client_name: Optional[str], nps_url: str
) -> str:
    salutation = f"Bonjour {client_name}," if client_name else "Bonjour,"
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.55;max-width:620px">
  <p style="margin:0 0 16px 0">{salutation}</p>
  <p style="margin:0 0 16px 0">
    Votre projet <strong>{project_name}</strong> a été livré il y a une
    semaine. Maintenant que vous avez eu le temps de prendre le pouls,
    nous serions très reconnaissants d'avoir votre avis sur votre
    expérience avec Horizon.
  </p>
  <p style="margin:0 0 16px 0">
    Ça prend moins d'une minute : une note de 0 à 10 et, si vous le
    souhaitez, un mot pour nous dire ce qui a bien fonctionné ou ce
    qu'on pourrait améliorer.
  </p>
  <p style="margin:24px 0 6px 0">
    <a href="{nps_url}"
       style="display:inline-block;background:#1e40af;color:#fff;
              padding:14px 24px;border-radius:8px;font-weight:bold;
              text-decoration:none">Donner mon avis</a>
  </p>
  <p style="margin:8px 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {nps_url}
  </p>
  <p style="margin:24px 0 4px 0;color:#555;font-size:12px">
    Merci d'avance,<br/>
    L'équipe Horizon &middot; Pôle Développement logiciel<br/>
    immohorizon.com
  </p>
</div>
"""


async def _eligible_projects(
    db: AsyncSession, now_utc: datetime
) -> list[DevlogProject]:
    """Projets livrés il y a entre 7 et 8 jours, sans NPS encore créé."""
    window_start = now_utc - timedelta(days=8)
    window_end = now_utc - timedelta(days=7)
    # Sous-requête : project_ids qui ont déjà un NPS.
    already_npsd = select(DevlogNpsResponse.project_id)
    return list(
        (
            await db.execute(
                select(DevlogProject).where(
                    and_(
                        DevlogProject.status == "livre",
                        DevlogProject.delivered_at.isnot(None),
                        DevlogProject.delivered_at >= window_start,
                        DevlogProject.delivered_at <= window_end,
                        DevlogProject.id.notin_(already_npsd),
                    )
                )
            )
        ).scalars().all()
    )


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


async def run_nps_dispatch(db: AsyncSession) -> dict:
    from app.services.automation_state import is_automation_enabled
    if not await is_automation_enabled("devlog_nps_dispatch"):
        return {"skipped": "disabled"}
    mailer = get_mailer()
    now_utc = datetime.now(timezone.utc)

    projects = await _eligible_projects(db, now_utc)

    dispatched = 0
    skipped_no_client_email = 0

    for project in projects:
        client = await _load_client(db, project.client_id)
        to_email = (client.email or "").strip() if client is not None else ""
        if not to_email:
            skipped_no_client_email += 1
            continue

        if not mailer.ready:
            log.warning("Mailer non configuré — arrêt du job NPS dispatch.")
            break

        token = secrets.token_urlsafe(32)
        nps = DevlogNpsResponse(
            project_id=project.id,
            token=token,
            email_sent_at=now_utc,
        )
        db.add(nps)
        await db.flush()  # Pour que l'audit log capte un id si besoin.

        nps_url = f"{_public_base()}/devlog/nps/{token}"
        subject = "Votre avis nous intéresse — Horizon"
        body = _build_email_html(
            project_name=project.name,
            client_name=client.name if client is not None else None,
            nps_url=nps_url,
        )

        try:
            await mailer.send(
                to=[to_email],
                subject=subject,
                html_body=body,
                reply_to=mailer.sender,
            )
        except Exception as exc:
            log.exception(
                "NPS email send failed for project %s: %s", project.id, exc
            )
            # On garde la row créée — un envoi manuel reste possible avec
            # le token. Le projet ne sera pas re-traité au prochain run
            # (la sous-requête ``already_npsd`` exclut son project_id).
            continue

        dispatched += 1
        await log_action(
            db,
            user=None,
            action="devlog_nps.dispatched",
            entity_type="devlog_project",
            entity_id=project.id,
            details={
                "to": to_email,
                "nps_response_id": nps.id,
                "token_prefix": token[:8],
            },
        )

    await db.commit()
    return {
        "eligible_projects": len(projects),
        "dispatched": dispatched,
        "skipped_no_client_email": skipped_no_client_email,
    }


async def run() -> dict:
    async with AsyncSessionLocal() as db:
        return await run_nps_dispatch(db)


def main() -> None:
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = asyncio.run(run())
    log.info("devlog_nps_dispatch: %s", result)


if __name__ == "__main__":
    main()
