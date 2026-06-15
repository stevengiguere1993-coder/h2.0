"""Synchro QBO de masse — endpoint RAPPORT dry-run (lecture seule).

Aucune écriture dans QuickBooks. Réservé admin/propriétaire. Sert à
valider, AVANT tout envoi réel, ce que la migration ferait (clients,
projets, factures) et l'état de liaison QBO actuel.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.api.deps import DBSession, RequireAdminOrOwner
from app.services.qbo_bulk_sync import dry_run_report, run_migration

router = APIRouter(prefix="/qbo", tags=["qbo-bulk"])


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
