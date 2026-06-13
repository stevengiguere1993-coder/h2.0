"""Registre des automatisations — réservé owner/admin.

    GET   /api/v1/automations          → catalogue + état (activé, dernier run)
    PATCH /api/v1/automations/{key}     → activer / couper

Centralise le suivi et le contrôle des automatisations (relances,
rapports, synchros) au lieu d'une config éparpillée. Réservé aux rôles
admin/owner — invisible pour les autres volets.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import DBSession, RequireAdminOrOwner
from app.automations.catalog import CATALOG_BY_KEY
from app.services.automation_state import (
    list_automation_states,
    set_automation_enabled,
)

router = APIRouter(prefix="/automations", tags=["automations"])


class AutomationToggle(BaseModel):
    enabled: bool


@router.get("")
async def list_automations(
    db: DBSession, user: RequireAdminOrOwner
) -> list[dict]:
    """Catalogue complet avec état (activé/coupé) et dernière exécution."""
    return await list_automation_states(db)


@router.patch("/{key}")
async def toggle_automation(
    key: str,
    data: AutomationToggle,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> dict:
    """Active ou coupe une automatisation contrôlable."""
    entry = CATALOG_BY_KEY.get(key)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Automatisation inconnue.")
    if not entry.controllable:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cette automatisation se règle dans son volet dédié "
            "(ex. Téléphonie) et n'est pas contrôlable ici.",
        )
    await set_automation_enabled(db, key, data.enabled, user_id=user.id)
    return {"key": key, "enabled": data.enabled}
