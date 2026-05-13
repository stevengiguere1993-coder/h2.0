"""Kratos — détecteur proactif de problèmes par entreprise.

Pour chaque entreprise, l'IA reçoit l'état (tâches en cours / en
retard, activités, visions, projets stratégiques) et produit 3 à 5
problèmes détectés avec une action suggérée pour chacun.

Format de l'action :
  - kind="create_task" : params { title, description?, priority? }
    → bouton « Créer la tâche » dans l'UI exécute la création.
  - kind="schedule_review" / "send_reminder" / "manual" : pas d'action
    automatique, juste un texte d'orientation.

Idempotence : on supprime les problèmes "open" plus vieux qu'une
semaine avant de regénérer, pour éviter l'accumulation. Les
problèmes appliqués ou rejetés sont conservés.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.models.kratos_problem import (
    KratosProblem,
    KratosProblemSeverity,
    KratosProblemStatus,
)
from app.models.qg_strategic import Activity, StrategicProject, Vision


log = logging.getLogger(__name__)


MODEL = "claude-sonnet-4-6"


SYSTEM_PROMPT = """Tu es Kratos, l'analyste stratégique d'un dirigeant \
qui gère plusieurs entreprises (immobilier, construction, gestion). \
Tu reçois l'état d'une entreprise (tâches, activités, visions, \
projets) et tu détectes 3 à 5 PROBLÈMES concrets qui freinent sa \
croissance, ainsi qu'une SOLUTION actionnable pour chacun.

Tu réponds UNIQUEMENT en JSON strict :
{
  "problems": [
    {
      "title": "Titre court max 100 caractères",
      "description": "Pourquoi c'est un problème (1-2 phrases)",
      "severity": "low" | "medium" | "high",
      "action_kind": "create_task" | "schedule_review" | "send_reminder" | "manual",
      "action_label": "Texte du bouton (max 60 car)",
      "action_params": { ... }  // pour create_task : { "title", "description"?, "priority"? "high"|"medium"|"low" }
    }
  ]
}

Règles :
- Tu produis TOUJOURS au moins 3 problèmes même si l'activité \
récente est faible. Dans ce cas pivote sur : tâches non-bougées \
depuis longtemps, vision pas claire, manque de revenus, processus à \
formaliser, recrutement, marketing, partenariats inactifs.
- Chaque problème doit être ACTIONNABLE — pas de constats vagues.
- Si tu peux proposer une tâche à créer immédiatement, fais-le avec \
action_kind="create_task" et action_params={"title":"…"}.
- severity reflète l'impact : high = bloque la croissance, medium = \
ralentit, low = optimisation."""


def _format_taches(taches: list[EntrepriseTache]) -> str:
    if not taches:
        return "(aucune)"
    lines = []
    today = date.today()
    for t in taches[:30]:
        score = ""
        if t.impact and t.confidence and t.effort:
            s = (t.impact * t.confidence) / max(t.effort, 1)
            score = f" [score {s:.1f}]"
        age = ""
        if t.created_at:
            days = (
                datetime.now(timezone.utc) - t.created_at.replace(tzinfo=timezone.utc)
            ).days if t.created_at.tzinfo is None else (
                datetime.now(timezone.utc) - t.created_at
            ).days
            if days > 30:
                age = f" — créée il y a {days}j"
        due = ""
        if t.due_date:
            delta = (t.due_date - today).days
            if delta < 0:
                due = f" — EN RETARD ({-delta}j)"
            elif delta == 0:
                due = " — DUE AUJOURD'HUI"
        status = t.status
        lines.append(f"- [{status}] {t.title}{score}{due}{age}")
    return "\n".join(lines)


def _format_visions(visions: list[Vision]) -> str:
    if not visions:
        return "(aucune vision enregistrée)"
    return "\n".join(
        f"- [{v.horizon_label}] {v.title} — {v.narrative[:200]}"
        for v in visions[:5]
    )


def _format_projects(projects: list[StrategicProject]) -> str:
    if not projects:
        return "(aucun projet stratégique)"
    return "\n".join(
        f"- [{getattr(p, 'status', '?')}] {getattr(p, 'title', '?')}"
        for p in projects[:10]
    )


def _format_activities(acts: list[Activity]) -> str:
    if not acts:
        return "(aucune)"
    return "\n".join(
        f"- [{a.kind}] {a.title}"
        for a in acts[:20]
    )


async def _gather_state(
    db: AsyncSession, entreprise_id: int
) -> dict:
    """Collecte l'état complet d'une entreprise pour analyse IA."""
    todo = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.entreprise_id == entreprise_id,
                EntrepriseTache.status.in_(
                    [TacheStatus.TODO.value, TacheStatus.IN_PROGRESS.value]
                ),
            ).limit(50)
        )
    ).scalars().all()
    today = date.today()
    overdue = [t for t in todo if t.due_date and t.due_date < today]
    visions = (
        await db.execute(
            select(Vision)
            .where(Vision.entreprise_id == entreprise_id)
            .where(Vision.horizon_end >= today)
            .order_by(Vision.horizon_end.asc())
            .limit(5)
        )
    ).scalars().all()
    projects = (
        await db.execute(
            select(StrategicProject)
            .where(StrategicProject.entreprise_id == entreprise_id)
            .order_by(StrategicProject.updated_at.desc())
            .limit(10)
        )
    ).scalars().all()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    acts = (
        await db.execute(
            select(Activity)
            .where(Activity.entreprise_id == entreprise_id)
            .where(Activity.occurred_at >= week_ago)
            .order_by(Activity.occurred_at.desc())
            .limit(30)
        )
    ).scalars().all()
    return {
        "todo": list(todo),
        "overdue": list(overdue),
        "visions": list(visions),
        "projects": list(projects),
        "activities": list(acts),
    }


async def _call_claude(entreprise: Entreprise, state: dict) -> list[dict]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY non configuré.")
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    parts = [
        f"## Entreprise\n{entreprise.name}",
        f"Description : {entreprise.description or '(aucune)'}",
        f"## Tâches actives ({len(state['todo'])} dont {len(state['overdue'])} en retard)\n"
        + _format_taches(state["todo"]),
        "## Visions stratégiques\n" + _format_visions(state["visions"]),
        "## Projets stratégiques\n" + _format_projects(state["projects"]),
        "## Activités 7 derniers jours\n" + _format_activities(state["activities"]),
        "## Demande\nDétecte 3 à 5 problèmes selon le schéma JSON.",
    ]
    user_prompt = "\n\n".join(parts)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = "\n".join(b.text for b in msg.content if b.type == "text").strip()
    if raw.startswith("```"):
        import re

        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    parsed = json.loads(raw)
    return list(parsed.get("problems") or [])


async def detect_for_entreprise(
    db: AsyncSession,
    entreprise_id: int,
    *,
    force: bool = False,
) -> list[KratosProblem]:
    """Lance l'analyse et persiste les nouveaux problèmes.

    Si `force=False`, on saute si un scan a déjà tourné dans les
    dernières 24 h (un problem créé < 24 h). Sinon on regénère."""
    ent = (
        await db.execute(
            select(Entreprise).where(Entreprise.id == entreprise_id)
        )
    ).scalar_one_or_none()
    if ent is None or not ent.is_active:
        return []

    # Idempotence par 24 h.
    if not force:
        day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        recent = (
            await db.execute(
                select(KratosProblem).where(
                    KratosProblem.entreprise_id == entreprise_id,
                    KratosProblem.created_at >= day_ago,
                )
            )
        ).scalars().first()
        if recent is not None:
            # Retourne ce qui est ouvert pour cette entreprise.
            return list(
                (
                    await db.execute(
                        select(KratosProblem)
                        .where(
                            KratosProblem.entreprise_id == entreprise_id,
                            KratosProblem.status
                            == KratosProblemStatus.OPEN.value,
                        )
                        .order_by(KratosProblem.created_at.desc())
                    )
                ).scalars().all()
            )

    # Cleanup : supprime les "open" plus vieux qu'une semaine pour
    # éviter l'accumulation.
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    old_open = (
        await db.execute(
            select(KratosProblem).where(
                KratosProblem.entreprise_id == entreprise_id,
                KratosProblem.status == KratosProblemStatus.OPEN.value,
                KratosProblem.created_at < week_ago,
            )
        )
    ).scalars().all()
    for p in old_open:
        await db.delete(p)
    await db.flush()

    state = await _gather_state(db, entreprise_id)

    try:
        problems_raw = await _call_claude(ent, state)
    except Exception as exc:  # noqa: BLE001
        log.warning("Kratos problem detector failed for %s: %s", ent.id, exc)
        return []

    created: list[KratosProblem] = []
    valid_sev = {s.value for s in KratosProblemSeverity}
    for p in problems_raw[:8]:
        title = str(p.get("title") or "").strip()[:255]
        if not title:
            continue
        severity = str(p.get("severity") or "medium").lower()
        if severity not in valid_sev:
            severity = KratosProblemSeverity.MEDIUM.value
        action_kind = str(p.get("action_kind") or "manual").strip()[:48]
        action_params = p.get("action_params") or {}
        problem = KratosProblem(
            entreprise_id=entreprise_id,
            title=title,
            description=str(p.get("description") or "")[:2000],
            severity=severity,
            suggested_action_kind=action_kind,
            suggested_action_label=str(p.get("action_label") or "")[:255]
            or None,
            suggested_action_params=json.dumps(action_params, default=str)[
                :2000
            ],
            status=KratosProblemStatus.OPEN.value,
        )
        db.add(problem)
        created.append(problem)
    await db.flush()
    return created


async def apply_solution(
    db: AsyncSession,
    problem_id: int,
    user_id: Optional[int] = None,
) -> Optional[KratosProblem]:
    """Applique la solution suggérée. Pour `create_task`, crée
    l'EntrepriseTache et marque le problème applied."""
    problem = (
        await db.execute(
            select(KratosProblem).where(KratosProblem.id == problem_id)
        )
    ).scalar_one_or_none()
    if problem is None:
        return None
    if problem.status != KratosProblemStatus.OPEN.value:
        return problem

    if problem.suggested_action_kind == "create_task":
        try:
            params = (
                json.loads(problem.suggested_action_params)
                if problem.suggested_action_params
                else {}
            )
        except Exception:  # noqa: BLE001
            params = {}
        title = str(params.get("title") or problem.title)[:255]
        priority_map = {"high": 9, "medium": 6, "low": 3}
        prio = priority_map.get(
            str(params.get("priority") or "medium").lower(), 6
        )
        tache = EntrepriseTache(
            entreprise_id=problem.entreprise_id,
            title=title,
            description=(str(params.get("description") or problem.description or ""))[
                :5000
            ],
            status=TacheStatus.TODO.value,
            impact=prio,
            confidence=5,
            effort=3,
            created_by_user_id=user_id,
        )
        db.add(tache)
        await db.flush()
        problem.applied_target_type = "entreprise_tache"
        problem.applied_target_id = int(tache.id)

    problem.status = KratosProblemStatus.APPLIED.value
    problem.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return problem
