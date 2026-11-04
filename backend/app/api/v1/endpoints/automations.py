"""Registre des automatisations — réservé owner/admin.

    GET   /api/v1/automations          → catalogue + état (activé, dernier run)
    PATCH /api/v1/automations/{key}     → activer / couper

Centralise le suivi et le contrôle des automatisations (relances,
rapports, synchros) au lieu d'une config éparpillée. Réservé aux rôles
admin/owner — invisible pour les autres volets.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.automations.catalog import CATALOG_BY_KEY
from app.services.automation_state import (
    get_automation_config,
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


class DestinatairesIn(BaseModel):
    emails: list[str] = Field(default_factory=list, max_length=50)


@router.get("/brief-matin/destinataires")
async def lire_destinataires_brief(user: RequireAdminOrOwner) -> dict:
    """Qui reçoit le brief du matin. Liste EXPLICITE : vide = personne
    (Phil 2026-10-15 : jamais de courriel à quelqu'un sans qu'un humain
    l'ait inscrit)."""
    from app.services.brief_matin import JOB, liste_destinataires

    return {"destinataires": liste_destinataires(await get_automation_config(JOB))}


@router.put("/brief-matin/destinataires")
async def ecrire_destinataires_brief(
    data: DestinatairesIn, db: DBSession, user: RequireAdminOrOwner
) -> dict:
    """Remplace la liste des destinataires du brief. Chaque courriel doit
    être celui d'un compte Kratos actif (le brief respecte SES
    permissions). Les autres réglages (heure, minute) sont conservés."""
    from app.models.user import User
    from app.services.audit import log_action
    from app.services.brief_matin import JOB

    emails: list[str] = []
    for e in data.emails:
        s = (e or "").strip().lower()
        if s and s not in emails:
            emails.append(s)
    if emails:
        connus = {
            (u.email or "").strip().lower()
            for u in (
                await db.execute(
                    select(User).where(func.lower(User.email).in_(emails), User.is_active.is_(True))
                )
            ).scalars().all()
        }
        inconnus = [e for e in emails if e not in connus]
        if inconnus:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Courriel(s) sans compte Kratos actif : " + ", ".join(inconnus),
            )
    actuel = dict(await get_automation_config(JOB) or {})
    actuel["destinataires"] = emails
    await set_automation_config(db, JOB, actuel, user_id=user.id)
    await log_action(
        db, user=user, action="automations.brief_matin.destinataires",
        entity_type="automation_setting", entity_id=None,
        details={"destinataires": emails},
    )
    await db.flush()
    return {"destinataires": emails}


class AlerteProjetQboIn(BaseModel):
    actif: bool
    destinataire: str = Field(default="", max_length=254)


@router.get(
    "/projet-qbo-alerte",
    summary="Courriel à la technicienne comptable (projets QuickBooks) : réglage",
)
async def lire_alerte_projet_qbo(user: RequireAdminOrOwner) -> dict:
    """Activé ou non + courriel qui reçoit, à chaque nouveau projet, le nom
    du sous-client QuickBooks à convertir en projet. `source` dit d'où vient
    le réglage (« parametres », « variable » BOOKKEEPER_EMAIL, « aucun »)."""
    from app.integrations.email_graph import get_mailer
    from app.services.project_qbo_notify import lire_reglage

    reglage = await lire_reglage()
    reglage["envoi_pret"] = bool(get_mailer().ready)
    return reglage


@router.put(
    "/projet-qbo-alerte",
    summary="Activer / couper le courriel à la technicienne comptable et changer le destinataire",
)
async def ecrire_alerte_projet_qbo(
    data: AlerteProjetQboIn, db: DBSession, user: RequireAdminOrOwner
) -> dict:
    from app.services.audit import log_action
    from app.services.project_qbo_notify import (
        CLE_REGLAGE,
        courriel_valide,
        reglage_depuis_config,
    )

    dest = (data.destinataire or "").strip()
    if dest and not courriel_valide(dest):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Courriel invalide."
        )
    if data.actif and not dest:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Indique le courriel qui reçoit les instructions avant d'activer.",
        )
    actuel = dict(await get_automation_config(CLE_REGLAGE) or {})
    actuel.update({"actif": bool(data.actif), "destinataire": dest})
    await set_automation_config(db, CLE_REGLAGE, actuel, user_id=user.id)
    await log_action(
        db, user=user, action="automations.projet_qbo_alerte",
        entity_type="automation_setting", entity_id=None,
        details={"actif": bool(data.actif), "destinataire": dest},
    )
    await db.flush()
    return reglage_depuis_config(actuel)


@router.post(
    "/projet-qbo-alerte/essai",
    summary="Envoyer un courriel d'essai à la technicienne comptable",
)
async def essai_alerte_projet_qbo(user: RequireAdminOrOwner) -> dict:
    """Envoie l'alerte (marquée « Essai ») au destinataire enregistré, même
    si l'envoi automatique est coupé, pour vérifier l'adresse."""
    from app.integrations.email_graph import get_mailer
    from app.services.project_qbo_notify import (
        construire_courriel,
        lire_reglage,
    )

    reglage = await lire_reglage()
    dest = reglage["destinataire"]
    if not dest:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Aucun courriel destinataire enregistré.",
        )
    mailer = get_mailer()
    if not mailer.ready:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "L'envoi de courriels n'est pas configuré sur ce serveur.",
        )
    sujet, corps = construire_courriel(
        "123 rue Exemple, Montréal", "Client exemple", essai=True
    )
    try:
        await mailer.send(to=[dest], subject=sujet, html_body=corps)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Envoi refusé : {exc}"
        ) from exc
    return {"envoye_a": dest}


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
    # Fusion : les réglages hors catalogue (ex. destinataires du brief)
    # ne sont jamais écrasés par un changement d'heure.
    actuel = dict(await get_automation_config(key) or {})
    actuel.update(clean)
    await set_automation_config(db, key, actuel, user_id=user.id)
    return {"key": key, "config": clean}
