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


class ProjectQboJobError(Exception):
    """Sous-client QB impossible à garantir — motif lisible pour l'UI."""


async def ensure_project_qbo_job(db: AsyncSession, proj: Project) -> dict:
    """Garantit le SOUS-CLIENT QuickBooks d'un projet SOUS son client
    mère et retourne un compte rendu explicite (retour 2026-09-21 : le
    projet 1616 Saint-Alexandre restait invisible dans QB sans qu'on
    sache pourquoi). Lève ``ProjectQboJobError`` avec le motif exact
    (QBO non connecté, projet sans client, client introuvable, refus
    QB…) au lieu d'échouer en silence. Ne commit pas : l'appelant
    décide.

    Résultat : ``{qbo_job_id, parent_customer_id, parent_name,
    job_name, action}`` où ``action`` vaut ``deja_lie`` (le lien
    existant est valide), ``adopte`` (sous-client existant retrouvé
    sous le client) ou ``cree`` (sous-client créé).
    """
    from app.integrations.quickbooks import get_qbo
    from app.models.client import Client
    from app.services.qbo_project_resolve import resolve_project_customer_id

    if not proj.client_id:
        raise ProjectQboJobError(
            "Le projet n'a pas de client : choisis le client mère sur la "
            "fiche, puis relance."
        )
    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        raise ProjectQboJobError(
            "QuickBooks n'est pas connecté à Kratos (reconnecte QBO dans "
            "les réglages)."
        )
    client: Optional[Client] = (
        await db.execute(select(Client).where(Client.id == proj.client_id))
    ).scalar_one_or_none()
    if client is None:
        raise ProjectQboJobError("Client du projet introuvable.")

    # Client mère QB : d'abord le lien mémorisé sur la fiche — mais si
    # ce lien pointe un customer dont le nom ne correspond pas ALORS
    # qu'un customer au nom exact de la fiche existe, le lien est
    # erroné (ex. adoption par un courriel partagé entre compagnies) →
    # on le répare. Sinon find-or-create (nom exact d'abord, courriel
    # unique en repli).
    cust = None
    if client.qbo_customer_id:
        cust = await qbo.get_customer(client.qbo_customer_id)
        if cust is not None:
            _dn = (cust.get("DisplayName") or "").strip().lower()
            _kn = (client.name or "").strip().lower()
            if _kn and _dn != _kn:
                _exact = await qbo.find_customer_by_name(client.name)
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
        raise ProjectQboJobError(
            f"QuickBooks n'a pas retourné de client pour « {client.name} »."
        )
    if client.qbo_customer_id != parent_id:
        client.qbo_customer_id = parent_id
        await db.flush()

    report: dict = {}
    job_id = await resolve_project_customer_id(
        qbo, db, proj, parent_id, report=report
    )
    action = report.get("action") or "parent"
    if not job_id or job_id == parent_id or action == "parent":
        # resolve retombe sur le client parent quand la création a
        # échoué (motif déjà journalisé) → on le dit clairement.
        raise ProjectQboJobError(
            "QuickBooks a refusé la création du sous-client sous « "
            f"{client.name} » (voir le journal serveur). Le projet n'est "
            "pas lié."
        )
    job_name = ""
    try:
        row = await qbo.get_customer(job_id)
        job_name = (
            (row or {}).get("FullyQualifiedName")
            or (row or {}).get("DisplayName")
            or ""
        )
    except Exception:  # noqa: BLE001
        job_name = ""
    log.info(
        "Projet %s « %s » : sous-client QB %s (%s) sous %s — %s",
        proj.id, proj.name, job_id, job_name, client.name, action,
    )
    return {
        "qbo_job_id": job_id,
        "parent_customer_id": parent_id,
        "parent_name": (cust.get("DisplayName") or client.name),
        "job_name": job_name,
        "action": action,
    }


async def push_bon_qbo_job_now(project_id: int) -> None:
    """Arrière-plan (session fraîche) : crée/répare le SOUS-CLIENT QB du
    projet, sous le client mère. Vaut pour le mini-projet d'un BON comme
    pour un PROJET DE CONSTRUCTION (retour 2026-09-21 : le projet 1616
    Saint-Alexandre n'apparaissait pas sous Jean-François Croteau dans
    QuickBooks — rien ne créait le sous-client avant la première facture
    ou le premier coût poussé, eux-mêmes gatés par l'interrupteur
    d'auto-sync). Best-effort : sans client ou sans QBO configuré, on ne
    fait rien — mais le MOTIF est journalisé en WARNING et persisté sur
    le projet (``qbo_sync_error``) pour être visible sur la fiche.
    Alias lisible : ``push_project_qbo_job_now``."""
    try:
        import asyncio

        from app.db.session import AsyncSessionLocal

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
            try:
                res = await ensure_project_qbo_job(db, proj)
                proj.qbo_sync_error = None
                await db.commit()
                log.info(
                    "Sous-client QB %s prêt (projet %s « %s », %s)",
                    res["qbo_job_id"], proj.id, proj.name, res["action"],
                )
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                log.warning(
                    "push_bon_qbo_job_now projet %s : %s", project_id, exc
                )
                await record_project_qbo_error(project_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "push_bon_qbo_job_now projet %s : %s", project_id, exc
        )


async def record_project_qbo_error(project_id: int, message: str) -> None:
    """Persiste (session fraîche) le dernier motif d'échec QB du projet
    pour l'afficher sur sa fiche — un échec silencieux n'aide personne."""
    try:
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            proj = (
                await db.execute(
                    select(Project).where(Project.id == project_id)
                )
            ).scalar_one_or_none()
            if proj is None:
                return
            proj.qbo_sync_error = (message or "")[:1000] or None
            await db.commit()
    except Exception:  # noqa: BLE001
        log.debug("record_project_qbo_error %s ignoré", project_id, exc_info=True)


# Nom générique : même mécanique pour un projet de construction créé
# depuis une soumission acceptée ou à la main (retour 2026-09-21).
push_project_qbo_job_now = push_bon_qbo_job_now
