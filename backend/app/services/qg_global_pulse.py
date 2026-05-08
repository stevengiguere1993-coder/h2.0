"""Briefing IA global — synthèse cross-entreprise pour la vue
agrégée Tâches (sous Navigation > Gestion d'entreprise).

Différent du daily-pulse par-entreprise : un seul briefing pour
l'ensemble des entreprises actives + des deals Pipeline ouverts.
Pas de persistance ; cache en mémoire pour une journée (regénération
explicite via ?force=true).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.ai import (
    AIProviderError,
    AIProviderUnavailable,
    complete,
)
from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.models.entreprise_tache_assignee import EntrepriseTacheAssignee
from app.models.prospection_deal import ProspectionDeal
from app.models.prospection_deal_task import ProspectionDealTask
from app.models.prospection_deal_task_assignee import (
    ProspectionDealTaskAssignee,
)

log = logging.getLogger(__name__)

PROMPT_VERSION = "global-pulse@v1"
SYSTEM_PROMPT = (
    "Tu es l'assistant stratégique d'un dirigeant qui supervise "
    "plusieurs entreprises et un pipeline d'acquisition immobilière. "
    "Tu rédiges un briefing matinal en français québécois, factuel "
    "et orienté action. Pas de flatterie. Si peu de données, dis-le."
)


@dataclass
class GlobalBriefing:
    period_start: datetime
    period_end: datetime
    headline: str
    summary_text: str
    highlights: List[str]
    model_used: Optional[str]
    provider: Optional[str]
    created_at: datetime


# Cache en mémoire. Clé = date_iso (briefing global) ou
# `date_iso:user:{id}` (briefing scopé à un user). Recyclé au boot.
_CACHE: dict[str, GlobalBriefing] = {}


def _format_taches(taches: list[EntrepriseTache]) -> str:
    if not taches:
        return "(aucune)"
    lines = []
    for t in taches[:25]:
        score = ""
        if t.impact and t.confidence and t.effort:
            s = (t.impact * t.confidence) / max(t.effort, 1)
            score = f" [score {s:.1f}]"
        due = ""
        if t.due_date:
            delta = (t.due_date - date.today()).days
            if delta < 0:
                due = f" ⚠ EN RETARD ({-delta}j)"
            elif delta == 0:
                due = " ⚠ DUE AUJOURD'HUI"
            elif delta <= 7:
                due = f" (dans {delta}j)"
        lines.append(f"- {t.title}{score}{due}")
    if len(taches) > 25:
        lines.append(f"… et {len(taches) - 25} autre(s)")
    return "\n".join(lines)


def _format_deal_taches(taches: list[ProspectionDealTask]) -> str:
    if not taches:
        return "(aucune)"
    lines = []
    for t in taches[:25]:
        due = ""
        if t.due_date:
            delta = (t.due_date - date.today()).days
            if delta < 0:
                due = f" ⚠ EN RETARD ({-delta}j)"
            elif delta == 0:
                due = " ⚠ DUE AUJOURD'HUI"
        lines.append(f"- {t.name}{due}")
    if len(taches) > 25:
        lines.append(f"… et {len(taches) - 25} autre(s)")
    return "\n".join(lines)


def _build_prompt(
    *,
    entreprises: list[Entreprise],
    open_taches_by_ent: dict[int, list[EntrepriseTache]],
    done_yesterday_by_ent: dict[int, list[EntrepriseTache]],
    deals_open_taches: list[ProspectionDealTask],
    deals_count: int,
    user_scoped: bool = False,
) -> str:
    parts = ["## Périmètre"]
    if user_scoped:
        parts.append(
            "**Périmètre filtré : uniquement les tâches assignées à "
            "l'utilisateur connecté.** Le briefing porte exclusivement "
            "sur ses dossiers personnels."
        )
    parts.append(
        f"{len(entreprises)} entreprise(s) active(s), "
        f"{deals_count} deal(s) actif(s) au Pipeline."
    )
    parts.append("\n## Tâches OUVERTES par entreprise")
    for ent in entreprises:
        opened = open_taches_by_ent.get(ent.id, [])
        if not opened:
            continue
        parts.append(f"\n### {ent.name} ({len(opened)})")
        parts.append(_format_taches(opened))

    parts.append("\n## Tâches TERMINÉES hier (toutes entreprises)")
    flat_done = [
        t for ts in done_yesterday_by_ent.values() for t in ts
    ]
    parts.append(_format_taches(flat_done))

    parts.append("\n## Tâches OUVERTES côté Pipeline (deals)")
    parts.append(_format_deal_taches(deals_open_taches))

    parts.append(
        "\n## Demande\n"
        "Rédige un briefing matinal global en JSON strict avec :\n"
        '  "headline" (string, max 120 caractères, accroche du jour)\n'
        '  "summary" (string, 4-6 phrases concises — vue d\'ensemble '
        "cross-entreprise + deals)\n"
        '  "highlights" (array de 4-6 strings, faits saillants ou '
        "actions à prioriser, format puce courte)\n"
        "Réponds UNIQUEMENT avec le JSON, sans markdown autour."
    )
    return "\n".join(parts)


def _parse_ai_json(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = "\n".join(s.split("\n")[1:])
        if s.endswith("```"):
            s = s[:-3]
    return json.loads(s.strip())


async def get_or_generate_global_pulse(
    db: AsyncSession,
    *,
    force: bool = False,
    user_id: Optional[int] = None,
) -> Optional[GlobalBriefing]:
    """Retourne le briefing global du jour. Génère via l'IA si
    absent du cache ou force=True. None si IA indisponible.

    Si `user_id` est fourni, le périmètre est filtré aux **tâches
    assignées à ce user** (entreprise + deals) — utilisé par le
    bouton « Mes tâches » de la page agrégée Tâches. Cache distinct
    par user pour éviter le crosstalk.
    """
    today = datetime.now(timezone.utc).date()
    cache_key = (
        f"{today.isoformat()}:user:{user_id}"
        if user_id is not None
        else today.isoformat()
    )
    if not force and cache_key in _CACHE:
        return _CACHE[cache_key]

    entreprises = list(
        (
            await db.execute(
                select(Entreprise)
                .where(Entreprise.is_active.is_(True))
                .order_by(Entreprise.name.asc())
            )
        ).scalars().all()
    )
    if not entreprises:
        return None

    ent_ids = [e.id for e in entreprises]

    # Filtre user : seulement les tâches assignées à ce user.
    # On considère deux sources : `assignee_user_id` (scalaire legacy
    # = primary) et la table `entreprise_tache_assignees` (multi).
    user_tache_ids: Optional[set[int]] = None
    user_deal_task_ids: Optional[set[int]] = None
    if user_id is not None:
        # IDs de tâches entreprise auxquelles ce user est assigné
        # (via le multi-assignees ou le scalaire legacy).
        multi_ids = (
            await db.execute(
                select(EntrepriseTacheAssignee.tache_id).where(
                    EntrepriseTacheAssignee.user_id == user_id
                )
            )
        ).scalars().all()
        legacy_ids = (
            await db.execute(
                select(EntrepriseTache.id).where(
                    EntrepriseTache.assignee_user_id == user_id
                )
            )
        ).scalars().all()
        user_tache_ids = set(multi_ids) | set(legacy_ids)

        # IDs de tâches deal assignées.
        deal_multi = (
            await db.execute(
                select(ProspectionDealTaskAssignee.task_id).where(
                    ProspectionDealTaskAssignee.user_id == user_id
                )
            )
        ).scalars().all()
        deal_legacy = (
            await db.execute(
                select(ProspectionDealTask.id).where(
                    ProspectionDealTask.assignee_user_id == user_id
                )
            )
        ).scalars().all()
        user_deal_task_ids = set(deal_multi) | set(deal_legacy)

    open_q = select(EntrepriseTache).where(
        EntrepriseTache.entreprise_id.in_(ent_ids),
        EntrepriseTache.status.in_(
            [
                TacheStatus.TODO.value,
                TacheStatus.A_FAIRE.value,
                TacheStatus.IN_PROGRESS.value,
                TacheStatus.WAITING.value,
            ]
        ),
    )
    if user_tache_ids is not None:
        if not user_tache_ids:
            open_taches = []
        else:
            open_taches = list(
                (
                    await db.execute(
                        open_q.where(EntrepriseTache.id.in_(user_tache_ids))
                    )
                ).scalars().all()
            )
    else:
        open_taches = list((await db.execute(open_q)).scalars().all())
    open_by_ent: dict[int, list[EntrepriseTache]] = {}
    for t in open_taches:
        open_by_ent.setdefault(t.entreprise_id, []).append(t)

    yesterday = today - timedelta(days=1)
    yest_start = datetime.combine(yesterday, dtime.min, tzinfo=timezone.utc)
    today_start = datetime.combine(today, dtime.min, tzinfo=timezone.utc)
    done_q = select(EntrepriseTache).where(
        EntrepriseTache.entreprise_id.in_(ent_ids),
        EntrepriseTache.status == TacheStatus.DONE.value,
        EntrepriseTache.completed_at >= yest_start,
        EntrepriseTache.completed_at < today_start,
    )
    if user_tache_ids is not None:
        if not user_tache_ids:
            done_yest = []
        else:
            done_yest = list(
                (
                    await db.execute(
                        done_q.where(EntrepriseTache.id.in_(user_tache_ids))
                    )
                ).scalars().all()
            )
    else:
        done_yest = list((await db.execute(done_q)).scalars().all())
    done_by_ent: dict[int, list[EntrepriseTache]] = {}
    for t in done_yest:
        done_by_ent.setdefault(t.entreprise_id, []).append(t)

    # Deals Pipeline actifs (priority != termine/abandonne).
    active_deals = list(
        (
            await db.execute(
                select(ProspectionDeal).where(
                    ~ProspectionDeal.priority.in_(["termine", "abandonne"])
                )
            )
        ).scalars().all()
    )
    deal_ids = [d.id for d in active_deals]
    deal_open_taches: list[ProspectionDealTask] = []
    if deal_ids:
        deal_q = select(ProspectionDealTask).where(
            ProspectionDealTask.deal_id.in_(deal_ids),
            ProspectionDealTask.status.in_(
                ["todo", "a_faire", "in_progress", "waiting"]
            ),
        )
        if user_deal_task_ids is not None:
            if not user_deal_task_ids:
                deal_open_taches = []
            else:
                deal_open_taches = list(
                    (
                        await db.execute(
                            deal_q.where(
                                ProspectionDealTask.id.in_(user_deal_task_ids)
                            )
                        )
                    ).scalars().all()
                )
        else:
            deal_open_taches = list(
                (await db.execute(deal_q)).scalars().all()
            )

    prompt = _build_prompt(
        entreprises=entreprises,
        open_taches_by_ent=open_by_ent,
        done_yesterday_by_ent=done_by_ent,
        deals_open_taches=deal_open_taches,
        deals_count=len(active_deals),
        user_scoped=user_id is not None,
    )

    t0 = time.perf_counter()
    try:
        res = await complete(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=700,
            temperature=0.4,
        )
    except (AIProviderUnavailable, AIProviderError) as exc:
        log.warning("Global pulse AI failed: %s", exc)
        return None

    duration_ms = int((time.perf_counter() - t0) * 1000)

    try:
        parsed = _parse_ai_json(res.text)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Global pulse JSON parse failed: %s — raw: %s",
            exc,
            res.text[:200],
        )
        first_line = res.text.strip().split("\n", 1)[0][:120]
        parsed = {
            "headline": first_line or "Briefing global",
            "summary": res.text.strip(),
            "highlights": [],
        }

    headline = str(parsed.get("headline") or "").strip()[:500]
    summary_text = str(parsed.get("summary") or "").strip()
    highlights = parsed.get("highlights") or []
    if not isinstance(highlights, list):
        highlights = [str(highlights)]
    highlights = [str(h)[:300] for h in highlights[:8]]

    period_start = today_start
    period_end = today_start + timedelta(days=1)

    brief = GlobalBriefing(
        period_start=period_start,
        period_end=period_end,
        headline=headline or "Briefing global",
        summary_text=summary_text or "(résumé indisponible)",
        highlights=highlights,
        model_used=res.model,
        provider=res.provider,
        created_at=datetime.now(timezone.utc),
    )
    _CACHE[cache_key] = brief
    log.info(
        "Global pulse generated in %d ms (provider=%s, model=%s)",
        duration_ms,
        res.provider,
        res.model,
    )
    return brief
