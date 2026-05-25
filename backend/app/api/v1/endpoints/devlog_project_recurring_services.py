"""Endpoints services récurrents d'un projet Dev Logiciel.

    GET    /api/v1/devlog/projects/{project_id}/recurring-services
    POST   /api/v1/devlog/projects/{project_id}/recurring-services
    PATCH  /api/v1/devlog/projects/{project_id}/recurring-services/{service_id}
    DELETE /api/v1/devlog/projects/{project_id}/recurring-services/{service_id}
    POST   /api/v1/devlog/projects/{project_id}/recurring-services/{service_id}/generate-invoice

    POST   /api/v1/devlog/projects/backfill-recurring-services  (admin one-shot)

Les CRUD sont protégés par le guard admin/owner du pôle (appliqué au
niveau du router parent dans ``api/v1/router.py``).

Le bouton « Générer la facture du mois » crée une
:class:`DevlogInvoice` en statut ``brouillon`` avec une seule
:class:`DevlogInvoiceItem` au montant mensuel TTC (TPS + TVQ ajoutées).
Aucune envoi automatique : Phil ouvre la facture côté UI et l'envoie
manuellement (l'automatisation cron arrivera plus tard).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_invoice_item import DevlogInvoiceItem
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_recurring_service import (
    RECURRING_SERVICE_STATUSES,
    DevlogProjectRecurringService,
)
from app.services.audit import log_action


router = APIRouter(
    prefix="/devlog/projects", tags=["devlog-project-recurring-services"]
)


# Taxes Québec — alignées sur ``app.services.devlog_devis_calc``. On
# réplique ici les constantes pour éviter un import circulaire.
TPS_RATE = 0.05
TVQ_RATE = 0.09975


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RecurringServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    monthly_amount_cents: int = Field(..., ge=0)
    start_date: Optional[date] = None
    status: str = Field(default="pending", max_length=16)


class RecurringServiceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    monthly_amount_cents: Optional[int] = Field(default=None, ge=0)
    start_date: Optional[date] = None
    status: Optional[str] = Field(default=None, max_length=16)


class RecurringServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    monthly_amount_cents: int
    start_date: Optional[date]
    status: str
    last_invoiced_at: Optional[datetime]
    source_soumission_item_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_project_or_404(db, project_id: int) -> DevlogProject:
    obj = (
        await db.execute(
            select(DevlogProject).where(DevlogProject.id == project_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable")
    return obj


async def _get_service_or_404(
    db, project_id: int, service_id: int
) -> DevlogProjectRecurringService:
    obj = (
        await db.execute(
            select(DevlogProjectRecurringService).where(
                DevlogProjectRecurringService.id == service_id,
                DevlogProjectRecurringService.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Service récurrent introuvable"
        )
    return obj


def _validate_status(value: str) -> None:
    if value not in RECURRING_SERVICE_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Statut invalide. Attendu : {RECURRING_SERVICE_STATUSES}",
        )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/recurring-services",
    response_model=List[RecurringServiceRead],
)
async def list_recurring_services(
    project_id: int, db: DBSession, _: CurrentUser
) -> List[RecurringServiceRead]:
    await _get_project_or_404(db, project_id)
    rows = (
        await db.execute(
            select(DevlogProjectRecurringService)
            .where(DevlogProjectRecurringService.project_id == project_id)
            .order_by(
                DevlogProjectRecurringService.id.asc(),
            )
        )
    ).scalars().all()
    return [RecurringServiceRead.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/recurring-services",
    response_model=RecurringServiceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_recurring_service(
    project_id: int,
    data: RecurringServiceCreate,
    db: DBSession,
    user: CurrentUser,
) -> RecurringServiceRead:
    await _get_project_or_404(db, project_id)
    _validate_status(data.status)
    obj = DevlogProjectRecurringService(
        project_id=project_id,
        name=data.name.strip(),
        monthly_amount_cents=data.monthly_amount_cents,
        start_date=data.start_date,
        status=data.status,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_project_recurring_service.created",
        entity_type="devlog_project_recurring_service",
        entity_id=obj.id,
        details={
            "project_id": project_id,
            "name": obj.name,
            "monthly_amount_cents": obj.monthly_amount_cents,
            "status": obj.status,
        },
    )
    return RecurringServiceRead.model_validate(obj)


@router.patch(
    "/{project_id}/recurring-services/{service_id}",
    response_model=RecurringServiceRead,
)
async def update_recurring_service(
    project_id: int,
    service_id: int,
    data: RecurringServiceUpdate,
    db: DBSession,
    user: CurrentUser,
) -> RecurringServiceRead:
    await _get_project_or_404(db, project_id)
    obj = await _get_service_or_404(db, project_id, service_id)
    fields = data.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] is not None:
        _validate_status(fields["status"])
    if "name" in fields and isinstance(fields["name"], str):
        fields["name"] = fields["name"].strip()
    for field, value in fields.items():
        setattr(obj, field, value)
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_project_recurring_service.updated",
        entity_type="devlog_project_recurring_service",
        entity_id=obj.id,
        details={"project_id": project_id, **fields},
    )
    return RecurringServiceRead.model_validate(obj)


@router.post(
    "/{project_id}/recurring-services/activate-pending",
    response_model=dict,
)
async def activate_pending_services(
    project_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """Active tous les services récurrents ``pending`` du projet.

    À appeler côté frontend juste après que le projet passe en
    ``status='livre'`` (le PATCH générique sur DevlogProject pose
    automatiquement ``delivered_at`` via l'event listener du modèle,
    mais n'active pas les services puisque l'event listener
    SQLAlchemy est synchrone et ne peut pas appeler de fonction
    async).

    Idempotent : si aucun service en pending, retourne ``{count: 0}``.
    Si ``delivered_at`` n'est pas posé, retourne 400 (le projet n'est
    pas livré, rien à activer).
    """
    from app.services.devlog_project_provision import (
        activate_recurring_services_on_delivery,
    )

    project = await _get_project_or_404(db, project_id)
    if project.delivered_at is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Le projet n'est pas livré — impossible d'activer les services.",
        )
    n = await activate_recurring_services_on_delivery(db, project)
    await log_action(
        db,
        user=user,
        action="devlog_project_recurring_service.activate_pending.invoked",
        entity_type="devlog_project",
        entity_id=project_id,
        details={"count": n},
    )
    return {"count": n}


@router.delete(
    "/{project_id}/recurring-services/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_recurring_service(
    project_id: int,
    service_id: int,
    db: DBSession,
    user: CurrentUser,
) -> None:
    await _get_project_or_404(db, project_id)
    obj = await _get_service_or_404(db, project_id, service_id)
    await db.delete(obj)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="devlog_project_recurring_service.deleted",
        entity_type="devlog_project_recurring_service",
        entity_id=service_id,
        details={"project_id": project_id},
    )


# ---------------------------------------------------------------------------
# Génération facture mensuelle (manuelle pour l'instant)
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/recurring-services/{service_id}/generate-invoice",
    status_code=status.HTTP_201_CREATED,
)
async def generate_monthly_invoice(
    project_id: int,
    service_id: int,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    """Crée une facture brouillon avec une seule ligne au montant
    mensuel TTC du service. Le statut reste ``brouillon`` — Phil
    l'ouvre et l'envoie depuis l'UI factures classique."""
    project = await _get_project_or_404(db, project_id)
    svc = await _get_service_or_404(db, project_id, service_id)
    if svc.status != "active":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Le service n'est pas actif — impossible de générer une facture.",
        )
    if svc.monthly_amount_cents <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Montant mensuel à 0 — ajuste le service avant de facturer.",
        )

    # Montants en dollars pour rester aligné avec DevlogInvoice.amount
    # (Float en dollars, pas en cents).
    amount_ht = svc.monthly_amount_cents / 100.0
    tps = amount_ht * TPS_RATE
    tvq = amount_ht * TVQ_RATE
    amount_ttc = round(amount_ht + tps + tvq, 2)

    today = date.today()
    invoice = DevlogInvoice(
        client_id=project.client_id,
        project_id=project.id,
        amount=amount_ttc,
        status="brouillon",
        issued_date=today,
        notes=(
            f"Facturation mensuelle automatique — {svc.name}\n"
            f"Service récurrent #{svc.id}"
        ),
    )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice)

    # Ligne de facture détaillée — quantity=1, unit_price=amount HT.
    # Total inclut les taxes côté DevlogInvoice.amount (TTC).
    item = DevlogInvoiceItem(
        invoice_id=invoice.id,
        description=f"{svc.name} — facturation mensuelle",
        quantity=1.0,
        unit_price=amount_ht,
        total=amount_ht,
    )
    db.add(item)

    # Stamp last_invoiced_at sur le service.
    svc.last_invoiced_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(invoice)
    await db.refresh(svc)

    await log_action(
        db,
        user=user,
        action="devlog_project_recurring_service.invoice_generated",
        entity_type="devlog_invoice",
        entity_id=invoice.id,
        details={
            "project_id": project_id,
            "service_id": service_id,
            "service_name": svc.name,
            "amount_ht_cents": svc.monthly_amount_cents,
            "amount_ttc": amount_ttc,
        },
    )
    return {
        "invoice_id": invoice.id,
        "amount": amount_ttc,
        "status": invoice.status,
    }


# ---------------------------------------------------------------------------
# Backfill admin one-shot — projets créés avec l'ancien provisioning
# ---------------------------------------------------------------------------


class BackfillSummary(BaseModel):
    projects_scanned: int
    phases_removed: int
    services_created: int
    projects_touched: list[int]


@router.post(
    "/backfill-recurring-services",
    response_model=BackfillSummary,
)
async def backfill_recurring_services(
    db: DBSession, user: CurrentUser
) -> BackfillSummary:
    """Migre les projets créés AVANT la refonte (PR #492 et antérieures).

    Heuristique : pour chaque projet lié à une soumission, on rejoue
    la classification initial / récurrent sur les items source. Pour
    chaque item récurrent :

        1. Crée le ``DevlogProjectRecurringService`` correspondant si
           absent (clé d'unicité : project_id + source_soumission_item_id).
        2. Supprime la phase et les tâches qui ont été créées pour cet
           item récurrent par l'ancien provisioning (best-effort par
           correspondance de nom avec ``client_label`` de la section
           récurrente).

    100 % idempotent : appelable plusieurs fois sans dupliquer.
    """
    from app.models.devlog_project_phase import DevlogProjectPhase
    from app.models.devlog_project_task import DevlogProjectTask
    from app.models.devlog_soumission import DevlogSoumission
    from app.models.devlog_soumission_item import DevlogSoumissionItem
    from app.models.devlog_soumission_section import (
        DevlogSoumissionSection,
    )
    from app.services.devlog_project_provision import _is_recurring_item

    projects = list(
        (
            await db.execute(
                select(DevlogProject).where(
                    DevlogProject.soumission_id.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )

    nb_services = 0
    nb_phases_removed = 0
    touched: list[int] = []

    for project in projects:
        soumission = (
            await db.execute(
                select(DevlogSoumission).where(
                    DevlogSoumission.id == project.soumission_id
                )
            )
        ).scalar_one_or_none()
        if soumission is None:
            continue

        sections = list(
            (
                await db.execute(
                    select(DevlogSoumissionSection)
                    .where(
                        DevlogSoumissionSection.soumission_id
                        == project.soumission_id
                    )
                    .order_by(
                        DevlogSoumissionSection.position.asc(),
                        DevlogSoumissionSection.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        section_by_id = {s.id: s for s in sections}
        items = list(
            (
                await db.execute(
                    select(DevlogSoumissionItem).where(
                        DevlogSoumissionItem.soumission_id
                        == project.soumission_id
                    )
                )
            )
            .scalars()
            .all()
        )

        existing_services = list(
            (
                await db.execute(
                    select(DevlogProjectRecurringService).where(
                        DevlogProjectRecurringService.project_id
                        == project.id
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_by_source_item = {
            s.source_soumission_item_id: s
            for s in existing_services
            if s.source_soumission_item_id is not None
        }

        project_touched = False
        recurring_section_names: set[str] = set()
        for sec in sections:
            if getattr(sec, "billing_kind", "initial") == "recurring":
                label = (sec.client_label or sec.name or "").strip()
                if label:
                    recurring_section_names.add(label.lower())

        # Phase 1 : pour chaque item récurrent, créer le service.
        for it in items:
            sec = (
                section_by_id.get(it.section_id)
                if it.section_id is not None
                else None
            )
            if not _is_recurring_item(it, sec, soumission):
                continue
            if it.id in existing_by_source_item:
                continue  # déjà migré

            cost = float(it.cost_per_unit or 0.0)
            label_source = it.description or (
                sec.client_label if sec else None
            ) or "Service récurrent"
            is_delivered = project.delivered_at is not None
            svc = DevlogProjectRecurringService(
                project_id=project.id,
                name=label_source.strip()[:255],
                monthly_amount_cents=max(0, int(round(cost * 100))),
                start_date=(
                    project.delivered_at.date()
                    if is_delivered and project.delivered_at is not None
                    else None
                ),
                status="active" if is_delivered else "pending",
                source_soumission_item_id=it.id,
            )
            db.add(svc)
            await db.flush()
            await db.refresh(svc)
            existing_by_source_item[it.id] = svc
            nb_services += 1
            project_touched = True
            await log_action(
                db,
                user=user,
                action="devlog_project_recurring_service.backfilled",
                entity_type="devlog_project_recurring_service",
                entity_id=svc.id,
                details={
                    "project_id": project.id,
                    "source_item_id": it.id,
                    "monthly_amount_cents": svc.monthly_amount_cents,
                },
            )

        # Phase 2 : supprime les phases dont le nom correspond à une
        # section récurrente — les tâches sont supprimées par cascade
        # (ON DELETE CASCADE sur DevlogProjectTask.phase_id ? non, on
        # le fait à la main pour rester safe).
        if recurring_section_names:
            phases = list(
                (
                    await db.execute(
                        select(DevlogProjectPhase).where(
                            DevlogProjectPhase.project_id == project.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for ph in phases:
                if (ph.name or "").strip().lower() in recurring_section_names:
                    # Supprime d'abord les tâches de cette phase.
                    tasks = list(
                        (
                            await db.execute(
                                select(DevlogProjectTask).where(
                                    DevlogProjectTask.phase_id == ph.id
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for t in tasks:
                        await db.delete(t)
                    await db.delete(ph)
                    nb_phases_removed += 1
                    project_touched = True
                    await log_action(
                        db,
                        user=user,
                        action="devlog_project_phase.backfill_removed",
                        entity_type="devlog_project_phase",
                        entity_id=ph.id,
                        details={
                            "project_id": project.id,
                            "name": ph.name,
                            "reason": "matched_recurring_section_name",
                            "tasks_removed": len(tasks),
                        },
                    )

        if project_touched:
            touched.append(project.id)

    await db.flush()

    return BackfillSummary(
        projects_scanned=len(projects),
        phases_removed=nb_phases_removed,
        services_created=nb_services,
        projects_touched=touched,
    )
