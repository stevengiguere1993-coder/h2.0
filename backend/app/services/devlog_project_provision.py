"""Service de provisionnement et de démarrage d'un projet Dev Logiciel.

Ce service centralise la logique « contrat signé + dépôt payé →
projet démarré » :

    1. Marquage du projet comme démarré (``status='en_cours'``,
       ``started_at=now()``).
    2. Génération du planning depuis la soumission source : une
       :class:`DevlogProjectPhase` par section de soumission, et une
       :class:`DevlogProjectTask` par item de section.
    3. Notification interne à Phil (Microsoft Graph) et audit log
       complet sur chaque étape.

L'opération est idempotente : si le projet a déjà ``started_at``, on
retourne le projet sans rien refaire (no-op). Le déclenchement se fait
depuis :

    - ``POST /devlog/contracts/{id}/mark-deposit-paid`` (endpoint admin)
    - ``POST /public/devlog/contracts/{token}/sign`` (signature publique,
      cas où le dépôt avait été marqué payé AVANT la signature en ligne)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.devlog_client import DevlogClient
from app.models.devlog_contract import DevlogContract
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_phase import DevlogProjectPhase
from app.models.devlog_project_task import DevlogProjectTask
from app.models.devlog_soumission import DevlogSoumission
from app.models.devlog_soumission_item import DevlogSoumissionItem
from app.models.devlog_soumission_section import DevlogSoumissionSection
from app.services.audit import log_action


log = logging.getLogger(__name__)


PHIL_EMAIL = "philippe.meuser@immohorizon.com"


async def _load_project_for_contract(
    db: AsyncSession, contract: DevlogContract
) -> Optional[DevlogProject]:
    """Récupère le projet lié au contrat.

    Priorité 1 : ``contract.project_id`` explicite.
    Priorité 2 : projet provisionné par PR #486 lors de la signature
    soumission (lien via ``DevlogProject.soumission_id``).
    """
    if contract.project_id is not None:
        project = (
            await db.execute(
                select(DevlogProject).where(
                    DevlogProject.id == contract.project_id
                )
            )
        ).scalar_one_or_none()
        if project is not None:
            return project

    if contract.soumission_id is not None:
        project = (
            await db.execute(
                select(DevlogProject).where(
                    DevlogProject.soumission_id == contract.soumission_id
                )
            )
        ).scalar_one_or_none()
        if project is not None:
            # On profite du passage pour matérialiser le lien direct
            # contrat → projet (évite une jointure au prochain coup).
            contract.project_id = project.id
            await db.flush()
            return project

    return None


async def _load_soumission_with_planning(
    db: AsyncSession, soumission_id: int
) -> tuple[
    Optional[DevlogSoumission],
    list[DevlogSoumissionSection],
    list[DevlogSoumissionItem],
]:
    """Charge la soumission, ses sections et ses items en 3 requêtes."""
    soumission = (
        await db.execute(
            select(DevlogSoumission).where(
                DevlogSoumission.id == soumission_id
            )
        )
    ).scalar_one_or_none()
    if soumission is None:
        return None, [], []

    sections = list(
        (
            await db.execute(
                select(DevlogSoumissionSection)
                .where(DevlogSoumissionSection.soumission_id == soumission_id)
                .order_by(
                    DevlogSoumissionSection.position.asc(),
                    DevlogSoumissionSection.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )

    items = list(
        (
            await db.execute(
                select(DevlogSoumissionItem)
                .where(DevlogSoumissionItem.soumission_id == soumission_id)
                .order_by(
                    DevlogSoumissionItem.position.asc(),
                    DevlogSoumissionItem.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )

    return soumission, sections, items


async def _build_planning_from_soumission(
    db: AsyncSession,
    project: DevlogProject,
    sections: list[DevlogSoumissionSection],
    items: list[DevlogSoumissionItem],
) -> tuple[int, int]:
    """Crée phases + tâches depuis la soumission source.

    Retourne ``(nb_phases_creees, nb_tasks_creees)``. Best-effort par
    section : si une section n'a aucun item, on crée quand même la
    phase pour préserver la structure de la soumission.

    NOTE : cette fonction ne dé-duplique pas. Le caller est responsable
    de l'idempotence (voir ``start_project_from_contract`` qui no-op si
    ``project.started_at`` est déjà set).
    """
    nb_phases = 0
    nb_tasks = 0

    # Map section_id → liste d'items (one pass sur items).
    items_by_section: dict[Optional[int], list[DevlogSoumissionItem]] = {}
    for it in items:
        items_by_section.setdefault(it.section_id, []).append(it)

    if not sections:
        # Pas de sections : on retombe sur une phase "Livraison" unique
        # qui regroupe tous les items de la soumission.
        phase = DevlogProjectPhase(
            project_id=project.id,
            name="Livraison",
            position=0,
            status="planifie",
        )
        db.add(phase)
        await db.flush()
        await db.refresh(phase)
        nb_phases += 1
        await log_action(
            db,
            user=None,
            action="devlog_phase_auto_created",
            entity_type="devlog_project_phase",
            entity_id=phase.id,
            details={
                "project_id": project.id,
                "name": phase.name,
                "fallback_no_sections": True,
            },
        )
        for it in items:
            task = await _create_task_from_item(db, project.id, phase.id, it)
            if task is not None:
                nb_tasks += 1
        return nb_phases, nb_tasks

    for sec in sections:
        phase_name = (sec.client_label or sec.name or "Section").strip()[:255]
        phase = DevlogProjectPhase(
            project_id=project.id,
            name=phase_name,
            description=sec.notes,
            position=sec.position,
            status="planifie",
        )
        db.add(phase)
        await db.flush()
        await db.refresh(phase)
        nb_phases += 1
        await log_action(
            db,
            user=None,
            action="devlog_phase_auto_created",
            entity_type="devlog_project_phase",
            entity_id=phase.id,
            details={
                "project_id": project.id,
                "section_id": sec.id,
                "name": phase_name,
                "billing_kind": sec.billing_kind,
            },
        )

        for it in items_by_section.get(sec.id, []):
            task = await _create_task_from_item(db, project.id, phase.id, it)
            if task is not None:
                nb_tasks += 1

    # Items orphelins (sans section_id ou avec section_id absent des
    # sections de la soumission, p.ex. mode devis_dev où section_id
    # n'est pas utilisé). On les rattache à une phase fourre-tout.
    orphans = items_by_section.get(None, [])
    known_section_ids = {sec.id for sec in sections}
    for sec_id, sec_items in items_by_section.items():
        if sec_id is not None and sec_id not in known_section_ids:
            orphans.extend(sec_items)

    if orphans:
        phase = DevlogProjectPhase(
            project_id=project.id,
            name="Tâches diverses",
            position=len(sections),
            status="planifie",
        )
        db.add(phase)
        await db.flush()
        await db.refresh(phase)
        nb_phases += 1
        await log_action(
            db,
            user=None,
            action="devlog_phase_auto_created",
            entity_type="devlog_project_phase",
            entity_id=phase.id,
            details={
                "project_id": project.id,
                "name": phase.name,
                "orphan_items": True,
            },
        )
        for it in orphans:
            task = await _create_task_from_item(db, project.id, phase.id, it)
            if task is not None:
                nb_tasks += 1

    return nb_phases, nb_tasks


async def _create_task_from_item(
    db: AsyncSession,
    project_id: int,
    phase_id: int,
    item: DevlogSoumissionItem,
) -> Optional[DevlogProjectTask]:
    """Crée une tâche à partir d'un item de soumission. Les heures
    estimées sont injectées dans la description (le modèle
    ``DevlogProjectTask`` n'a pas de champ dédié — on évite d'ajouter
    une 6e colonne additive pour ça)."""
    title = (item.description or "Tâche").strip()[:255]
    description_parts: list[str] = []
    if item.notes:
        description_parts.append(item.notes.strip())
    heures = item.heures
    if heures is not None:
        try:
            heures_f = float(heures)
        except (TypeError, ValueError):
            heures_f = 0.0
        if heures_f > 0:
            description_parts.append(f"Heures estimées : {heures_f:g} h")

    task = DevlogProjectTask(
        project_id=project_id,
        phase_id=phase_id,
        title=title,
        description=("\n\n".join(description_parts) or None),
        status="a_faire",
        priority="moyenne",
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    await log_action(
        db,
        user=None,
        action="devlog_task_auto_created",
        entity_type="devlog_project_task",
        entity_id=task.id,
        details={
            "project_id": project_id,
            "phase_id": phase_id,
            "source_item_id": item.id,
            "heures_estimees": float(heures) if heures is not None else None,
        },
    )
    return task


async def _send_internal_notification(
    project: DevlogProject,
    client_name: Optional[str],
    contract: DevlogContract,
) -> None:
    """Email interne à Phil — best-effort. Toute exception est avalée :
    un démarrage projet ne doit jamais échouer parce que la notification
    rate."""
    try:
        from app.integrations.email_graph import get_mailer

        mailer = get_mailer()
        if not mailer.ready:
            log.info(
                "devlog project %s started — mailer not configured, "
                "internal notification skipped",
                project.id,
            )
            return

        display_client = client_name or "client inconnu"
        subject = f"Projet démarré : {display_client}"
        html = f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p>Bonjour Phil,</p>
  <p>Le projet <strong>{project.name}</strong> (#{project.id}) vient d'être
  démarré automatiquement suite à la signature du contrat
  <strong>#{contract.id} — {contract.title}</strong> et au versement du
  dépôt initial.</p>
  <ul>
    <li><strong>Client :</strong> {display_client}</li>
    <li><strong>Contrat :</strong> {contract.title}</li>
    <li><strong>Démarré le :</strong> {project.started_at.strftime('%d/%m/%Y %H:%M') if project.started_at else '—'}</li>
  </ul>
  <p>
    <a href="https://immohorizon.com/fr/app/dev-logiciel/projets/{project.id}"
       style="display:inline-block;background:#3b82f6;color:#fff;
              padding:10px 18px;border-radius:6px;text-decoration:none;
              font-weight:bold">
      Voir le projet
    </a>
  </p>
  <p style="margin-top:24px;color:#888;font-size:12px">
    Notification automatique — Horizon Services Immobiliers
  </p>
</div>
"""
        await mailer.send(
            to=[PHIL_EMAIL],
            subject=subject,
            html_body=html,
        )
        log.info(
            "internal notification sent to %s for project %s",
            PHIL_EMAIL,
            project.id,
        )
    except Exception:
        log.exception(
            "internal notification failed for project %s", project.id
        )


async def start_project_from_contract(
    db: AsyncSession,
    contract: DevlogContract,
    *,
    user=None,
) -> Optional[DevlogProject]:
    """Démarre le projet lié à un contrat signé + dépôt payé.

    Pré-conditions vérifiées par le caller :
        * ``contract.status == 'signe'``
        * ``contract.deposit_paid_at is not None``

    Idempotent : si le projet a déjà ``started_at`` non null, retourne
    le projet sans rien refaire. Si aucun projet n'est lié, retourne
    None (l'appelant aura déjà loggé un warning).
    """
    project = await _load_project_for_contract(db, contract)
    if project is None:
        log.warning(
            "contract %s ready to start but no project linked "
            "(soumission_id=%s, project_id=%s)",
            contract.id,
            contract.soumission_id,
            contract.project_id,
        )
        await log_action(
            db,
            user=user,
            action="devlog_project_started.skipped_no_project",
            entity_type="devlog_contract",
            entity_id=contract.id,
            details={
                "soumission_id": contract.soumission_id,
                "project_id": contract.project_id,
            },
        )
        return None

    # Idempotence : déjà démarré → no-op silencieux.
    if project.started_at is not None:
        log.info(
            "project %s already started at %s — skip",
            project.id,
            project.started_at,
        )
        return project

    project.status = "en_cours"
    project.started_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(project)

    # Charge la soumission source si dispo, sinon planning vide.
    sections: list[DevlogSoumissionSection] = []
    items: list[DevlogSoumissionItem] = []
    if project.soumission_id is not None:
        _, sections, items = await _load_soumission_with_planning(
            db, project.soumission_id
        )

    nb_phases, nb_tasks = await _build_planning_from_soumission(
        db, project, sections, items
    )

    # Audit log principal — résumé.
    await log_action(
        db,
        user=user,
        action="devlog_project_started",
        entity_type="devlog_project",
        entity_id=project.id,
        details={
            "contract_id": contract.id,
            "soumission_id": project.soumission_id,
            "phases_created": nb_phases,
            "tasks_created": nb_tasks,
            "trigger": "contract_signed_and_deposit_paid",
        },
    )

    # Notification email interne — best-effort.
    client_name: Optional[str] = None
    if project.client_id is not None:
        client = (
            await db.execute(
                select(DevlogClient).where(
                    DevlogClient.id == project.client_id
                )
            )
        ).scalar_one_or_none()
        if client is not None:
            client_name = client.name

    await _send_internal_notification(project, client_name, contract)

    return project


async def maybe_start_project(
    db: AsyncSession,
    contract: DevlogContract,
    *,
    user=None,
) -> Optional[DevlogProject]:
    """Helper unique pour les endpoints : déclenche le démarrage uniquement
    si les deux conditions sont remplies (contrat signé ET dépôt payé).
    No-op sinon. Toujours retourne le projet quand il est démarré, sinon
    None.
    """
    if contract.status != "signe":
        return None
    if contract.deposit_paid_at is None:
        return None
    return await start_project_from_contract(db, contract, user=user)
