"""Synchro QBO de masse — endpoint RAPPORT dry-run (lecture seule).

Aucune écriture dans QuickBooks. Réservé admin/propriétaire. Sert à
valider, AVANT tout envoi réel, ce que la migration ferait (clients,
projets, factures) et l'état de liaison QBO actuel.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.api.deps import DBSession, RequireAdminOrOwner
from app.services.qbo_bulk_sync import dry_run_report

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
