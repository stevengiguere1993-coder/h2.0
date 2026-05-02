"""Insights IA — détection de risques / opportunités / synergies.

Pour chaque entreprise active, l'IA analyse l'état (tâches en retard,
en cours, score moyen, dernier briefing, activités récentes) et
propose 0 à 5 insights structurés. Stockés dans qg_insights avec
cycle de vie new → acknowledged → in_action → resolved/dismissed.

Idempotence : on n'écrase jamais un insight ouvert. À chaque cycle,
on ferme automatiquement les insights expired (>14 jours sans action),
puis on génère de nouveaux insights basés sur l'état courant.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.ai import AIProviderError, AIProviderUnavailable, complete
from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.models.qg_strategic import (
    Insight,
    InsightStatus,
    InsightType,
    Summary,
    SummaryType,
)


log = logging.getLogger(__name__)

PROMPT_VERSION = "insights@v1"
SYSTEM_PROMPT = (
    "Tu es un consultant stratégique sénior. Tu analyses l'état "
    "courant d'une entreprise et tu identifies 1 à 5 insights "
    "actionables. Pas de banalités, pas de flatterie. Si tout va "
    "bien, dis-le et n'invente pas de risques."
)

VALID_TYPES = {t.value for t in InsightType}


async def _close_expired(db: AsyncSession, entreprise_id: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    rows = (
        await db.execute(
            select(Insight).where(
                Insight.entreprise_id == entreprise_id,
                Insight.status.in_([
                    InsightStatus.NEW.value,
                    InsightStatus.ACKNOWLEDGED.value,
                ]),
                Insight.created_at < cutoff,
            )
        )
    ).scalars().all()
    for r in rows:
        r.expires_at = datetime.now(timezone.utc)
        r.status = InsightStatus.DISMISSED.value


def _format_taches(taches: list[EntrepriseTache]) -> str:
    if not taches:
        return "(aucune)"
    out = []
    for t in taches[:30]:
        score = ""
        if t.impact and t.confidence and t.effort:
            s = (t.impact * t.confidence) / max(t.effort, 1)
            score = f" [score {s:.1f}]"
        due = ""
        if t.due_date:
            d = (t.due_date - date.today()).days
            if d < 0:
                due = f" RETARD {-d}j"
            elif d <= 7:
                due = f" dans {d}j"
        out.append(f"- {t.title}{score}{due}")
    return "\n".join(out)


def _build_prompt(
    *,
    ent: Entreprise,
    todo: list[EntrepriseTache],
    in_progress: list[EntrepriseTache],
    overdue: list[EntrepriseTache],
    last_summary: Optional[Summary],
) -> str:
    parts = [
        f"## Entreprise : {ent.name}",
    ]
    if ent.description:
        parts.append(f"Contexte : {ent.description}")
    parts.append(f"## Tâches À FAIRE\n{_format_taches(todo)}")
    parts.append(f"## Tâches EN COURS\n{_format_taches(in_progress)}")
    parts.append(f"## Tâches EN RETARD\n{_format_taches(overdue)}")
    if last_summary:
        parts.append(
            "## Dernier briefing (contexte)\n"
            f"{last_summary.headline}\n{last_summary.summary_text[:1000]}"
        )
    parts.append(
        "## Demande\n"
        "Identifie 1 à 5 insights stratégiques. Réponds STRICTEMENT en "
        "JSON sans markdown, format :\n"
        "{\n"
        '  "insights": [\n'
        "    {\n"
        '      "type": "risk|opportunity|synergy|anomaly|recommendation",\n'
        '      "title": "string max 200 char",\n'
        '      "body": "string 2-4 phrases",\n'
        '      "confidence": 0.0-1.0,\n'
        '      "suggested_actions": ["action 1", "action 2"],\n'
        '      "estimated_impact_label": "string court ex: 5k$/mois économisés",\n'
        '      "estimated_impact_currency": null ou nombre\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Si rien d'important : retourne `{\"insights\": []}`."
    )
    return "\n\n".join(parts)


def _parse(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = "\n".join(s.split("\n")[1:])
        if s.endswith("```"):
            s = s[:-3]
    return json.loads(s.strip())


async def generate_for_entreprise(
    db: AsyncSession,
    entreprise_id: int,
    *,
    force: bool = False,
) -> dict:
    """Génère des insights pour 1 entreprise. Retourne {created, kept,
    skipped, errors}."""
    ent = (
        await db.execute(
            select(Entreprise).where(Entreprise.id == entreprise_id)
        )
    ).scalar_one_or_none()
    if ent is None or not ent.is_active:
        return {"created": 0, "kept": 0, "skipped": 1, "errors": 0}

    await _close_expired(db, entreprise_id)

    # Sauf si force=True, on ne re-génère pas s'il y a déjà 3+ insights
    # ouverts pour ne pas spammer le user.
    if not force:
        n_open = (
            await db.execute(
                select(Insight).where(
                    Insight.entreprise_id == entreprise_id,
                    Insight.status.in_([
                        InsightStatus.NEW.value,
                        InsightStatus.ACKNOWLEDGED.value,
                        InsightStatus.IN_ACTION.value,
                    ]),
                )
            )
        ).scalars().all()
        if len(n_open) >= 3:
            return {
                "created": 0,
                "kept": len(n_open),
                "skipped": 1,
                "errors": 0,
            }

    today = date.today()
    todo = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.entreprise_id == entreprise_id,
                EntrepriseTache.status == TacheStatus.TODO.value,
            )
            .limit(20)
        )
    ).scalars().all()
    in_prog = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.entreprise_id == entreprise_id,
                EntrepriseTache.status == TacheStatus.IN_PROGRESS.value,
            )
            .limit(20)
        )
    ).scalars().all()
    overdue = [
        t for t in (todo + in_prog)
        if t.due_date is not None and t.due_date < today
    ]
    last_summary = (
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

    prompt = _build_prompt(
        ent=ent,
        todo=list(todo),
        in_progress=list(in_prog),
        overdue=overdue,
        last_summary=last_summary,
    )

    try:
        res = await complete(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=900,
            temperature=0.4,
        )
    except (AIProviderUnavailable, AIProviderError) as exc:
        log.warning(
            "Insights AI failed for entreprise %d: %s",
            entreprise_id,
            exc,
        )
        return {"created": 0, "kept": 0, "skipped": 0, "errors": 1}

    try:
        parsed = _parse(res.text)
        items = parsed.get("insights") or []
        if not isinstance(items, list):
            items = []
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Insights parse failed for entreprise %d: %s — raw: %s",
            entreprise_id,
            exc,
            res.text[:200],
        )
        return {"created": 0, "kept": 0, "skipped": 0, "errors": 1}

    created = 0
    for it in items[:5]:
        try:
            t_val = str(it.get("type") or "recommendation").lower()
            if t_val not in VALID_TYPES:
                t_val = InsightType.RECOMMENDATION.value
            title = str(it.get("title") or "").strip()[:500]
            body = str(it.get("body") or "").strip()
            if not title or not body:
                continue
            conf = it.get("confidence")
            confidence = (
                float(conf) if isinstance(conf, (int, float)) else None
            )
            if confidence is not None:
                confidence = max(0.0, min(1.0, confidence))
            actions = it.get("suggested_actions") or []
            if not isinstance(actions, list):
                actions = [str(actions)]
            actions = [str(a)[:300] for a in actions[:5]]
            impact_label = str(it.get("estimated_impact_label") or "")[:255] or None
            impact_curr = it.get("estimated_impact_currency")
            if not isinstance(impact_curr, (int, float)):
                impact_curr = None

            ins = Insight(
                entreprise_id=entreprise_id,
                type=t_val,
                status=InsightStatus.NEW.value,
                title=title,
                body=body,
                confidence=confidence,
                suggested_actions_json=json.dumps(actions, ensure_ascii=False),
                estimated_impact_label=impact_label,
                estimated_impact_currency=impact_curr,
                source_summary_id=last_summary.id if last_summary else None,
            )
            db.add(ins)
            created += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("Skipping insight item: %s", exc)
            continue

    await db.flush()
    return {
        "created": created,
        "kept": 0,
        "skipped": 0,
        "errors": 0,
    }


async def generate_for_all_active(db: AsyncSession, *, force: bool = False) -> dict:
    rows = (
        await db.execute(
            select(Entreprise).where(Entreprise.is_active.is_(True))
        )
    ).scalars().all()
    out = {"total": len(rows), "created": 0, "errors": 0}
    for e in rows:
        try:
            r = await generate_for_entreprise(db, e.id, force=force)
            out["created"] += r.get("created", 0)
            out["errors"] += r.get("errors", 0)
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "Insights error for entreprise %d: %s", e.id, exc
            )
            out["errors"] += 1
    return out
