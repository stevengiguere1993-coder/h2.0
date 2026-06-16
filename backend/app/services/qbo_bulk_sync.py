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
                    "action": "already_linked" if p_linked else "needs_link",
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


async def run_migration(
    db: AsyncSession, *, client_id: Optional[int] = None
) -> dict:
    """Migration RÉELLE (écritures QBO), idempotente.

    Clients → Customers (réutilise par email/nom, sinon crée), Projets →
    Jobs (sous-clients), Factures → Invoices rattachées au Job du projet
    (sinon au client). Les ID QBO sont stockés des deux côtés pour ne pas
    recréer de doublon au re-run. Les erreurs sont collectées par dossier
    sans tout interrompre.
    """
    from app.integrations.quickbooks import QuickBooksError, get_qbo
    from app.services.facture_qbo import (
        _build_invoice_payload,
        _build_lines,
        _load_items,
        ensure_invoice_payment,
    )

    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        return {"error": "QuickBooks non connecté (OAuth)."}

    cstmt = select(Client)
    if client_id is not None:
        cstmt = cstmt.where(Client.id == client_id)
    clients = list((await db.execute(cstmt)).scalars().all())

    res = {
        "dry_run": False,
        "scope": "client" if client_id is not None else "all",
        "customers": {"created": 0, "already_linked": 0, "errors": 0},
        "projects": {"linked": 0, "errors": 0},
        "factures": {"pushed": 0, "errors": 0},
        "payments": {"applied": 0},
        "details": [],
    }

    for c in clients:
        detail: dict = {"client_id": c.id, "name": c.name, "errors": []}
        # 1) Customer (réutilise par email/nom via ensure_customer).
        try:
            if not c.qbo_customer_id:
                cust = await qbo.ensure_customer(
                    display_name=c.name,
                    email=c.email,
                    phone=c.phone,
                    billing_address=c.address,
                )
                cid = str(cust.get("Id") or "")
                if not cid:
                    raise QuickBooksError("Customer sans Id")
                c.qbo_customer_id = cid
                await db.flush()
                res["customers"]["created"] += 1
            else:
                res["customers"]["already_linked"] += 1
        except Exception as exc:  # noqa: BLE001
            res["customers"]["errors"] += 1
            detail["errors"].append(f"client: {exc}")
            res["details"].append(detail)
            continue
        customer_id = c.qbo_customer_id

        # 2) Projets → vrais projets QBO (onglet Projets / sous-clients).
        # On NE CRÉE PLUS de sous-client automatiquement : l'API publique
        # QBO ne sait pas créer un « Projet » de l'onglet Projets (un
        # sous-client créé par l'API n'y apparaît pas). On utilise donc
        # UNIQUEMENT la liaison manuelle (Project.qbo_job_id, posée via
        # POST /qbo/link-project). Un projet non lié → ses factures sont
        # rattachées au client parent.
        projects = list(
            (
                await db.execute(
                    select(Project).where(Project.client_id == c.id)
                )
            ).scalars().all()
        )
        job_by_project: dict[int, Optional[str]] = {
            p.id: p.qbo_job_id for p in projects
        }

        # 3) Factures → Invoices (rattachées au Job du projet si dispo).
        factures = list(
            (
                await db.execute(
                    select(Facture).where(Facture.client_id == c.id)
                )
            ).scalars().all()
        )
        for f in factures:
            try:
                ref = customer_id
                if f.project_id and job_by_project.get(f.project_id):
                    ref = job_by_project[f.project_id]
                items = await _load_items(db, f.id)
                lines = await _build_lines(
                    qbo, items, fallback_name=f.reference
                )
                payload = _build_invoice_payload(
                    facture=f,
                    customer_id=ref,
                    lines=lines,
                    existing_invoice_id=f.qbo_invoice_id,
                    existing_sync_token=f.qbo_sync_token,
                )
                invoice = await qbo.create_invoice(payload)
                inv = invoice.get("Invoice") or invoice
                f.qbo_invoice_id = str(inv.get("Id") or "") or None
                f.qbo_sync_token = str(inv.get("SyncToken") or "") or None
                f.qbo_doc_number = str(inv.get("DocNumber") or "") or None
                await db.flush()
                res["factures"]["pushed"] += 1
                # Facture payée dans Kratos → solder la facture côté QBO.
                pid = await ensure_invoice_payment(qbo, db, f, ref, inv)
                if pid:
                    res["payments"]["applied"] += 1
            except Exception as exc:  # noqa: BLE001
                res["factures"]["errors"] += 1
                detail["errors"].append(f"facture {f.id}: {exc}")

        res["details"].append(detail)

    return res


async def reset_links(
    db: AsyncSession, *, client_id: Optional[int] = None
) -> dict:
    """Efface les ID QBO côté Kratos (client / projets / factures) d'un
    dossier, pour pouvoir RE-MIGRER proprement après correction.

    ⚠️ Ne touche PAS à QuickBooks : supprime d'abord les fiches
    correspondantes dans QB sinon la re-migration créera des doublons.
    """
    cstmt = select(Client)
    if client_id is not None:
        cstmt = cstmt.where(Client.id == client_id)
    clients = list((await db.execute(cstmt)).scalars().all())
    out = {"clients": 0, "projects": 0, "factures": 0}
    for c in clients:
        if c.qbo_customer_id:
            c.qbo_customer_id = None
            out["clients"] += 1
        projects = list(
            (
                await db.execute(
                    select(Project).where(Project.client_id == c.id)
                )
            ).scalars().all()
        )
        for p in projects:
            if p.qbo_job_id:
                p.qbo_job_id = None
                out["projects"] += 1
        factures = list(
            (
                await db.execute(
                    select(Facture).where(Facture.client_id == c.id)
                )
            ).scalars().all()
        )
        for f in factures:
            if (
                f.qbo_invoice_id
                or f.qbo_sync_token
                or f.qbo_payment_id
            ):
                f.qbo_invoice_id = None
                f.qbo_sync_token = None
                f.qbo_payment_id = None
                out["factures"] += 1
    await db.flush()
    return out
