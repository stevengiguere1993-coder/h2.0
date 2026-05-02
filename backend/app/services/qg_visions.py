"""Visions stratégiques par horizon (7 jours / 30 jours / 90 jours).

Pour une entreprise donnée, l'IA produit :
- title court (200 char max)
- narrative (3-5 phrases)
- objectives : 3-5 objectifs SMART
- key_actions : 3-7 actions concrètes pour les atteindre

Différent des insights : la vision est globale, narrative, projetée
dans le futur. Les insights sont ponctuels et réactifs.

Idempotent : un horizon = un slot. Re-générer écrase.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.ai import AIProviderError, AIProviderUnavailable, complete
from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.models.qg_strategic import (
    Insight,
    InsightStatus,
    Summary,
    SummaryType,
    Vision,
)


log = logging.getLogger(__name__)


HORIZONS = {
    "7j": ("7 jours", 7),
    "30j": ("30 jours", 30),
    "90j": ("90 jours", 90),
    "12m": ("12 mois", 365),
}


SYSTEM_PROMPT = (
    "Tu es un consultant stratégique sénior. Tu rédiges une vision "
    "concise et actionable pour un horizon donné. Tu te bases "
    "uniquement sur l'état actuel de l'entreprise — pas de "
    "projection magique. Français québécois."
)


def _parse(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = "\n".join(s.split("\n")[1:])
        if s.endswith("```"):
            s = s[:-3]
    return json.loads(s.strip())


async def generate_vision(
    db: AsyncSession,
    entreprise_id: int,
    *,
    horizon_key: str,
    force: bool = False,
) -> Optional[Vision]:
    """Génère ou retourne la vision pour un horizon ('7j', '30j', '90j',
    '12m'). Idempotent : si une vision existe déjà pour cet horizon
    (overlap des dates), on retourne celle-là sauf si force=True."""
    if horizon_key not in HORIZONS:
        raise ValueError(f"Horizon invalide : {horizon_key}")
    label, days = HORIZONS[horizon_key]

    ent = (
        await db.execute(
            select(Entreprise).where(Entreprise.id == entreprise_id)
        )
    ).scalar_one_or_none()
    if ent is None or not ent.is_active:
        return None

    today = date.today()
    horizon_end = today + timedelta(days=days)

    # Vision existante pour ce label sur la dernière période
    existing = (
        await db.execute(
            select(Vision)
            .where(
                Vision.entreprise_id == entreprise_id,
                Vision.horizon_label == label,
            )
            .order_by(Vision.horizon_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if existing is not None and not force:
        # Si la vision est encore valide (créée < 7 jours), on la garde.
        age = (today - existing.horizon_start).days
        if age < 7:
            return existing

    # Contexte : tâches ouvertes, derniers insights ouverts, dernier
    # briefing.
    todo = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.entreprise_id == entreprise_id,
                EntrepriseTache.status.in_(
                    [TacheStatus.TODO.value, TacheStatus.IN_PROGRESS.value]
                ),
            )
            .limit(30)
        )
    ).scalars().all()
    insights = (
        await db.execute(
            select(Insight).where(
                Insight.entreprise_id == entreprise_id,
                Insight.status.in_(
                    [
                        InsightStatus.NEW.value,
                        InsightStatus.ACKNOWLEDGED.value,
                        InsightStatus.IN_ACTION.value,
                    ]
                ),
            )
            .order_by(Insight.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    last_briefing = (
        await db.execute(
            select(Summary)
            .where(
                Summary.entreprise_id == entreprise_id,
                Summary.type == SummaryType.DAILY_BRIEFING.value,
            )
            .order_by(Summary.period_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    parts = [
        f"## Entreprise : {ent.name}",
    ]
    if ent.description:
        parts.append(f"Contexte : {ent.description}")
    parts.append(f"## Horizon visé : {label} (jusqu'au {horizon_end.isoformat()})")
    if todo:
        items = []
        for t in todo[:20]:
            score = ""
            if t.impact and t.confidence and t.effort:
                s = (t.impact * t.confidence) / max(t.effort, 1)
                score = f" [score {s:.1f}]"
            items.append(f"- {t.title}{score}")
        parts.append(
            "## Tâches ouvertes\n" + "\n".join(items)
        )
    if insights:
        items = [f"- [{i.type}] {i.title}" for i in insights]
        parts.append("## Insights actifs\n" + "\n".join(items))
    if last_briefing:
        parts.append(
            f"## Dernier briefing\n{last_briefing.headline}\n"
            f"{last_briefing.summary_text[:800]}"
        )

    parts.append(
        "## Demande\n"
        "Rédige une vision stratégique pour cet horizon. Réponds en "
        "JSON STRICT (sans markdown) avec :\n"
        "{\n"
        '  "title": "string max 200 char, accroche directionnelle",\n'
        '  "narrative": "3-5 phrases qui décrivent où on veut être à la fin de l\'horizon",\n'
        '  "objectives": ["objectif SMART 1", ...] (3-5 entrées),\n'
        '  "key_actions": ["action concrète 1", ...] (3-7 entrées)\n'
        "}"
    )
    prompt = "\n\n".join(parts)

    try:
        res = await complete(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=900,
            temperature=0.4,
        )
    except (AIProviderUnavailable, AIProviderError) as exc:
        log.warning(
            "Vision AI failed for entreprise %d horizon %s: %s",
            entreprise_id,
            horizon_key,
            exc,
        )
        return None

    try:
        parsed = _parse(res.text)
        title = str(parsed.get("title") or "").strip()[:500]
        narrative = str(parsed.get("narrative") or "").strip()
        objectives = parsed.get("objectives") or []
        if not isinstance(objectives, list):
            objectives = []
        objectives = [str(o)[:500] for o in objectives[:8]]
        key_actions = parsed.get("key_actions") or []
        if not isinstance(key_actions, list):
            key_actions = []
        key_actions = [str(a)[:500] for a in key_actions[:10]]
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Vision parse failed for entreprise %d : %s — raw: %s",
            entreprise_id,
            exc,
            res.text[:200],
        )
        return None

    if not title or not narrative:
        return None

    if existing is not None and force:
        existing.horizon_start = today
        existing.horizon_end = horizon_end
        existing.title = title
        existing.narrative = narrative
        existing.objectives_json = json.dumps(objectives, ensure_ascii=False)
        existing.key_actions_json = json.dumps(key_actions, ensure_ascii=False)
        existing.generated_by_ai = True
        existing.approved_by_user_id = None
        existing.approved_at = None
        await db.flush()
        return existing

    v = Vision(
        entreprise_id=entreprise_id,
        horizon_label=label,
        horizon_start=today,
        horizon_end=horizon_end,
        title=title,
        narrative=narrative,
        objectives_json=json.dumps(objectives, ensure_ascii=False),
        key_actions_json=json.dumps(key_actions, ensure_ascii=False),
        generated_by_ai=True,
    )
    db.add(v)
    await db.flush()
    await db.refresh(v)
    return v
