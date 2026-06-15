"""Synchro QBO de masse — RAPPORT dry-run (lecture seule).

Ne fait AUCUNE écriture dans QuickBooks. Donne, par client/projet/facture
dans la portée demandée, l'état de liaison QBO actuel et — si QBO est
connecté — si une fiche QB existe déjà par NOM EXACT (réutilisable) ou
non (à créer). Sert à valider la migration avant tout envoi réel.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.facture import Facture
from app.models.project import Project

log = logging.getLogger(__name__)


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


async def dry_run_report(
    db: AsyncSession, *, client_id: Optional[int] = None
) -> dict:
    # Portée : un client précis (test sur 1 dossier) ou tous.
    cstmt = select(Client)
    if client_id is not None:
        cstmt = cstmt.where(Client.id == client_id)
    cstmt = cstmt.order_by(Client.name.asc())
    clients = list((await db.execute(cstmt)).scalars().all())

    # QBO en lecture seule (best-effort) pour prévisualiser réutiliser/créer.
    qbo = None
    qbo_ready = False
    try:
        from app.integrations.quickbooks import get_qbo

        qbo = get_qbo()
        await qbo._load_refresh_from_db()
        qbo_ready = bool(qbo.ready)
    except Exception as exc:  # noqa: BLE001
        log.warning("QBO non disponible pour le rapport: %s", exc)

    out_clients: list[dict] = []
    summary = {
        "clients_total": 0,
        "clients_unlinked": 0,
        "projects_total": 0,
        "projects_unlinked": 0,
        "factures_total": 0,
        "factures_unlinked": 0,
    }

    for c in clients:
        summary["clients_total"] += 1
        c_linked = bool(c.qbo_customer_id)
        if not c_linked:
            summary["clients_unlinked"] += 1

        # Action prévue côté client : déjà lié / réutiliser (nom exact) /
        # créer. La réutilisation se fait par NOM EXACT (choix retenu).
        client_action = "already_linked" if c_linked else "create"
        if not c_linked and qbo_ready and qbo is not None:
            try:
                match = await qbo.find_customer_by_name(c.name)
                if match and (match.get("DisplayName") or "") == c.name:
                    client_action = "reuse"
            except Exception:  # noqa: BLE001
                pass

        projects = list(
            (
                await db.execute(
                    select(Project)
                    .where(Project.client_id == c.id)
                    .order_by(Project.name.asc())
                )
            ).scalars().all()
        )
        proj_out: list[dict] = []
        for p in projects:
            summary["projects_total"] += 1
            p_linked = bool(p.qbo_job_id)
            if not p_linked:
                summary["projects_unlinked"] += 1
            proj_out.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "address": p.address,
                    "qbo_job_id": p.qbo_job_id,
                    "action": "already_linked" if p_linked else "create_or_reuse",
                }
            )

        factures = list(
            (
                await db.execute(
                    select(Facture)
                    .where(Facture.client_id == c.id)
                    .order_by(Facture.id.asc())
                )
            ).scalars().all()
        )
        fact_out: list[dict] = []
        for f in factures:
            summary["factures_total"] += 1
            f_linked = bool(f.qbo_invoice_id)
            if not f_linked:
                summary["factures_unlinked"] += 1
            fact_out.append(
                {
                    "id": f.id,
                    "reference": f.reference,
                    "status": f.status,
                    "total": _num(f.total),
                    "project_id": f.project_id,
                    "qbo_invoice_id": f.qbo_invoice_id,
                    "action": "already_linked" if f_linked else "create",
                }
            )

        out_clients.append(
            {
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "qbo_customer_id": c.qbo_customer_id,
                "action": client_action,
                "projects": proj_out,
                "factures": fact_out,
            }
        )

    return {
        "dry_run": True,
        "qbo_connected": qbo_ready,
        "scope": "client" if client_id is not None else "all",
        "summary": summary,
        "clients": out_clients,
    }
