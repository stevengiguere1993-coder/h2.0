"""Service de provisionnement et de démarrage d'un projet Dev Logiciel.

Ce service centralise la logique « contrat signé + dépôt payé →
projet démarré » :

    1. Marquage du projet comme démarré (``status='en_cours'``,
       ``started_at=now()``).
    2. Génération du planning depuis la soumission source. Refonte
       (mai 2026) : seules les sections / items « Investissement
       initial » deviennent des :class:`DevlogProjectPhase` +
       :class:`DevlogProjectTask`. Les « Frais Mensuels Récurrents »
       (hébergement, maintenance, abonnements) deviennent des
       :class:`DevlogProjectRecurringService` séparés — un service
       récurrent n'est pas une phase de projet.
    3. Notification interne à Phil (Microsoft Graph) et audit log
       complet sur chaque étape.

L'opération est idempotente : si le projet a déjà ``started_at``, on
retourne le projet sans rien refaire (no-op). Le déclenchement se fait
depuis :

    - ``POST /devlog/contracts/{id}/mark-deposit-paid`` (endpoint admin)
    - ``POST /public/devlog/contracts/{token}/sign`` (signature publique,
      cas où le dépôt avait été marqué payé AVANT la signature en ligne)

Distinction initial / récurrent
--------------------------------

Deux signaux coexistent dans le modèle soumission :

* **Mode devis_dev** (``soumission.is_devis_dev = True``) : ``section_id``
  n'est pas utilisé sur les items ; on regarde ``item.item_kind`` :
    - ``recurring_cost`` → service récurrent
    - ``feature`` / ``fixed_cost`` → initial (deviennent des tâches)
* **Mode legacy** (``soumission.is_devis_dev = False``) : on regarde
  ``section.billing_kind`` qui vaut ``initial`` ou ``recurring``.

Fallback : si rien n'est explicite, on traite comme du ``initial``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.devlog_client import DevlogClient
from app.models.devlog_contract import DevlogContract
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_phase import DevlogProjectPhase
from app.models.devlog_project_recurring_service import (
    DevlogProjectRecurringService,
)
from app.models.devlog_project_task import DevlogProjectTask
from app.models.devlog_soumission import DevlogSoumission
from app.models.devlog_soumission_item import DevlogSoumissionItem
from app.models.devlog_soumission_module import DevlogSoumissionModule
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


def _is_recurring_item(
    item: DevlogSoumissionItem,
    section: Optional[DevlogSoumissionSection],
    soumission: Optional[DevlogSoumission],
) -> bool:
    """Détermine si un item de soumission est récurrent (mensuel).

    Règles (cf. docstring du module) :
      1. Mode devis_dev : ``item_kind == 'recurring_cost'``.
      2. Mode legacy : ``section.billing_kind == 'recurring'``.
      3. Sinon : initial (False).
    """
    kind = getattr(item, "item_kind", None)
    if kind == "recurring_cost":
        return True
    if section is not None and getattr(section, "billing_kind", None) == "recurring":
        return True
    return False


async def _create_recurring_service_from_item(
    db: AsyncSession,
    project: DevlogProject,
    item: DevlogSoumissionItem,
    section: Optional[DevlogSoumissionSection],
    is_project_delivered: bool,
) -> Optional[DevlogProjectRecurringService]:
    """Crée un :class:`DevlogProjectRecurringService` à partir d'un item.

    Le statut initial est ``pending`` tant que le projet n'est pas livré
    (``delivered_at is None``) ; ``active`` (avec ``start_date`` posé)
    une fois la livraison effective.
    """
    label_source = item.description or (
        section.client_label if section else None
    ) or "Service récurrent"
    name = label_source.strip()[:255]
    # Coût interne mensuel en cents — on prend ``cost_per_unit`` (float
    # en dollars) et on convertit. Si le legacy a un ``unit_price`` plus
    # juste (marge déjà appliquée), on garde quand même le coût interne
    # pour rester aligné avec l'item de soumission (la marge sera
    # reconstituée au moment de la facturation).
    cost = float(item.cost_per_unit or 0.0)
    monthly_amount_cents = max(0, int(round(cost * 100)))

    status = "active" if is_project_delivered else "pending"
    start_date = None
    if is_project_delivered and project.delivered_at is not None:
        start_date = project.delivered_at.date()

    svc = DevlogProjectRecurringService(
        project_id=project.id,
        name=name,
        monthly_amount_cents=monthly_amount_cents,
        status=status,
        start_date=start_date,
        source_soumission_item_id=item.id,
    )
    db.add(svc)
    await db.flush()
    await db.refresh(svc)
    await log_action(
        db,
        user=None,
        action="devlog_project_recurring_service.auto_created",
        entity_type="devlog_project_recurring_service",
        entity_id=svc.id,
        details={
            "project_id": project.id,
            "source_item_id": item.id,
            "section_id": section.id if section else None,
            "monthly_amount_cents": monthly_amount_cents,
            "status": status,
        },
    )
    return svc


async def _build_planning_from_modules(
    db: AsyncSession,
    project: DevlogProject,
    soumission: DevlogSoumission,
    items: list[DevlogSoumissionItem],
    modules: list[DevlogSoumissionModule],
) -> tuple[int, int, int]:
    """Mode devis_dev avec MODULES : auto-import structuré.

    Crée UNE phase par module sélectionné (budget = prix client, heures
    prévues dev/manager figées), une phase agrégée pour les fonctionnalités
    directes + frais fixes, et les services récurrents au PRIX CLIENT. Pose
    aussi le budget total + les heures prévues + le taux repère sur le
    projet. Retourne ``(nb_phases, 0, nb_recurring)``.
    """
    from app.services.devlog_devis_calc import compute_devis

    devis = compute_devis(soumission, items, modules)
    initial = devis.get("initial", {}) or {}
    is_delivered = project.delivered_at is not None

    nb_phases = 0
    nb_recurring = 0
    pos = 0
    total_heures_dev = 0.0
    total_heures_manager = 0.0

    async def _add_phase(name, budget_dollars, hdev, hmgr, source_module_id):
        nonlocal nb_phases, pos
        phase = DevlogProjectPhase(
            project_id=project.id,
            name=(name or "Module")[:255] or "Module",
            position=pos,
            status="planifie",
            source_module_id=source_module_id,
            budget_cents=max(0, int(round(float(budget_dollars or 0.0) * 100.0))),
            heures_dev_prevues=float(hdev or 0.0),
            heures_manager_prevues=float(hmgr or 0.0),
        )
        db.add(phase)
        await db.flush()
        await db.refresh(phase)
        nb_phases += 1
        pos += 1
        await log_action(
            db,
            user=None,
            action="devlog_phase_auto_created",
            entity_type="devlog_project_phase",
            entity_id=phase.id,
            details={
                "project_id": project.id,
                "name": phase.name,
                "source_module_id": source_module_id,
                "budget_cents": phase.budget_cents,
                "heures_dev_prevues": phase.heures_dev_prevues,
            },
        )

    # 1. Une phase par module sélectionné (inclut les offerts : scope réel).
    for m in initial.get("modules", []) or []:
        if not m.get("selected"):
            continue
        hdev = float(m.get("total_heures_dev") or 0.0)
        hmgr = float(m.get("total_heures_manager") or 0.0)
        budget = float(m.get("prix_client") or 0.0)
        if hdev <= 0 and hmgr <= 0 and budget <= 0:
            continue
        total_heures_dev += hdev
        total_heures_manager += hmgr
        await _add_phase(
            (m.get("name") or "Module").strip(), budget, hdev, hmgr, m.get("id")
        )

    # 2. Fonctionnalités directes (sans module) + frais fixes → phase agrégée.
    direct = [
        f
        for f in (initial.get("features_client") or [])
        if f.get("module_id") is None and not f.get("offert")
    ]
    fixed = initial.get("frais_fixes_client") or []
    direct_budget = sum(
        float(f.get("prix_client") or 0.0) for f in direct
    ) + sum(float(ff.get("prix_client") or 0.0) for ff in fixed)
    direct_heures = sum(float(f.get("heures") or 0.0) for f in direct)
    if direct or fixed:
        total_heures_dev += direct_heures
        await _add_phase(
            "Fonctionnalités directes & mise en place",
            direct_budget,
            direct_heures,
            0.0,
            None,
        )

    # 3. Services récurrents au PRIX CLIENT (coût interne × (1 + marge réc)).
    marge_rec = (
        float(getattr(soumission, "marge_recurrente_pct", None) or 0.0) / 100.0
    )
    for it in items:
        if getattr(it, "item_kind", None) != "recurring_cost":
            continue
        cost = float(it.cost_per_unit or 0.0)
        client_monthly = cost * (1.0 + marge_rec)
        name = (it.description or "Service récurrent").strip()[:255]
        svc = DevlogProjectRecurringService(
            project_id=project.id,
            name=name or "Service récurrent",
            monthly_amount_cents=max(0, int(round(client_monthly * 100.0))),
            status=("active" if is_delivered else "pending"),
            start_date=(
                project.delivered_at.date()
                if (is_delivered and project.delivered_at)
                else None
            ),
            source_soumission_item_id=it.id,
        )
        db.add(svc)
        await db.flush()
        await db.refresh(svc)
        nb_recurring += 1
        await log_action(
            db,
            user=None,
            action="devlog_project_recurring_service.auto_created",
            entity_type="devlog_project_recurring_service",
            entity_id=svc.id,
            details={
                "project_id": project.id,
                "source_item_id": it.id,
                "monthly_amount_cents": svc.monthly_amount_cents,
                "client_price": True,
            },
        )

    # 4. Totaux projet (budget one-shot + heures prévues + taux repère).
    total_final = float(initial.get("total_final") or 0.0)
    project.budget_cents = max(0, int(round(total_final * 100.0)))
    project.heures_dev_prevues = round(total_heures_dev, 2)
    project.heures_manager_prevues = round(total_heures_manager, 2)
    taux = float(getattr(soumission, "taux_dev_horaire", None) or 0.0)
    if taux > 0:
        project.taux_horaire_defaut = taux
    await db.flush()

    return nb_phases, 0, nb_recurring


async def build_planning_for_project(
    db: AsyncSession, project: DevlogProject, *, user=None
) -> tuple[int, int, int]:
    """Génère le planning d'un projet depuis sa soumission. IDEMPOTENT :
    no-op si le projet a déjà des phases ou n'a pas de soumission. Utilisé
    à l'ACCEPTATION (pour peupler le projet tout de suite) et réutilisable
    pour un re-sync. Retourne ``(nb_phases, nb_tasks, nb_recurring)``."""
    if project.soumission_id is None:
        return 0, 0, 0
    existing = (
        await db.execute(
            select(func.count())
            .select_from(DevlogProjectPhase)
            .where(DevlogProjectPhase.project_id == project.id)
        )
    ).scalar_one()
    if existing and int(existing) > 0:
        return 0, 0, 0
    soumission, sections, items = await _load_soumission_with_planning(
        db, project.soumission_id
    )
    if soumission is None:
        return 0, 0, 0
    return await _build_planning_from_soumission(
        db, project, soumission, sections, items
    )


async def _build_planning_from_soumission(
    db: AsyncSession,
    project: DevlogProject,
    soumission: Optional[DevlogSoumission],
    sections: list[DevlogSoumissionSection],
    items: list[DevlogSoumissionItem],
) -> tuple[int, int, int]:
    """Crée phases + tâches (initial) et services récurrents.

    Retourne ``(nb_phases_creees, nb_tasks_creees, nb_recurring_services)``.
    Best-effort par section : si une section initiale n'a aucun item,
    on crée quand même la phase pour préserver la structure de la
    soumission. Les sections récurrentes ne génèrent jamais de phase.

    NOTE : cette fonction ne dé-duplique pas. Le caller est responsable
    de l'idempotence (voir ``start_project_from_contract`` qui no-op si
    ``project.started_at`` est déjà set).
    """
    nb_phases = 0
    nb_tasks = 0
    nb_recurring = 0

    is_delivered = project.delivered_at is not None

    # Refonte projet 2026-06 : mode devis_dev AVEC modules → import
    # structuré (une phase par module, budget + heures figés). Sinon, on
    # garde la logique sections/items historique ci-dessous.
    if soumission is not None and getattr(soumission, "is_devis_dev", False):
        modules = list(
            (
                await db.execute(
                    select(DevlogSoumissionModule).where(
                        DevlogSoumissionModule.soumission_id == soumission.id
                    )
                )
            )
            .scalars()
            .all()
        )
        if modules:
            return await _build_planning_from_modules(
                db, project, soumission, items, modules
            )

    # Index pour retrouver la section parente d'un item rapidement.
    section_by_id: dict[int, DevlogSoumissionSection] = {
        sec.id: sec for sec in sections
    }
    items_by_section: dict[Optional[int], list[DevlogSoumissionItem]] = {}
    for it in items:
        items_by_section.setdefault(it.section_id, []).append(it)

    # ----------------------------------------------------------------
    # Cas 1 : pas de section explicite (mode devis_dev — section_id NULL
    # sur tous les items). On dispatche par item_kind directement.
    # ----------------------------------------------------------------
    if not sections:
        # Items récurrents → services récurrents (un par item).
        # Items initial → une phase fourre-tout « Livraison » + une
        # tâche par item.
        recurring_items: list[DevlogSoumissionItem] = []
        initial_items: list[DevlogSoumissionItem] = []
        for it in items:
            if _is_recurring_item(it, None, soumission):
                recurring_items.append(it)
            else:
                initial_items.append(it)

        for it in recurring_items:
            svc = await _create_recurring_service_from_item(
                db, project, it, None, is_delivered
            )
            if svc is not None:
                nb_recurring += 1

        if initial_items:
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
            for it in initial_items:
                task = await _create_task_from_item(
                    db, project.id, phase.id, it
                )
                if task is not None:
                    nb_tasks += 1

        return nb_phases, nb_tasks, nb_recurring

    # ----------------------------------------------------------------
    # Cas 2 : sections présentes (mode legacy). On boucle sur les
    # sections en distinguant initial / récurrent.
    # ----------------------------------------------------------------
    for sec in sections:
        sec_items = items_by_section.get(sec.id, [])
        is_recurring_section = (
            getattr(sec, "billing_kind", "initial") == "recurring"
        )

        if is_recurring_section:
            # Section récurrente → 1 service récurrent par item.
            # Si la section n'a aucun item, on en crée quand même un
            # avec le client_label de la section comme nom et
            # monthly_amount_cents=0 (sera ajusté manuellement).
            if not sec_items:
                placeholder = DevlogProjectRecurringService(
                    project_id=project.id,
                    name=(sec.client_label or sec.name or "Service récurrent").strip()[:255],
                    monthly_amount_cents=0,
                    status="active" if is_delivered else "pending",
                    start_date=(
                        project.delivered_at.date()
                        if is_delivered and project.delivered_at is not None
                        else None
                    ),
                )
                db.add(placeholder)
                await db.flush()
                await db.refresh(placeholder)
                nb_recurring += 1
                await log_action(
                    db,
                    user=None,
                    action="devlog_project_recurring_service.auto_created",
                    entity_type="devlog_project_recurring_service",
                    entity_id=placeholder.id,
                    details={
                        "project_id": project.id,
                        "section_id": sec.id,
                        "section_placeholder": True,
                    },
                )
                continue

            for it in sec_items:
                svc = await _create_recurring_service_from_item(
                    db, project, it, sec, is_delivered
                )
                if svc is not None:
                    nb_recurring += 1
            continue

        # --- Section initiale → phase + tasks --------------------------
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

        for it in sec_items:
            task = await _create_task_from_item(db, project.id, phase.id, it)
            if task is not None:
                nb_tasks += 1

    # ----------------------------------------------------------------
    # Items orphelins (sans section_id ou avec un section_id absent des
    # sections de la soumission). On les dispatche par item_kind.
    # ----------------------------------------------------------------
    orphans: list[DevlogSoumissionItem] = list(items_by_section.get(None, []))
    known_section_ids = set(section_by_id.keys())
    for sec_id, sec_items in items_by_section.items():
        if sec_id is not None and sec_id not in known_section_ids:
            orphans.extend(sec_items)

    if orphans:
        orphan_recurring: list[DevlogSoumissionItem] = []
        orphan_initial: list[DevlogSoumissionItem] = []
        for it in orphans:
            if _is_recurring_item(it, None, soumission):
                orphan_recurring.append(it)
            else:
                orphan_initial.append(it)

        for it in orphan_recurring:
            svc = await _create_recurring_service_from_item(
                db, project, it, None, is_delivered
            )
            if svc is not None:
                nb_recurring += 1

        if orphan_initial:
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
            for it in orphan_initial:
                task = await _create_task_from_item(
                    db, project.id, phase.id, it
                )
                if task is not None:
                    nb_tasks += 1

    return nb_phases, nb_tasks, nb_recurring


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
    soumission: Optional[DevlogSoumission] = None
    sections: list[DevlogSoumissionSection] = []
    items: list[DevlogSoumissionItem] = []
    if project.soumission_id is not None:
        soumission, sections, items = await _load_soumission_with_planning(
            db, project.soumission_id
        )

    nb_phases, nb_tasks, nb_recurring = await _build_planning_from_soumission(
        db, project, soumission, sections, items
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
            "recurring_services_created": nb_recurring,
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


# ---------------------------------------------------------------------------
# Activation auto des services récurrents à la livraison
# ---------------------------------------------------------------------------


async def activate_recurring_services_on_delivery(
    db: AsyncSession,
    project: DevlogProject,
) -> int:
    """Bascule en ``active`` tous les services récurrents ``pending`` du
    projet, pose leur ``start_date`` à ``project.delivered_at``.

    À appeler depuis l'event listener du modèle ``DevlogProject`` (ou
    depuis un endpoint admin pour rejouer manuellement). Retourne le
    nombre de services activés. Idempotent : les services déjà actifs
    ou en pause/cancelled ne sont pas touchés.
    """
    if project.delivered_at is None:
        return 0
    services = list(
        (
            await db.execute(
                select(DevlogProjectRecurringService).where(
                    DevlogProjectRecurringService.project_id == project.id,
                    DevlogProjectRecurringService.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    n = 0
    target_date = project.delivered_at.date()
    for svc in services:
        svc.status = "active"
        if svc.start_date is None:
            svc.start_date = target_date
        n += 1
    if n > 0:
        await db.flush()
        await log_action(
            db,
            user=None,
            action="devlog_project_recurring_service.activated_on_delivery",
            entity_type="devlog_project",
            entity_id=project.id,
            details={"count": n, "delivered_at": project.delivered_at.isoformat()},
        )
    return n
