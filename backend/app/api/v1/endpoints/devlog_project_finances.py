"""Endpoint finances d'un projet Dev Logiciel - vue agregee.

    GET /api/v1/devlog/projects/{project_id}/finances

Pas de CUD : lecture seule, totaux calcules a la volee a partir des
factures, soumissions et saisies d'heures du projet. Protege par
le guard admin/owner du pole (au router parent).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_invoice_item import DevlogInvoiceItem
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_recurring_service import (
    DevlogProjectRecurringService,
)
from app.models.devlog_soumission import DevlogSoumission
from app.models.devlog_soumission_item import DevlogSoumissionItem
from app.models.devlog_soumission_section import DevlogSoumissionSection
from app.models.devlog_time_entry import DevlogTimeEntry
from app.schemas.devlog import DevlogProjectFinances


router = APIRouter(prefix="/devlog/projects", tags=["devlog-project-finances"])


async def _get_project_or_404(db, project_id: int) -> DevlogProject:
    obj = (
        await db.execute(
            select(DevlogProject).where(DevlogProject.id == project_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable")
    return obj


def _f(v: Optional[float]) -> float:
    return float(v) if v is not None else 0.0


@router.get(
    "/{project_id}/finances",
    response_model=DevlogProjectFinances,
)
async def get_project_finances(
    project_id: int, db: DBSession, _: CurrentUser
) -> DevlogProjectFinances:
    project = await _get_project_or_404(db, project_id)

    # --- Total facture : factures envoyees + payees rattachees au projet
    # On somme le champ ``amount`` quand il est rempli, sinon on tombe
    # sur la somme des items de la facture (devlog_invoice_items.total).
    invoices = (
        await db.execute(
            select(
                DevlogInvoice.id,
                DevlogInvoice.amount,
                DevlogInvoice.status,
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

    # --- Reste a facturer : a partir de la soumission acceptee
    # rattachee au projet (DevlogProject.soumission_id). On somme les
    # totaux client (unit_price * quantity) en EXCLUANT les items
    # recurrents (mensuel) — ces derniers ne font pas partie de
    # l'investissement initial.
    #
    # Distinction :
    #   * Mode devis_dev : item.item_kind in ('feature','fixed_cost')
    #     pour l'initial ; 'recurring_cost' = mensuel exclu.
    #   * Mode legacy : on exclut les items dont la section parente a
    #     billing_kind = 'recurring'.
    total_soumission = 0.0
    if project.soumission_id is not None:
        # Récupère les ids de sections récurrentes pour exclusion.
        recurring_section_ids_rows = (
            await db.execute(
                select(DevlogSoumissionSection.id).where(
                    DevlogSoumissionSection.soumission_id
                    == project.soumission_id,
                    DevlogSoumissionSection.billing_kind == "recurring",
                )
            )
        ).all()
        recurring_section_ids = {r[0] for r in recurring_section_ids_rows}

        total_soumission_val = (
            await db.execute(
                select(func.coalesce(func.sum(DevlogSoumissionItem.total), 0))
                .where(
                    DevlogSoumissionItem.soumission_id == project.soumission_id,
                    DevlogSoumissionItem.item_kind != "recurring_cost",
                    ~DevlogSoumissionItem.section_id.in_(recurring_section_ids)
                    if recurring_section_ids
                    else True,  # type: ignore[arg-type]
                )
            )
        ).scalar_one()
        total_soumission = float(total_soumission_val or 0)
        # Fallback : si la soumission n'a aucun item value (cas inhabituel
        # juste apres conversion), on retombe sur le champ ``amount``
        # global de la soumission s'il est defini.
        if total_soumission == 0.0:
            soumission_amount = (
                await db.execute(
                    select(DevlogSoumission.amount).where(
                        DevlogSoumission.id == project.soumission_id
                    )
                )
            ).scalar_one_or_none()
            total_soumission = _f(soumission_amount)
    total_reste_a_facturer = total_soumission - total_facture

    # --- Total heures facturables : somme des saisies d'heures du projet.
    total_heures_val = (
        await db.execute(
            select(func.coalesce(func.sum(DevlogTimeEntry.hours), 0))
            .where(DevlogTimeEntry.project_id == project_id)
        )
    ).scalar_one()
    total_heures_facturables = float(total_heures_val or 0)

    # --- Marge estimee : approximation simple = soumission_total - cout
    # interne (sum des items de la soumission en cost_per_unit * qty +
    # heures saisies valorisees a 75$/h par defaut). C'est une
    # estimation grossiere ; un vrai calcul devra brancher la table
    # des taux par membre quand on l'aura.
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
                    DevlogSoumissionItem.soumission_id == project.soumission_id,
                    DevlogSoumissionItem.item_kind != "recurring_cost",
                    ~DevlogSoumissionItem.section_id.in_(recurring_section_ids)
                    if recurring_section_ids
                    else True,  # type: ignore[arg-type]
                )
            )
        ).scalar_one()
        cout_estime_items = float(cout_items_val or 0)
    # Valorisation heures : on prend le taux moyen ~75$/h (fallback).
    DEFAULT_HOURLY_RATE = 75.0
    cout_estime_heures = total_heures_facturables * DEFAULT_HOURLY_RATE
    marge_estimee = total_soumission - cout_estime_items - cout_estime_heures

    # Compte des sections de la soumission rattachee, pour info.
    nb_sections = 0
    if project.soumission_id is not None:
        nb_sections_val = (
            await db.execute(
                select(func.count(DevlogSoumissionSection.id)).where(
                    DevlogSoumissionSection.soumission_id == project.soumission_id
                )
            )
        ).scalar_one()
        nb_sections = int(nb_sections_val or 0)

    # --- KPIs services récurrents : MRR + comptes par statut ---
    svc_rows = (
        await db.execute(
            select(
                DevlogProjectRecurringService.status,
                func.count(DevlogProjectRecurringService.id),
                func.coalesce(
                    func.sum(DevlogProjectRecurringService.monthly_amount_cents),
                    0,
                ),
            )
            .where(DevlogProjectRecurringService.project_id == project_id)
            .group_by(DevlogProjectRecurringService.status)
        )
    ).all()
    mrr_active = 0
    counts: dict[str, int] = {
        "active": 0,
        "pending": 0,
        "paused": 0,
        "cancelled": 0,
    }
    for status_value, count_value, sum_value in svc_rows:
        counts[status_value] = int(count_value or 0)
        if status_value == "active":
            mrr_active = int(sum_value or 0)

    return DevlogProjectFinances(
        project_id=project_id,
        soumission_id=project.soumission_id,
        total_facture=round(total_facture, 2),
        total_paye=round(total_paye, 2),
        total_reste_a_facturer=round(total_reste_a_facturer, 2),
        total_soumission=round(total_soumission, 2),
        total_heures_facturables=round(total_heures_facturables, 2),
        marge_estimee=round(marge_estimee, 2),
        nb_sections_soumission=nb_sections,
        mrr_active_cents=mrr_active,
        nb_recurring_services_active=counts["active"],
        nb_recurring_services_pending=counts["pending"],
        nb_recurring_services_paused=counts["paused"],
        nb_recurring_services_cancelled=counts["cancelled"],
    )
