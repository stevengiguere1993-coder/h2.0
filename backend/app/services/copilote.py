"""Copilote Kratos — assistant interne qui répond aux questions de
l'équipe **à partir des données réelles** du portail.

Phase 1 (lecture seule) : on rassemble un contexte compact (RDV à venir
de l'agenda + prospects ouverts du CRM construction) selon le périmètre
du user connecté, puis on demande à la cascade IA gratuite (Gemini →
Groq → Claude) de répondre à la question en langage naturel.

Aucune action n'est exécutée ici : le copilote ne fait que LIRE et
répondre. Les actions (créer une tâche, déplacer un lead…) viendront en
phase 2 via du tool-calling, derrière une validation explicite.

Principes de coût : un seul appel IA par question, contexte plafonné
(MAX_* ci-dessous) pour rester très en dessous des quotas gratuits, et
`thinking_budget=0` pour ne pas gaspiller le budget de tokens.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.ai import AIProviderError, AIProviderUnavailable, complete
from app.models.agenda_event import AgendaEvent
from app.models.contact_request import ContactRequest
from app.models.user import User

log = logging.getLogger(__name__)

# Plafonds de contexte — bornent les tokens envoyés à l'IA (coût + quota).
MAX_EVENTS = 25
MAX_LEADS = 40
AGENDA_HORIZON_DAYS = 14

# Statuts CRM considérés « ouverts » (à suivre / relancer).
_CLOSED_STATUSES = {"won", "lost", "spam"}

SYSTEM_PROMPT = (
    "Tu es le Copilote de Kratos, l'assistant interne de l'équipe "
    "Horizon Services Immobiliers. Tu réponds en français, de façon "
    "concise et concrète, en t'appuyant UNIQUEMENT sur les données "
    "fournies dans le contexte. Si l'information n'est pas dans le "
    "contexte, dis-le simplement au lieu d'inventer. Quand c'est utile, "
    "propose des prochaines actions claires (qui relancer, quoi "
    "préparer), mais tu ne peux pas encore exécuter d'actions toi-même : "
    "formule-les comme des suggestions. Utilise des listes courtes "
    "quand ça aide la lisibilité."
)


def _can_see_all(user: User) -> bool:
    """Owner/admin voient les données de toute l'équipe ; les autres
    sont limités à ce qui les concerne (leurs RDV, leurs prospects)."""
    return bool(user.is_admin or user.role in ("owner", "admin"))


async def _gather_agenda(db: AsyncSession, user: User) -> list[str]:
    """RDV à venir (horizon AGENDA_HORIZON_DAYS), filtrés au périmètre."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=AGENDA_HORIZON_DAYS)
    stmt = (
        select(AgendaEvent)
        .where(AgendaEvent.start_at >= now, AgendaEvent.start_at <= horizon)
        .order_by(AgendaEvent.start_at.asc())
        .limit(MAX_EVENTS)
    )
    if not _can_see_all(user):
        stmt = stmt.where(AgendaEvent.assignee_user_id == user.id)

    rows = (await db.execute(stmt)).scalars().all()
    out: list[str] = []
    for ev in rows:
        when = ev.start_at.strftime("%d/%m %H:%M") if ev.start_at else "?"
        title = (ev.title or "(sans titre)").strip()
        loc = f" @ {ev.location}" if getattr(ev, "location", None) else ""
        out.append(f"- {when} — {title}{loc}")
    return out


async def _gather_leads(db: AsyncSession, user: User) -> list[str]:
    """Prospects CRM ouverts (construction), filtrés au périmètre."""
    stmt = (
        select(ContactRequest)
        .where(ContactRequest.status.notin_(_CLOSED_STATUSES))
        .order_by(ContactRequest.created_at.desc())
        .limit(MAX_LEADS)
    )
    if not _can_see_all(user):
        stmt = stmt.where(ContactRequest.assigned_to_user_id == user.id)

    rows = (await db.execute(stmt)).scalars().all()
    out: list[str] = []
    for c in rows:
        created = c.created_at.strftime("%d/%m") if c.created_at else "?"
        name = (c.name or "(sans nom)").strip()
        phone = f" · {c.phone}" if c.phone else ""
        out.append(
            f"- {name}{phone} · type={c.project_type} · "
            f"statut={c.status} · reçu le {created}"
        )
    return out


def _build_context(events: list[str], leads: list[str]) -> str:
    parts: list[str] = []
    parts.append(f"## RDV à venir ({len(events)})")
    parts.append("\n".join(events) if events else "(aucun RDV à venir)")
    parts.append(f"\n## Prospects ouverts ({len(leads)})")
    parts.append("\n".join(leads) if leads else "(aucun prospect ouvert)")
    return "\n".join(parts)


async def answer_question(
    db: AsyncSession, *, user: User, question: str
) -> dict:
    """Répond à `question` à partir des données réelles du user.

    Retourne ``{"answer": str, "provider": str, "model": str}``.
    Lève ``AIProviderUnavailable`` si aucune IA n'est configurée.
    """
    events = await _gather_agenda(db, user)
    leads = await _gather_leads(db, user)
    context = _build_context(events, leads)

    who = (user.first_name or user.email or "collègue").strip()
    prompt = (
        f"Utilisateur : {who} (rôle {user.role}).\n\n"
        f"Données disponibles :\n{context}\n\n"
        f"Question : {question.strip()}\n\n"
        "Réponds en t'appuyant sur ces données."
    )

    res = await complete(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=1024,
        temperature=0.3,
        thinking_budget=0,
    )
    return {
        "answer": res.text.strip(),
        "provider": res.provider,
        "model": res.model,
    }


__all__ = ["answer_question", "AIProviderError", "AIProviderUnavailable"]
