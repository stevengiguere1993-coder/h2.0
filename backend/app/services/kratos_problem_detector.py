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


def _detect_problems_locally(entreprise: Entreprise, state: dict) -> list[dict]:
    """Fallback heuristique sans IA. Produit 3-5 problèmes basés sur
    des règles dures à partir de l'état de l'entreprise."""
    problems: list[dict] = []
    today = date.today()
    todo = state.get("todo") or []
    overdue = state.get("overdue") or []
    visions = state.get("visions") or []
    projects = state.get("projects") or []
    activities = state.get("activities") or []

    # 1. Tâches en retard
    for t in overdue[:3]:
        days = (today - t.due_date).days if t.due_date else 0
        problems.append(
            {
                "title": f"Tâche en retard : {t.title[:80]}",
                "description": (
                    f"Cette tâche est due depuis {days} jour"
                    f"{'s' if days > 1 else ''}. Statut actuel : {t.status}."
                ),
                "severity": "high" if days > 7 else "medium",
                "action_kind": "create_task",
                "action_label": "Relancer cette tâche",
                "action_params": {
                    "title": f"Relancer : {t.title[:100]}",
                    "description": (
                        f"Tâche en retard depuis {days} jour(s) — "
                        f"décider de la fermer ou de l'avancer."
                    ),
                    "priority": "high",
                },
            }
        )

    # 2. Tâches stagnantes (créées il y a > 30 jours, toujours TODO)
    stagnant = []
    for t in todo:
        if t.created_at and t.status == "todo":
            created = t.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - created).days
            if age_days > 30 and t not in overdue:
                stagnant.append((t, age_days))
    if stagnant:
        stagnant.sort(key=lambda x: -x[1])
        for t, age in stagnant[:2]:
            problems.append(
                {
                    "title": f"Tâche stagnante depuis {age}j : {t.title[:80]}",
                    "description": (
                        f"Cette tâche est restée « à faire » depuis {age} "
                        "jours sans activité. À fermer, à reprioriser ou à "
                        "déléguer."
                    ),
                    "severity": "medium",
                    "action_kind": "manual",
                    "action_label": "Décider du sort",
                    "action_params": {},
                }
            )

    # 3. Pas d'activité récente
    if not activities and not problems:
        problems.append(
            {
                "title": "Aucune activité enregistrée depuis 7 jours",
                "description": (
                    "Aucun mouvement noté pour cette entreprise dans la "
                    "dernière semaine. Planifie au minimum les 3 tâches "
                    "prioritaires de la semaine pour reprendre le momentum."
                ),
                "severity": "medium",
                "action_kind": "create_task",
                "action_label": "Planifier la semaine",
                "action_params": {
                    "title": "Planifier les 3 priorités de la semaine",
                    "description": (
                        "Lister les 3 actions concrètes à pousser cette "
                        "semaine pour faire avancer l'entreprise."
                    ),
                    "priority": "medium",
                },
            }
        )

    # 4. Vision absente
    if not visions:
        problems.append(
            {
                "title": "Vision stratégique à formaliser",
                "description": (
                    "Aucune vision active enregistrée pour cette entreprise. "
                    "Sans cap clair sur 30/90 jours, les tâches dérivent et "
                    "le suivi devient réactif."
                ),
                "severity": "medium",
                "action_kind": "create_task",
                "action_label": "Rédiger la vision 90 jours",
                "action_params": {
                    "title": "Rédiger la vision stratégique 90 jours",
                    "description": (
                        "Définir le cap court terme : 3 objectifs clés et "
                        "les indicateurs pour les suivre."
                    ),
                    "priority": "medium",
                },
            }
        )

    # 5. Aucun projet stratégique en cours
    if not projects and len(problems) < 5:
        problems.append(
            {
                "title": "Aucun projet stratégique actif",
                "description": (
                    "Pas de chantier structurant en cours pour faire grandir "
                    "cette entreprise. Identifie 1 projet ambitieux à lancer "
                    "ce mois-ci (marketing, recrutement, processus, offre)."
                ),
                "severity": "low",
                "action_kind": "create_task",
                "action_label": "Identifier 1 projet à lancer",
                "action_params": {
                    "title": "Identifier 1 projet stratégique du mois",
                    "description": (
                        "Choisir un chantier interne ou commercial à "
                        "lancer ce mois-ci avec un impact mesurable."
                    ),
                    "priority": "medium",
                },
            }
        )

    # 6. Beaucoup de tâches ouvertes → focus
    if len(todo) > 15 and len(problems) < 5:
        problems.append(
            {
                "title": f"{len(todo)} tâches ouvertes — risque de dispersion",
                "description": (
                    "Trop de tâches ouvertes en parallèle réduit la "
                    "concentration. Sélectionne les 3-5 ICE les plus élevés "
                    "et reporte le reste."
                ),
                "severity": "low",
                "action_kind": "manual",
                "action_label": "Trier par score ICE",
                "action_params": {},
            }
        )

    # Garde-fou : au minimum 3 problèmes même si l'entreprise va bien.
    if len(problems) < 3:
        problems.append(
            {
                "title": f"Faire évoluer {entreprise.name}",
                "description": (
                    "État stable. Profite-en pour pousser un chantier de "
                    "fond : marketing, optimisation, recrutement ou "
                    "partenariats."
                ),
                "severity": "low",
                "action_kind": "create_task",
                "action_label": "Choisir un chantier de fond",
                "action_params": {
                    "title": "Choisir un chantier de fond ce mois-ci",
                    "description": (
                        "Marketing, optimisation, recrutement, partenariats — "
                        "identifier UN levier de croissance pour le mois."
                    ),
                    "priority": "medium",
                },
            }
        )

    return problems[:5]


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
        log.warning(
            "Kratos detector → fallback heuristique local pour %s : %s",
            ent.id,
            exc,
        )
        # Fallback heuristique : on génère des problèmes basés sur
        # l'état actuel (tâches en retard, stagnation, vision absente,
        # etc.) pour que Kratos continue à proposer des actions même
        # sans Claude.
        problems_raw = _detect_problems_locally(ent, state)

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


# ─── Mode user-driven : utilisateur décrit un problème, IA propose ─────


SOLVE_SYSTEM_PROMPT = """Tu es Kratos, le consultant interne du \
dirigeant. Tu reçois un problème décrit (ou dicté) par l'utilisateur \
et tu produis un plan d'action concret en t'appuyant sur :
- les entreprises qu'il dirige (noms, descriptions, état),
- son organigramme et ses ressources actuelles,
- les solutions externes possibles (outils, prestataires, processus),
- les leviers stratégiques classiques (offre, marketing, processus, \
recrutement, finance, partenariats).

Tu réponds UNIQUEMENT en JSON strict :
{
  "title": "Titre court max 120 caractères qui résume le problème",
  "severity": "low" | "medium" | "high",
  "entreprise_id": id numérique de l'entreprise principale concernée \
(parmi la liste fournie), ou null si transverse,
  "solution_plan": "Plan d'action narratif markdown — 3 à 6 \
paragraphes. Couvre : diagnostic court, leviers à activer, ressources \
internes à mobiliser, options externes à considérer, indicateurs de \
succès.",
  "steps": [
    {
      "title": "Étape 1 — Titre court",
      "description": "Quoi faire concrètement (1-2 phrases)",
      "entreprise_id": id ou null,
      "action_kind": "create_task" | "manual",
      "action_params": { "title": "...", "priority": "high"|"medium"|"low" }
    }
  ]
}

Règles :
- 3 à 6 étapes maximum.
- Pour chaque étape qui peut devenir une tâche d'entreprise, mets \
action_kind="create_task" avec un title clair et priority cohérente.
- N'invente pas de prestataires précis (« Atelier X ») — reste sur \
catégories de solutions (« cabinet comptable », « consultant Lean »).
- Sois pragmatique, pas théorique."""


async def _solve_with_claude(
    text: str, entreprises: list[Entreprise]
) -> Optional[dict]:
    """Appelle Claude pour générer un plan de solution. Retourne le
    dict parsé, ou None si l'IA est indisponible."""
    if not settings.anthropic_api_key:
        return None
    import anthropic

    ents_block = "\n".join(
        f"- #{e.id} {e.name} : {(e.description or '(pas de description)')[:200]}"
        for e in entreprises[:30]
    ) or "(aucune entreprise active)"

    user_prompt = (
        f"## Entreprises actives\n{ents_block}\n\n"
        f"## Problème décrit par le dirigeant\n{text.strip()}\n\n"
        "Génère le plan d'action JSON selon le schéma."
    )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=MODEL,
            max_tokens=2500,
            system=SOLVE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Kratos solve_problem failed: %s", exc)
        return None

    raw = "\n".join(b.text for b in msg.content if b.type == "text").strip()
    if raw.startswith("```"):
        import re

        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def _solve_locally(text: str, entreprises: list[Entreprise]) -> dict:
    """Fallback heuristique sans IA. Plan minimal qui invite à
    structurer le diagnostic et à attaquer le problème en 3 étapes."""
    title = (text.strip().split("\n", 1)[0] or "Problème à résoudre")[:120]
    ent_id = entreprises[0].id if entreprises else None
    return {
        "title": title,
        "severity": "medium",
        "entreprise_id": ent_id,
        "solution_plan": (
            "**Diagnostic à clarifier** — précise l'impact financier, "
            "humain et temporel du problème.\n\n"
            "**Leviers internes** — identifie quelle ressource de "
            "l'organigramme peut porter ce dossier en priorité.\n\n"
            "**Solutions externes** — si l'expertise manque, envisage "
            "un consultant, un outil SaaS ou un partenaire externe.\n\n"
            "**Indicateur de succès** — fixe un critère mesurable pour "
            "savoir quand le problème est résolu."
        ),
        "steps": [
            {
                "title": "Clarifier le diagnostic",
                "description": (
                    "Documenter le problème : qui, quoi, quand, "
                    "combien ça coûte si on ne le règle pas."
                ),
                "entreprise_id": ent_id,
                "action_kind": "create_task",
                "action_params": {
                    "title": f"Diagnostiquer : {title}",
                    "priority": "high",
                },
            },
            {
                "title": "Identifier le porteur du dossier",
                "description": (
                    "Décider qui dans l'équipe est responsable. Si "
                    "personne, prévoir un recrutement ou une "
                    "externalisation."
                ),
                "entreprise_id": ent_id,
                "action_kind": "create_task",
                "action_params": {
                    "title": "Assigner un porteur au dossier",
                    "priority": "medium",
                },
            },
            {
                "title": "Définir l'indicateur de succès",
                "description": (
                    "Préciser comment on saura que le problème est "
                    "résolu (KPI mesurable + horizon)."
                ),
                "entreprise_id": ent_id,
                "action_kind": "manual",
                "action_params": {},
            },
        ],
    }


async def solve_problem(
    db: AsyncSession, problem_text: str
) -> KratosProblem:
    """Pipeline : reçoit un texte de problème → génère plan via IA
    (fallback local) → persiste un KratosProblem avec problem_text,
    solution_plan et steps. Status = open."""
    text = (problem_text or "").strip()
    if not text:
        raise ValueError("Le texte du problème est requis.")

    ents = (
        await db.execute(
            select(Entreprise).where(Entreprise.is_active.is_(True))
        )
    ).scalars().all()

    plan = await _solve_with_claude(text, list(ents))
    if plan is None:
        plan = _solve_locally(text, list(ents))

    title = str(plan.get("title") or text[:120]).strip()[:255]
    severity = str(plan.get("severity") or "medium").lower()
    if severity not in {s.value for s in KratosProblemSeverity}:
        severity = KratosProblemSeverity.MEDIUM.value
    entreprise_id = plan.get("entreprise_id")
    try:
        entreprise_id = int(entreprise_id) if entreprise_id else None
    except (ValueError, TypeError):
        entreprise_id = None
    steps = plan.get("steps") or []
    if not isinstance(steps, list):
        steps = []
    solution_plan = str(plan.get("solution_plan") or "").strip()[:8000]

    problem = KratosProblem(
        entreprise_id=entreprise_id,
        problem_text=text[:8000],
        title=title,
        description=text[:2000],
        severity=severity,
        solution_plan=solution_plan or None,
        solution_steps_json=json.dumps(steps, default=str)[:8000],
        status=KratosProblemStatus.OPEN.value,
    )
    db.add(problem)
    await db.flush()
    return problem
