"""Synchro QBO de masse — endpoint RAPPORT dry-run (lecture seule).

Aucune écriture dans QuickBooks. Réservé admin/propriétaire. Sert à
valider, AVANT tout envoi réel, ce que la migration ferait (clients,
projets, factures) et l'état de liaison QBO actuel.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.automation_setting import AutomationSetting
from app.services.qbo_auto_sync import QBO_AUTO_SYNC_KEY
from app.services.qbo_bulk_sync import (
    dry_run_report,
    reset_links,
    run_migration,
)
from app.services.qbo_invoice_pull import pull_invoices_from_qbo

router = APIRouter(prefix="/qbo", tags=["qbo-bulk"])


class QboAutoSync(BaseModel):
    enabled: bool


@router.get("/auto-sync", response_model=QboAutoSync)
async def get_auto_sync(db: DBSession, _: RequireAdminOrOwner) -> QboAutoSync:
    row = (
        await db.execute(
            select(AutomationSetting).where(
                AutomationSetting.key == QBO_AUTO_SYNC_KEY
            )
        )
    ).scalar_one_or_none()
    # Fail-closed : désactivé par défaut.
    return QboAutoSync(enabled=bool(row and row.enabled))


@router.put("/auto-sync", response_model=QboAutoSync)
async def set_auto_sync(
    data: QboAutoSync, db: DBSession, user: RequireAdminOrOwner
) -> QboAutoSync:
    row = (
        await db.execute(
            select(AutomationSetting).where(
                AutomationSetting.key == QBO_AUTO_SYNC_KEY
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = AutomationSetting(key=QBO_AUTO_SYNC_KEY, enabled=data.enabled)
        db.add(row)
    else:
        row.enabled = data.enabled
    row.updated_by_user_id = getattr(user, "id", None)
    await db.flush()
    return QboAutoSync(enabled=bool(row.enabled))


@router.get("/bulk-report")
async def bulk_report(
    db: DBSession,
    _: RequireAdminOrOwner,
    client_id: Optional[int] = Query(
        default=None,
        description="Limiter à un client (test sur 1 dossier). Vide = tous.",
    ),
) -> dict:
    return await dry_run_report(db, client_id=client_id)


@router.post("/bulk-sync")
async def bulk_sync(
    db: DBSession,
    _: RequireAdminOrOwner,
    dry_run: bool = Query(
        default=True,
        description=(
            "true (défaut) = rapport seul, AUCUNE écriture. "
            "false = migration RÉELLE dans QuickBooks (irréversible)."
        ),
    ),
    client_id: Optional[int] = Query(
        default=None,
        description="Limiter à un client (test sur 1 dossier). Vide = tous.",
    ),
) -> dict:
    if dry_run:
        return await dry_run_report(db, client_id=client_id)
    # Écritures réelles : la session est committée en fin de requête par
    # la dépendance DB. Idempotent (clé = ID QBO stocké).
    return await run_migration(db, client_id=client_id)


@router.post("/reset-links")
async def reset_links_endpoint(
    db: DBSession,
    _: RequireAdminOrOwner,
    client_id: Optional[int] = Query(default=None),
) -> dict:
    # Efface les ID QBO côté Kratos pour re-migrer proprement (ne touche
    # pas QuickBooks — supprime d'abord les fiches dans QB).
    return await reset_links(db, client_id=client_id)


@router.post("/pull-invoices")
async def pull_invoices(
    db: DBSession,
    _: RequireAdminOrOwner,
    dry_run: bool = Query(
        default=True,
        description=(
            "true (défaut) = aperçu, aucune écriture. false = importe "
            "réellement dans Kratos."
        ),
    ),
    since_days: int = Query(default=180, ge=1, le=3650),
) -> dict:
    # Importe les factures QB rattachées à un projet (Job). Une facture QB
    # SANS projet n'est PAS importée.
    return await pull_invoices_from_qbo(
        db, since_days=since_days, dry_run=dry_run
    )


@router.post("/pull-costs")
async def pull_costs(
    db: DBSession,
    _: RequireAdminOrOwner,
    dry_run: bool = Query(
        default=True,
        description="true (défaut) = aperçu ; false = importe dans Kratos.",
    ),
    since_days: int = Query(default=180, ge=1, le=3650),
) -> dict:
    # Importe les Bills (factures fournisseurs à payer) + Purchases
    # (dépenses) QB rattachés à un PROJET (sous-client). Sans projet → pas
    # d'import.
    from app.services.qbo_cost_pull import pull_project_costs_from_qbo

    return await pull_project_costs_from_qbo(
        db, since_days=since_days, dry_run=dry_run
    )
