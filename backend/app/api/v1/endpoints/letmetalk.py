"""LetMeTalk (GoHighLevel) integration — pastille réservée aux managers.

Tous les endpoints de ce module exigent un rôle ``manager`` ou plus
(manager / admin / owner). Le personnel terrain (employee) reçoit
un 403. L'intégration est un outil de gestion, pas une fonctionnalité
à exposer à toute l'équipe.

Étape 1 (présente) : statut de la config + lien vers le launchpad
public. Étape 2 (à venir, dès que ``LETMETALK_API_KEY`` est fournie) :
synchronisation des leads/contacts via l'API GHL.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import RequireManager


router = APIRouter(prefix="/letmetalk", tags=["letmetalk"])


class LetMeTalkStatus(BaseModel):
    api_key_configured: bool
    location_id: Optional[str] = None
    launchpad_url: Optional[str] = None


@router.get("/status", response_model=LetMeTalkStatus)
async def get_status(_: RequireManager) -> LetMeTalkStatus:
    """État de la configuration LetMeTalk côté serveur."""
    api_key = (os.environ.get("LETMETALK_API_KEY") or "").strip()
    location_id = (os.environ.get("LETMETALK_LOCATION_ID") or "").strip()
    launchpad_url = (
        f"https://app.letmetalk.ai/v2/location/{location_id}/launchpad"
        if location_id
        else None
    )
    return LetMeTalkStatus(
        api_key_configured=bool(api_key),
        location_id=location_id or None,
        launchpad_url=launchpad_url,
    )
