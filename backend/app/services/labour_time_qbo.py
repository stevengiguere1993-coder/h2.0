"""Heures Kratos → feuilles de temps QuickBooks (TimeActivity).

Chaque punch TERMINÉ + APPROUVÉ + rattaché à un PROJET est poussé comme
une TimeActivity QBO liée au sous-client/projet : les heures apparaissent
dans le SUIVI DE PROJET QuickBooks (onglet Projets, rentabilité, coût de
main-d'œuvre via CostRate) SANS AUCUNE écriture comptable — la paie passe
déjà au grand livre (globale, non séparée par projet), donc l'opération
comptable existe déjà ; ce module ne fait que la VENTILATION par projet.

≠ labour_qbo.py (ancien) : celui-là crée une Purchase (débit/crédit) — à
n'utiliser QUE si la paie n'est pas dans QB, sinon double comptage.

Idempotent : `Punch.qbo_time_activity_id`. Un punch modifié est MIS À JOUR
dans QB ; un punch supprimé / désapprouvé / détaché du projet voit sa
TimeActivity SUPPRIMÉE. Best-effort partout : un échec est journalisé et
sera repris par le filet horaire (qbo_nets, non gated).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.employe import Employe
from app.models.project import Project
from app.models.punch import Punch
from app.services.employe_rates import load_rate_periods, resolve_real_cost

log = logging.getLogger(__name__)


def _hours_minutes(hours: float) -> tuple[int, int]:
    """Décompose des heures décimales en (Hours, Minutes) QBO."""
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m >= 60:
        h += 1
        m -= 60
    return h, m


def _is_invalid_prop(exc: Exception) -> bool:
    """Vrai si QBO rejette une PROPRIÉTÉ du payload (ex. CostRate non
    supporté par la compagnie) — on réessaie sans elle."""
    msg = str(exc).lower()
    return (
        "property" in msg
        or "propriété" in msg
        or "invalid or unsupported" in msg
        or "2010" in msg
    )


async def _resolve_project_customer(
    qbo, db: AsyncSession, project: Project
) -> Optional[str]:
    """CustomerRef QB du projet (sous-client/projet), en réparant un
    qbo_job_id périmé via resolve_project_customer_id. None si le projet
    n'a aucun ancrage QB résolvable."""
    parent_id: Optional[str] = None
    if project.client_id:
        from app.models.client import Client

        client = (
            await db.execute(
                select(Client).where(Client.id == project.client_id)
            )
        ).scalar_one_or_none()
        if client is not None:
            try:
                cust = await qbo.ensure_customer(
                    display_name=client.name,
                    email=client.email,
                    phone=client.phone,
                    billing_address=client.address,
                )
                parent_id = str(cust.get("Id") or "") or None
            except QuickBooksError as exc:
                log.warning(
                    "TimeActivity : client QB introuvable (projet %s) : %s",
                    project.id, exc,
                )
    if parent_id:
        from app.services.qbo_project_resolve import (
            resolve_project_customer_id,
        )

        return await resolve_project_customer_id(qbo, db, project, parent_id)
    if getattr(project, "qbo_job_id", None):
        return str(project.qbo_job_id)
    return None


async def _punch_cost_rate(db: AsyncSession, punch: Punch) -> Optional[float]:
    """Coût réel horaire ($/h) de l'employé à la date du punch — même
    méthode que le « Profit réel » (périodes de taux datées)."""
    if not punch.employe_id:
        return None
    emp = (
        await db.execute(
            select(Employe).where(Employe.id == punch.employe_id)
        )
    ).scalar_one_or_none()
    if emp is None:
        return None
    periods = await load_rate_periods(db, [punch.employe_id])
    pdate = punch.started_at.date() if punch.started_at is not None else None
    try:
        rate = resolve_real_cost(
            periods.get(punch.employe_id, []), pdate, emp,
            float(emp.hourly_rate or 0) or 35.0,
        )
        return round(float(rate), 2) if rate else None
    except Exception:  # noqa: BLE001
        return None


async def push_punch_time_to_qbo(
    db: AsyncSession, punch_id: int
) -> Dict[str, Any]:
    """Crée/actualise la TimeActivity QB d'un punch. Si le punch n'est
    plus éligible (désapprouvé, sans projet, sans heures) mais qu'une
    TimeActivity existe, elle est SUPPRIMÉE. Best-effort ; ne lève pas."""
    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        return {"skipped": "qbo_not_configured"}

    punch = (
        await db.execute(select(Punch).where(Punch.id == punch_id))
    ).scalar_one_or_none()
    if punch is None:
        return {"skipped": "punch_introuvable"}

    hours = float(punch.hours or 0)
    eligible = bool(
        punch.approved
        and punch.ended_at is not None
        and punch.project_id
        and hours > 0
        and punch.employe_id
    )
    if not eligible:
        # Plus éligible → retirer la feuille de temps QB si elle existe.
        if punch.qbo_time_activity_id:
            await remove_punch_time_from_qbo(db, punch)
            return {"ok": True, "removed": True}
        return {"skipped": "punch_non_eligible"}

    project = (
        await db.execute(
            select(Project).where(Project.id == punch.project_id)
        )
    ).scalar_one_or_none()
    if project is None:
        return {"skipped": "projet_introuvable"}

    emp = (
        await db.execute(
            select(Employe).where(Employe.id == punch.employe_id)
        )
    ).scalar_one_or_none()
    emp_name = (getattr(emp, "full_name", None) or "").strip()
    if not emp_name:
        return {"skipped": "employe_sans_nom"}

    try:
        qb_emp = await qbo.ensure_employee(display_name=emp_name)
        if not qb_emp or not qb_emp.get("Id"):
            # Collision de nom Customer/Vendor/Employee ou refus QBO :
            # journalisé par ensure_employee ; le filet réessaiera.
            return {"skipped": "employe_qb_impossible"}

        customer_id = await _resolve_project_customer(qbo, db, project)
        if not customer_id:
            return {"skipped": "projet_sans_ancrage_qb"}

        h, m = _hours_minutes(hours)
        payload: Dict[str, Any] = {
            "NameOf": "Employee",
            "EmployeeRef": {"value": str(qb_emp["Id"])},
            "CustomerRef": {"value": str(customer_id)},
            "TxnDate": (
                punch.started_at.date().isoformat()
                if punch.started_at is not None
                else None
            ),
            "Hours": h,
            "Minutes": m,
            # Les heures ventilent le COÛT du projet, elles ne sont pas
            # refacturées d'ici (la facturation client passe par les
            # factures Kratos).
            "BillableStatus": "NotBillable",
            "Description": (
                f"{punch.task or 'Main-d’œuvre'} — Kratos punch #{punch.id}"
            )[:4000],
        }
        if payload["TxnDate"] is None:
            payload.pop("TxnDate")
        # Coût réel horaire → rentabilité du projet QB. Certaines compagnies
        # refusent la propriété : repli sans CostRate (les heures restent).
        cost_rate = await _punch_cost_rate(db, punch)
        if cost_rate:
            payload["CostRate"] = cost_rate

        if punch.qbo_time_activity_id:
            payload["Id"] = str(punch.qbo_time_activity_id)
            try:
                cur = await qbo.get_time_activity(payload["Id"])
                payload["SyncToken"] = str(cur.get("SyncToken") or "0")
                obj = await qbo.update_time_activity(payload)
            except QuickBooksError:
                # Supprimée côté QB → recréation.
                payload.pop("Id", None)
                payload.pop("SyncToken", None)
                obj = await qbo.create_time_activity(payload)
        else:
            try:
                obj = await qbo.create_time_activity(payload)
            except QuickBooksError as exc:
                if _is_invalid_prop(exc) and "CostRate" in payload:
                    payload.pop("CostRate", None)
                    obj = await qbo.create_time_activity(payload)
                else:
                    raise
        ta_id = str(obj.get("Id") or "")
        if ta_id:
            punch.qbo_time_activity_id = ta_id
            await db.flush()
        return {"ok": True, "qbo_time_activity_id": ta_id}
    except QuickBooksError as exc:
        # ERROR : des heures approuvées qui n'atteignent pas le suivi de
        # projet QB doivent se voir dans les logs (motif QBO inclus). Le
        # filet horaire réessaiera.
        log.error(
            "TimeActivity QB punch %s NON envoyée : %s", punch.id, exc
        )
        return {"error": str(exc)[:200]}


async def remove_punch_time_from_qbo(
    db: AsyncSession, punch: Punch
) -> None:
    """Supprime la TimeActivity QB liée au punch (best-effort) et oublie
    le lien. Appelé quand le punch est supprimé, désapprouvé ou détaché."""
    ta_id = (punch.qbo_time_activity_id or "").strip()
    if not ta_id:
        return
    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if qbo.ready:
        ok = await qbo.delete_time_activity(ta_id)
        if not ok:
            log.warning(
                "TimeActivity QB %s (punch %s) : suppression échouée "
                "(déjà absente ?)",
                ta_id, punch.id,
            )
    punch.qbo_time_activity_id = None
    await db.flush()


async def push_punch_time_now(punch_id: int) -> None:
    """Push d'arrière-plan (session fraîche) — déclenché à l'approbation /
    modification d'un punch. Gère aussi le retrait si plus éligible."""
    try:
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await push_punch_time_to_qbo(db, punch_id)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("push_punch_time_now %s: %s", punch_id, exc)


async def delete_time_activity_now(ta_id: str) -> None:
    """Suppression d'arrière-plan de la TimeActivity QB d'un punch DÉJÀ
    supprimé de Kratos (l'id QB a été capturé avant le delete)."""
    try:
        qbo = get_qbo()
        await qbo._load_refresh_from_db()
        if qbo.ready and ta_id:
            ok = await qbo.delete_time_activity(ta_id)
            if not ok:
                log.warning(
                    "TimeActivity QB %s : suppression échouée "
                    "(punch supprimé côté Kratos)",
                    ta_id,
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("delete_time_activity_now %s: %s", ta_id, exc)


async def push_pending_punch_times(db: AsyncSession, limit: int = 200) -> dict:
    """Filet : pousse les punches approuvés+terminés+liés à un projet qui
    n'ont pas encore de TimeActivity QB. Utilisé par qbo_nets (horaire,
    non gated) — garantit la convergence même si un push immédiat échoue."""
    ids = [
        int(r[0])
        for r in (
            await db.execute(
                select(Punch.id)
                .where(
                    Punch.approved.is_(True),
                    Punch.ended_at.is_not(None),
                    Punch.project_id.is_not(None),
                    Punch.hours.is_not(None),
                    Punch.qbo_time_activity_id.is_(None),
                )
                .order_by(Punch.id.asc())
                .limit(limit)
            )
        ).all()
    ]
    ok = ko = 0
    for pid in ids:
        res = await push_punch_time_to_qbo(db, pid)
        if res.get("ok"):
            ok += 1
        elif res.get("error"):
            ko += 1
    return {"candidats": len(ids), "ok": ok, "ko": ko}
