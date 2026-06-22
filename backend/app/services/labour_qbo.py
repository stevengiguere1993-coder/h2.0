"""Pousse le COÛT DE MAIN-D'ŒUVRE d'un projet vers QuickBooks.

Kratos suit les heures des employés (punches) et leur coût réel ; ce coût
n'existait pas dans QB → le coût du projet QB était plus bas que dans Kratos.
On crée donc une dépense (Purchase) par projet qui porte ce coût, rattachée
au sous-client (Job) du projet et à la classe (chantier) :

- ligne de dépense (DÉBIT) → compte « dépense main-d'œuvre » configuré ;
- contrepartie (CRÉDIT)    → compte « répartition / salaires à payer »
  configuré, à réconcilier ensuite avec la paie réelle.

⚠️ À n'activer QUE si la paie n'est PAS déjà enregistrée dans QuickBooks
(sinon double comptage). Idempotent : on met à jour la même Purchase
(`Project.qbo_labour_purchase_id`) au lieu d'en recréer une.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.employe import Employe
from app.models.project import Project
from app.models.punch import Punch
from app.models.qbo_account_map import QboAccountMap
from app.services.employe_rates import load_rate_periods, resolve_real_cost

log = logging.getLogger(__name__)


class LabourSyncError(Exception):
    pass


async def compute_project_labour_cost_ht(
    db: AsyncSession, project_id: int
) -> Tuple[float, float]:
    """(coût réel HT, heures) de main-d'œuvre du projet — même méthode que
    le bloc « Profit réel » : heures × coût réel daté de chaque employé."""
    punches = (
        await db.execute(
            select(Punch).where(
                Punch.project_id == project_id,
                Punch.ended_at.is_not(None),
            )
        )
    ).scalars().all()
    if not punches:
        return 0.0, 0.0
    hours = sum(float(p.hours or 0) for p in punches)
    avg_rate = float(
        (
            await db.execute(
                select(func.coalesce(func.avg(Employe.hourly_rate), 35.0))
            )
        ).scalar_one()
        or 35.0
    )
    emp_ids = [p.employe_id for p in punches if p.employe_id]
    rate_periods = await load_rate_periods(db, emp_ids)
    emp_cache: dict[int, object] = {}
    cost = 0.0
    for p in punches:
        if p.employe_id not in emp_cache:
            emp_cache[p.employe_id] = (
                await db.execute(
                    select(Employe).where(Employe.id == p.employe_id)
                )
            ).scalar_one_or_none()
        emp = emp_cache.get(p.employe_id)
        pdate = p.started_at.date() if p.started_at is not None else None
        cph = resolve_real_cost(
            rate_periods.get(p.employe_id or -1, []), pdate, emp, avg_rate
        )
        cost += float(p.hours or 0) * cph
    return round(cost, 2), round(hours, 2)


async def sync_project_labour_to_qbo(
    db: AsyncSession, project_id: int
) -> dict:
    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        raise LabourSyncError("QuickBooks n'est pas configuré.")
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise LabourSyncError(f"Projet {project_id} introuvable.")

    cost, hours = await compute_project_labour_cost_ht(db, project_id)
    if cost <= 0:
        return {"skipped": True, "reason": "aucune_main_doeuvre"}

    row = (
        await db.execute(select(QboAccountMap).where(QboAccountMap.id == 1))
    ).scalar_one_or_none()
    exp_name = (getattr(row, "labour_expense_account", None) or "").strip()
    clr_name = (getattr(row, "labour_clearing_account", None) or "").strip()
    if not exp_name or not clr_name:
        raise LabourSyncError(
            "Comptes « Main-d'œuvre » non configurés (dépense + "
            "contrepartie) dans Paramètres → Comptes QuickBooks."
        )
    exp_acc = await qbo.find_account_by_name(exp_name)
    clr_acc = await qbo.find_account_by_name(clr_name)
    if not exp_acc or not exp_acc.get("Id"):
        raise LabourSyncError(
            f"Compte de dépense main-d'œuvre introuvable dans QB : {exp_name}"
        )
    if not clr_acc or not clr_acc.get("Id"):
        raise LabourSyncError(
            f"Compte de contrepartie main-d'œuvre introuvable : {clr_name}"
        )

    customer_id = str(project.qbo_job_id) if project.qbo_job_id else None
    class_id = None
    class_name = (
        (getattr(project, "address", None) or "").strip()
        or (project.name or "").strip()
    )
    if class_name:
        try:
            klass = await qbo.ensure_class(name=class_name)
            class_id = (
                str(klass.get("Id")) if klass and klass.get("Id") else None
            )
        except QuickBooksError as exc:
            log.warning("labour ensure_class projet %s: %s", project_id, exc)

    line_detail: dict = {"AccountRef": {"value": str(exp_acc["Id"])}}
    if customer_id:
        line_detail["CustomerRef"] = {"value": customer_id}
        line_detail["BillableStatus"] = "NotBillable"
    if class_id:
        line_detail["ClassRef"] = {"value": class_id}
    payload: dict = {
        "AccountRef": {"value": str(clr_acc["Id"])},  # contrepartie créditée
        "PaymentType": "Cash",
        "TxnDate": date.today().isoformat(),
        "PrivateNote": (
            f"Main-d'œuvre Kratos — projet #{project.id} ({hours} h)"
        ),
        "Line": [
            {
                "DetailType": "AccountBasedExpenseLineDetail",
                "Amount": round(cost, 2),
                "Description": f"Main-d'œuvre ({hours} h)",
                "AccountBasedExpenseLineDetail": line_detail,
            }
        ],
    }

    existing = project.qbo_labour_purchase_id
    try:
        if existing:
            payload["Id"] = str(existing)
            try:
                cur = await qbo.get_purchase(str(existing))
                payload["SyncToken"] = str(cur.get("SyncToken") or "0")
                payload["sparse"] = True
                obj = await qbo.update_purchase(payload)
            except QuickBooksError:
                # Dépense supprimée/obsolète → on recrée à neuf.
                payload.pop("Id", None)
                payload.pop("SyncToken", None)
                payload.pop("sparse", None)
                obj = await qbo.create_purchase(payload)
        else:
            obj = await qbo.create_purchase(payload)
    except QuickBooksError as exc:
        raise LabourSyncError(str(exc)) from exc

    pid = str(obj.get("Id") or "")
    project.qbo_labour_purchase_id = pid or None
    await db.flush()
    return {"ok": True, "qbo_purchase_id": pid, "amount": cost, "hours": hours}
