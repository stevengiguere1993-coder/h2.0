"""Endpoint recap d'un projet Dev Logiciel - vue agregee lecture seule.

    GET /api/v1/devlog/projects/{project_id}/recap

Construit un payload unique combinant :
  * Identite + statut du projet
  * Avancement (nb phases / terminees / %), liste des phases
  * Total heures saisies
  * KPIs financiers (total facture/paye/soumission/marge)
  * Total achats du projet (cumul + count)
  * Derniere activite : 10 derniers audit_logs lies au projet
    (entity_type LIKE 'devlog_project%' AND entity_id pertinent)

Protege par le guard admin/owner du pole (au router parent).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select, func

from app.api.deps import CurrentUser, DBSession
from app.models.audit_log import AuditLog
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_invoice_item import DevlogInvoiceItem
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_phase import DevlogProjectPhase
from app.models.devlog_project_purchase import DevlogProjectPurchase
from app.models.devlog_soumission import DevlogSoumission
from app.models.devlog_soumission_item import DevlogSoumissionItem
from app.models.devlog_time_entry import DevlogTimeEntry
from app.schemas.devlog import (
    DevlogProjectRecap,
    DevlogProjectRecapEvent,
    DevlogProjectRecapPhase,
)


router = APIRouter(prefix="/devlog/projects", tags=["devlog-project-recap"])


def _f(v: Optional[float]) -> float:
    return float(v) if v is not None else 0.0


async def _get_project_or_404(db, project_id: int) -> DevlogProject:
    obj = (
        await db.execute(
            select(DevlogProject).where(DevlogProject.id == project_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable")
    return obj


@router.get("/{project_id}/recap", response_model=DevlogProjectRecap)
async def get_project_recap(
    project_id: int, db: DBSession, _: CurrentUser
) -> DevlogProjectRecap:
    project = await _get_project_or_404(db, project_id)

    # --- Phases (jalons) ----------------------------------------------------
    phases = (
        await db.execute(
            select(DevlogProjectPhase)
            .where(DevlogProjectPhase.project_id == project_id)
            .order_by(
                DevlogProjectPhase.position.asc(),
                DevlogProjectPhase.id.asc(),
            )
        )
    ).scalars().all()
    nb_phases = len(phases)
    nb_terminees = sum(1 for p in phases if p.status == "termine")
    pct_phases = (
        round((nb_terminees / nb_phases) * 100.0, 1) if nb_phases else 0.0
    )
    phases_payload = [
        DevlogProjectRecapPhase(
            id=p.id,
            name=p.name,
            status=p.status,
            position=p.position,
            start_date=p.start_date,
            end_date=p.end_date,
        )
        for p in phases
    ]

    # --- Total heures saisies ----------------------------------------------
    total_heures_val = (
        await db.execute(
            select(func.coalesce(func.sum(DevlogTimeEntry.hours), 0)).where(
                DevlogTimeEntry.project_id == project_id
            )
        )
    ).scalar_one()
    total_heures = float(total_heures_val or 0)

    # --- Finances (sous-ensemble de DevlogProjectFinances) -----------------
    invoices = (
        await db.execute(
            select(
                DevlogInvoice.id, DevlogInvoice.amount, DevlogInvoice.status
            ).where(
                DevlogInvoice.project_id == project_id,
                DevlogInvoice.status.in_(("envoyee", "payee")),
            )
        )
    ).all()
    invoice_ids = [row[0] for row in invoices]
    item_totals: dict[int, float] = {}
    if invoice_ids:
        rows = (
            await db.execute(
                select(
                    DevlogInvoiceItem.invoice_id,
                    func.coalesce(func.sum(DevlogInvoiceItem.total), 0),
                )
                .where(DevlogInvoiceItem.invoice_id.in_(invoice_ids))
                .group_by(DevlogInvoiceItem.invoice_id)
            )
        ).all()
        item_totals = {int(inv_id): float(tot or 0) for inv_id, tot in rows}
    total_facture = 0.0
    total_paye = 0.0
    for inv_id, amount, status_ in invoices:
        eff = (
            _f(amount) if amount is not None
            else item_totals.get(int(inv_id), 0.0)
        )
        total_facture += eff
        if status_ == "payee":
            total_paye += eff

    total_soumission = 0.0
    if project.soumission_id is not None:
        total_soumission_val = (
            await db.execute(
                select(
                    func.coalesce(func.sum(DevlogSoumissionItem.total), 0)
                ).where(
                    DevlogSoumissionItem.soumission_id == project.soumission_id
                )
            )
        ).scalar_one()
        total_soumission = float(total_soumission_val or 0)
        if total_soumission == 0.0:
            soumission_amount = (
                await db.execute(
                    select(DevlogSoumission.amount).where(
                        DevlogSoumission.id == project.soumission_id
                    )
                )
            ).scalar_one_or_none()
            total_soumission = _f(soumission_amount)

    total_reste = total_soumission - total_facture

    # Marge estimee = soumission - cout items - heures*75$
    cout_estime_items = 0.0
    if project.soumission_id is not None:
        cout_items_val = (
            await db.execute(
                select(
                    func.coalesce(
                        func.sum(
                            DevlogSoumissionItem.cost_per_unit
                            * DevlogSoumissionItem.quantity
                        ),
                        0,
                    )
                ).where(
                    DevlogSoumissionItem.soumission_id
                    == project.soumission_id
                )
            )
        ).scalar_one()
        cout_estime_items = float(cout_items_val or 0)
    DEFAULT_HOURLY_RATE = 75.0
    marge_estimee = (
        total_soumission - cout_estime_items - total_heures * DEFAULT_HOURLY_RATE
    )

    # --- Achats du projet --------------------------------------------------
    purchases_total = (
        await db.execute(
            select(
                func.coalesce(func.sum(DevlogProjectPurchase.amount_cents), 0),
                func.count(DevlogProjectPurchase.id),
            ).where(DevlogProjectPurchase.project_id == project_id)
        )
    ).one()
    total_achats_cents = int(purchases_total[0] or 0)
    nb_achats = int(purchases_total[1] or 0)

    # --- Derniere activite : 10 derniers audit_logs lies au projet ---------
    # On capture :
    #   * Les logs dont entity_type = 'devlog_project' AND entity_id = project_id
    #   * Les logs des sous-ressources (phases, tasks, members, photos,
    #     purchases) dont entity_id correspond a un id dans ces tables
    #     ET dont les details contiennent project_id. Simplification :
    #     on filtre sur entity_type LIKE 'devlog_project%' et on garde
    #     uniquement ceux ou details_json mentionne le project_id.
    # Pour rester simple et perf, on prend les 50 derniers qui matchent
    # le type, puis on filtre cote Python.
    raw_events = (
        await db.execute(
            select(AuditLog)
            .where(
                or_(
                    (AuditLog.entity_type == "devlog_project")
                    & (AuditLog.entity_id == project_id),
                    AuditLog.entity_type.in_(
                        (
                            "devlog_project_phase",
                            "devlog_project_task",
                            "devlog_project_member",
                            "devlog_project_photo",
                            "devlog_project_purchase",
                            "devlog_time_entry",
                            "devlog_invoice",
                            "devlog_contract",
                        )
                    ),
                )
            )
            .order_by(AuditLog.created_at.desc())
            .limit(80)
        )
    ).scalars().all()

    needle = f'"project_id": {project_id}'
    needle_alt = f"'project_id': {project_id}"
    filtered: list[AuditLog] = []
    for ev in raw_events:
        if (
            ev.entity_type == "devlog_project"
            and ev.entity_id == project_id
        ):
            filtered.append(ev)
            continue
        details = ev.details_json or ""
        if needle in details or needle_alt in details:
            filtered.append(ev)
    events = filtered[:10]

    events_payload = [
        DevlogProjectRecapEvent(
            id=e.id,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            user_email=e.user_email,
            created_at=e.created_at,
            details_json=e.details_json,
        )
        for e in events
    ]

    return DevlogProjectRecap(
        project_id=project_id,
        name=project.name,
        status=project.status,
        started_at=project.started_at,
        start_date=project.start_date,
        due_date=project.due_date,
        nb_phases=nb_phases,
        nb_phases_terminees=nb_terminees,
        pct_phases_terminees=pct_phases,
        phases=phases_payload,
        total_heures=round(total_heures, 2),
        total_facture=round(total_facture, 2),
        total_paye=round(total_paye, 2),
        total_reste_a_facturer=round(total_reste, 2),
        total_soumission=round(total_soumission, 2),
        marge_estimee=round(marge_estimee, 2),
        total_achats_cents=total_achats_cents,
        nb_achats=nb_achats,
        events=events_payload,
    )
