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
    set_automation_config,
    set_automation_enabled,
)

router = APIRouter(prefix="/automations", tags=["automations"])


@router.get(
    "/mcp-journal",
    summary="Journal des appels au connecteur MCP (diagnostic des routines)",
)
async def journal_mcp(user: RequireAdminOrOwner, limite: int = 100) -> dict:
    """Derniers messages JSON-RPC reçus par le serveur MCP : heure (UTC),
    méthode, outil, préfixe de clé, utilisateur, client déclaré, durée,
    succès — pour savoir si une routine claude.ai a seulement essayé de
    parler à Kratos, et à quelle heure."""
    from app.api.v1.endpoints.mcp_server import MCP_JOURNAL_KEY
    from app.services.automation_state import get_automation_config

    cfg = await get_automation_config(MCP_JOURNAL_KEY)
    entrees = [e for e in (cfg.get("entrees") or []) if isinstance(e, dict)]
    limite = max(1, min(300, int(limite)))
    return {"total": len(entrees), "entrees": entrees[-limite:]}


@router.post(
    "/brief-matin/envoyer",
    summary="Envoyer le brief du matin maintenant (test ou rattrapage)",
)
async def envoyer_brief_matin_maintenant(
    db: DBSession, user: RequireAdminOrOwner
) -> dict:
    """Envoie le digest Kratos du jour par courriel aux destinataires de
    l'automatisation « Brief du matin » — sans attendre l'heure réglée et
    sans consommer la réservation quotidienne."""
    from datetime import datetime

    from app.services.brief_matin import FUSEAU, envoyer_brief

    rapport = await envoyer_brief(db, quand=datetime.now(FUSEAU))
    await db.flush()
    return rapport


class AutomationToggle(BaseModel):
    enabled: bool


class AutomationConfig(BaseModel):
    config: dict


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


@router.patch("/{key}/config")
async def update_automation_config(
    key: str,
    data: AutomationConfig,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> dict:
    """Met à jour les paramètres éditables d'une automatisation. On ne
    garde que les clés déclarées dans le catalogue (et on coerce en int)."""
    entry = CATALOG_BY_KEY.get(key)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Automatisation inconnue.")
    allowed = {p.key: p for p in entry.params}
    clean: dict = {}
    for pk, p in allowed.items():
        if pk in data.config:
            try:
                v = int(data.config[pk])
            except (TypeError, ValueError):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Valeur invalide pour « {p.label} ».",
                )
            if v <= 0:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"« {p.label} » doit être un nombre positif.",
                )
            clean[pk] = v
    await set_automation_config(db, key, clean, user_id=user.id)
    return {"key": key, "config": clean}
