"""Background AI scoring for newly-created tasks (entreprise + deal).

Lance un scoring ICE asynchrone après création d'une tâche. Le
score (impact / confidence / effort) reste `None` à la création, ce
qui affiche la pastille P4 « Non évaluée » côté UI ; quelques
secondes plus tard l'IA remplit les valeurs et la pastille se met
à jour au prochain refetch.

Idempotent : ne touche pas une tâche déjà scorée manuellement (i.e.
qui a au moins une des trois valeurs ICE déjà remplie au moment où
le job s'exécute).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

from app.db.session import AsyncSessionLocal
from app.integrations.ai import (
    AIProviderError,
    AIProviderUnavailable,
    complete,
)
from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache
from app.models.prospection_deal import ProspectionDeal
from app.models.prospection_deal_task import ProspectionDealTask

log = logging.getLogger(__name__)

_SYSTEM = (
    "Tu es un consultant stratégique. Tu évalues la priorité des "
    "tâches de façon factuelle, sans flatterie. Conservateur sur la "
    "confiance ; rigoureux sur l'effort."
)


def _build_prompt(
    *,
    title: str,
    description: Optional[str],
    departement: Optional[str],
    due_date: Optional[date],
    context_name: Optional[str],
    context_description: Optional[str],
) -> str:
    parts: list[str] = []
    if context_name:
        parts.append(f"Contexte : {context_name}")
    if context_description:
        parts.append(f"Description du contexte : {context_description}")
    if departement:
        parts.append(f"Département : {departement}")
    if due_date:
        parts.append(f"Échéance prévue : {due_date.isoformat()}")
    parts.append(f"Titre de la tâche : {title}")
    if description:
        parts.append(f"Description : {description}")
    return (
        "\n".join(parts)
        + "\n\nÉvalue cette tâche selon le framework ICE puis renvoie "
        "STRICTEMENT un JSON avec :\n"
        '  "impact" (entier 1-10), "confidence" (entier 1-10), '
        '"effort" (entier 1-10).\n'
        "Réponds UNIQUEMENT avec le JSON, sans markdown."
    )


async def _ai_score(prompt: str) -> Optional[tuple[int, int, int]]:
    try:
        res = await complete(
            prompt=prompt, system=_SYSTEM, max_tokens=200, temperature=0.3
        )
    except (AIProviderUnavailable, AIProviderError) as exc:
        log.info("auto-score: AI unavailable: %s", exc)
        return None
    raw = res.text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
    try:
        parsed = json.loads(raw.strip())
        impact = max(1, min(10, int(parsed["impact"])))
        confidence = max(1, min(10, int(parsed["confidence"])))
        effort = max(1, min(10, int(parsed["effort"])))
        return impact, confidence, effort
    except Exception as exc:
        log.warning("auto-score: parse failed: %s. Raw=%r", exc, raw[:200])
        return None


async def autoscore_entreprise_tache(tache_id: int) -> None:
    """Background job — scoring IA d'une tâche d'entreprise."""
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        t = (
            await db.execute(
                select(EntrepriseTache).where(EntrepriseTache.id == tache_id)
            )
        ).scalar_one_or_none()
        if t is None:
            return
        # Skip si déjà scorée (manuel ou autre).
        if (
            t.impact is not None
            or t.confidence is not None
            or t.effort is not None
        ):
            return
        ent = (
            await db.execute(
                select(Entreprise).where(Entreprise.id == t.entreprise_id)
            )
        ).scalar_one_or_none()
        prompt = _build_prompt(
            title=t.title,
            description=t.description,
            departement=t.departement,
            due_date=t.due_date,
            context_name=ent.name if ent else None,
            context_description=ent.description if ent else None,
        )
        scored = await _ai_score(prompt)
        if scored is None:
            return
        impact, confidence, effort = scored
        t.impact = impact
        t.confidence = confidence
        t.effort = effort
        await db.commit()


async def autoscore_deal_task(task_id: int) -> None:
    """Background job — scoring IA d'une tâche de deal Pipeline."""
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        t = (
            await db.execute(
                select(ProspectionDealTask).where(
                    ProspectionDealTask.id == task_id
                )
            )
        ).scalar_one_or_none()
        if t is None:
            return
        if (
            t.impact is not None
            or t.confidence is not None
            or t.effort is not None
        ):
            return
        deal = (
            await db.execute(
                select(ProspectionDeal).where(
                    ProspectionDeal.id == t.deal_id
                )
            )
        ).scalar_one_or_none()
        prompt = _build_prompt(
            title=t.name,
            description=t.notes,
            departement=t.departement,
            due_date=t.due_date,
            context_name=f"Deal · {deal.address}" if deal else None,
            context_description=None,
        )
        scored = await _ai_score(prompt)
        if scored is None:
            return
        impact, confidence, effort = scored
        t.impact = impact
        t.confidence = confidence
        t.effort = effort
        await db.commit()
