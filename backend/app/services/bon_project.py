"""Projet lié d'un bon de travail + sous-client QuickBooks.

Un bon de travail (BT) porte ses achats / heures / factures via un PROJET
lié (kind="bon_travail") — même machinerie que les projets réguliers.
Ce module :

1. garantit le projet lié (create-or-get), nommé avec le NUMÉRO DU BON
   (« BT-26-001 — Réparation corde à linge ») pour que le sous-client
   QuickBooks porte le numéro de BT ;
2. crée en arrière-plan le SOUS-CLIENT/projet QB sous le client mère du
   bon (via resolve_project_customer_id, qui crée le projet QB s'il
   n'existe pas). La facturation du bon passe ensuite par le flux projet
   standard : la facture Kratos part sous ce sous-client, les coûts s'y
   rattachent — identique aux projets.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bon_travail import BonTravail
from app.models.project import Project, ProjectStatus

log = logging.getLogger(__name__)


def _bon_project_name(bon: BonTravail) -> str:
    """Nom du projet lié = « <ref BT> — <titre> » : le numéro de bon fait
    partie du nom → le sous-client QB créé pour ce projet porte le n° BT
    (demande : « un sous-client au client mère avec le numéro de BT »)."""
    ref = (bon.reference or "").strip()
    title = (bon.title or "").strip()
    if ref and title:
        return f"{ref} — {title}"[:255]
    return (ref or title or f"Bon {bon.id}")[:255]


async def ensure_bon_project(
    db: AsyncSession, bon: BonTravail
) -> Project:
    """Create-or-get le projet lié du bon (kind="bon_travail").
    Idempotent ; flush mais ne committe pas."""
    if bon.project_id:
        proj = (
            await db.execute(
                select(Project).where(Project.id == bon.project_id)
            )
        ).scalar_one_or_none()
        if proj is not None:
            return proj
    proj = Project(
        name=_bon_project_name(bon),
        client_id=bon.client_id,
        address=(bon.address or None),
        kind="bon_travail",
        responsible_user_id=getattr(bon, "assignee_user_id", None),
        status=ProjectStatus.IN_PROGRESS.value,
    )
    db.add(proj)
    await db.flush()
    bon.project_id = proj.id
    await db.flush()
    return proj


async def push_bon_qbo_job_now(project_id: int) -> None:
    """Arrière-plan (session fraîche) : crée/répare le SOUS-CLIENT QB du
    projet lié au bon, sous le client mère. Best-effort : sans client ou
    sans QBO configuré, on ne fait rien (le push de la première facture /
    du premier coût le créera de toute façon via le même resolveur)."""
    try:
        import asyncio

        from app.db.session import AsyncSessionLocal
        from app.integrations.quickbooks import get_qbo
        from app.models.client import Client
        from app.services.qbo_project_resolve import (
            resolve_project_customer_id,
        )

        qbo = get_qbo()
        await qbo._load_refresh_from_db()
        if not qbo.ready:
            return
        async with AsyncSessionLocal() as db:
            # La tâche est lancée PENDANT la requête qui crée le bon /
            # associe le client : sa transaction n'est commitée qu'à la
            # fin de la requête. Sans attente, cette session fraîche ne
            # voyait pas encore le projet (ou son client) et abandonnait
            # en silence → aucun sous-client QB créé (ex. BT-26-018).
            # On ré-essaie donc quelques secondes avant de renoncer.
            proj = None
            for _attempt in range(6):
                await asyncio.sleep(2)
                proj = (
                    await db.execute(
                        select(Project).where(Project.id == project_id)
                    )
                ).scalar_one_or_none()
                if proj is not None and proj.client_id:
                    break
                # Force une relecture DB au prochain tour (sinon la
                # session ressert l'instance déjà chargée sans client).
                db.expire_all()
            if proj is None or not proj.client_id:
                log.warning(
                    "push_bon_qbo_job_now projet %s : introuvable ou sans "
                    "client après attente — sous-client QB non créé",
                    project_id,
                )
                return
            client: Optional[Client] = (
                await db.execute(
                    select(Client).where(Client.id == proj.client_id)
                )
            ).scalar_one_or_none()
            if client is None:
                return
            # Client mère QB : d'abord le lien mémorisé sur la fiche —
            # mais si ce lien pointe un customer dont le nom ne
            # correspond pas ALORS qu'un customer au nom exact de la
            # fiche existe, le lien est erroné (ex. adoption par un
            # courriel partagé entre compagnies) → on le répare. Sinon
            # find-or-create (nom exact d'abord, courriel unique en
            # repli).
            cust = None
            if client.qbo_customer_id:
                cust = await qbo.get_customer(client.qbo_customer_id)
                if cust is not None:
                    _dn = (cust.get("DisplayName") or "").strip().lower()
                    _kn = (client.name or "").strip().lower()
                    if _kn and _dn != _kn:
                        _exact = await qbo.find_customer_by_name(
                            client.name
                        )
                        if _exact is not None:
                            cust = _exact
            if cust is None:
                cust = await qbo.ensure_customer(
                    display_name=client.name,
                    email=client.email,
                    phone=client.phone,
                    billing_address=client.address,
                )
            parent_id = str(cust.get("Id") or "") if cust else ""
            if not parent_id:
                return
            if client.qbo_customer_id != parent_id:
                client.qbo_customer_id = parent_id
                await db.flush()
            job_id = await resolve_project_customer_id(
                qbo, db, proj, parent_id
            )
            await db.commit()
            log.info(
                "Bon de travail : sous-client QB %s prêt (projet %s « %s »)",
                job_id, proj.id, proj.name,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "push_bon_qbo_job_now projet %s : %s", project_id, exc
        )
