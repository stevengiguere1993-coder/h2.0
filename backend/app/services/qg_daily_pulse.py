"""Daily Pulse pour le volet Gestion d'entreprises.

Pour chaque entreprise active : rassemble (tâches en cours, tâches dues,
tâches récemment terminées, activités du jour, dernier briefing) et
demande à l'IA un résumé synthétique pour le dirigeant. Sauvegardé
dans ``qg_summaries`` (type=daily_briefing) — historique conservé.

Idempotent : un briefing par entreprise par jour. Re-déclencher écrase
seulement si ``force=True``.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.ai import (
    AIProviderError,
    AIProviderUnavailable,
    complete,
)
from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.models.qg_strategic import (
    Activity,
    Summary,
    SummaryScope,
    SummaryType,
)


log = logging.getLogger(__name__)

PROMPT_VERSION = "daily-pulse@v2"
SYSTEM_PROMPT = (
    "Tu es l'assistant stratégique d'un dirigeant d'entreprise au "
    "Québec. Tu rédiges un briefing matinal en français québécois, "
    "factuel et orienté action. Pas de flatterie, pas de blabla.\n\n"
    "RÈGLE CRITIQUE : tu produis TOUJOURS une analyse utile, même "
    "quand peu de données récentes existent. Une entreprise doit "
    "croître en continu : il y a toujours quelque chose à analyser, "
    "à prioriser, à exécuter — qu'il s'agisse de tâches en cours "
    "même anciennes, de projets stratégiques en attente, de la "
    "vision long terme, du positionnement, des opportunités de "
    "croissance, de la santé financière ou des chantiers internes "
    "à lancer. Tu ne dis JAMAIS « rien à analyser », « système à "
    "l'arrêt », « pas de données » ou équivalent. Si l'activité "
    "récente est faible, tu pivotes vers : (1) les tâches actives "
    "non-bougées qui méritent une relance, (2) la mission/vision "
    "de l'entreprise et ce que ça implique cette semaine, (3) des "
    "pistes concrètes de croissance ou d'amélioration interne "
    "(marketing, processus, recrutement, finances, qualité, etc.).\n\n"
    "Format : 1 accroche (max 120 caractères), un résumé de 3 à 5 "
    "phrases, et 3 à 5 puces très courtes — chaque puce est une "
    "action ou un constat exploitable, pas une généralité."
)


async def _today_briefing(
    db: AsyncSession, entreprise_id: int, day: date
) -> Optional[Summary]:
    start = datetime.combine(day, dtime.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return (
        await db.execute(
            select(Summary).where(
                Summary.entreprise_id == entreprise_id,
                Summary.type == SummaryType.DAILY_BRIEFING.value,
                Summary.period_start >= start,
                Summary.period_start < end,
            )
        )
    ).scalar_one_or_none()


def _format_taches_block(taches: list[EntrepriseTache]) -> str:
    if not taches:
        return "(aucune)"
    lines = []
    for t in taches[:20]:  # garde-fou prompt
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
            else:
                due = f" (dans {delta}j)"
        dept = f" #{t.departement}" if t.departement else ""
        lines.append(f"- {t.title}{dept}{score}{due}")
    return "\n".join(lines)


def _format_activities_block(acts: list[Activity]) -> str:
    if not acts:
        return "(aucune)"
    lines = []
    for a in acts[:20]:
        amt = (
            f" — {float(a.amount):,.2f} {a.currency or '$'}"
            if a.amount else ""
        )
        lines.append(f"- [{a.kind}] {a.title}{amt}")
    return "\n".join(lines)


def _format_visions_block(visions: list["Vision"]) -> str:  # type: ignore[name-defined]
    if not visions:
        return "(aucune vision enregistrée — propose-en une dans le briefing)"
    lines = []
    for v in visions[:5]:
        lines.append(
            f"- [{v.horizon_label}] {v.title} — {v.narrative[:200]}"
        )
    return "\n".join(lines)


def _format_projects_block(projects: list) -> str:
    if not projects:
        return "(aucun projet stratégique enregistré)"
    lines = []
    for p in projects[:10]:
        status = getattr(p, "status", "?")
        title = getattr(p, "title", "?")
        lines.append(f"- [{status}] {title}")
    return "\n".join(lines)


def _build_prompt(
    *,
    entreprise: Entreprise,
    todo_taches: list[EntrepriseTache],
    in_progress_taches: list[EntrepriseTache],
    done_yesterday: list[EntrepriseTache],
    today_acts: list[Activity],
    yesterday_briefing: Optional[Summary],
    visions: list | None = None,
    strategic_projects: list | None = None,
) -> str:
    parts = [
        f"## Entreprise\n{entreprise.name}",
    ]
    if entreprise.description:
        parts.append(f"Description : {entreprise.description}")

    # Stats pour rappeler à l'IA la situation globale.
    total_open = len(todo_taches) + len(in_progress_taches)
    parts.append(
        "## Vue d'ensemble rapide\n"
        f"- {len(todo_taches)} tâches à faire\n"
        f"- {len(in_progress_taches)} tâches en cours\n"
        f"- {len(done_yesterday)} tâches terminées hier\n"
        f"- {len(today_acts)} activités enregistrées dans les dernières 24 h"
    )

    parts.append(
        "## Tâches À FAIRE / EN COURS (toutes — à traiter ou relancer)\n"
        + _format_taches_block(todo_taches + in_progress_taches)
    )
    parts.append(
        "## Tâches TERMINÉES hier\n"
        + _format_taches_block(done_yesterday)
    )
    parts.append(
        "## Activités enregistrées aujourd'hui (24h)\n"
        + _format_activities_block(today_acts)
    )
    parts.append(
        "## Visions stratégiques actives\n"
        + _format_visions_block(visions or [])
    )
    parts.append(
        "## Projets stratégiques\n"
        + _format_projects_block(strategic_projects or [])
    )
    if yesterday_briefing:
        parts.append(
            "## Briefing d'hier (pour contexte)\n"
            + (yesterday_briefing.summary_text[:1500])
        )

    # Garde-fou explicite contre le « rien à dire ».
    low_activity = (
        total_open == 0
        and len(done_yesterday) == 0
        and len(today_acts) == 0
    )
    instruction = (
        "## Demande\n"
        "Rédige un briefing matinal pour le dirigeant en JSON strict "
        "avec ces clés :\n"
        '  "headline" (string, max 120 caractères, accroche du jour)\n'
        '  "summary" (string, 3-5 phrases concises, exploitables)\n'
        '  "highlights" (array de 3-5 strings, actions ou constats '
        "concrets — toujours utiles, jamais « pas de données »)\n"
        "Réponds UNIQUEMENT avec le JSON, sans markdown autour.\n\n"
        "RAPPEL : tu ne dis JAMAIS « rien à analyser » ou « système "
        "à l'arrêt »."
    )
    if low_activity:
        instruction += (
            " Aujourd'hui l'activité enregistrée est faible — ne le "
            "constate pas comme un échec. Pivote sur : (a) la mission/"
            "description de l'entreprise et ce qu'elle implique cette "
            "semaine, (b) des pistes concrètes pour relancer la "
            "croissance (offre, marketing, processus, finances, "
            "recrutement, qualité, partenariats), (c) des actions à "
            "faire MAINTENANT pour reprendre le momentum. Sors 3 à 5 "
            "actions actionnables."
        )
    parts.append(instruction)
    return "\n\n".join(parts)


def _parse_ai_json(raw: str) -> dict:
    """Parse défensif. L'IA retourne parfois ```json ... ``` autour."""
    s = raw.strip()
    # Strip markdown fences si présents
    if s.startswith("```"):
        # première ligne = ```json ou ```
        s = "\n".join(s.split("\n")[1:])
        if s.endswith("```"):
            s = s[:-3]
    s = s.strip()
    return json.loads(s)


async def generate_for_entreprise(
    db: AsyncSession,
    entreprise_id: int,
    *,
    force: bool = False,
) -> Optional[Summary]:
    """Génère (ou retourne) le daily briefing pour une entreprise.

    - Si un briefing existe déjà aujourd'hui et ``force=False`` → retourne
      celui-là sans nouvel appel IA.
    - Si ``force=True`` → écrase le briefing existant du jour.
    - Si l'IA est indisponible → retourne None silencieusement.
    """
    today = datetime.now(timezone.utc).date()

    ent = (
        await db.execute(
            select(Entreprise).where(Entreprise.id == entreprise_id)
        )
    ).scalar_one_or_none()
    if ent is None or not ent.is_active:
        return None

    existing = await _today_briefing(db, entreprise_id, today)
    if existing is not None and not force:
        return existing

    # Quand l'entreprise est marquée « parent » (ex. MGV
    # Investissements), on inclut les tâches/activités/visions de
    # TOUTES les entreprises actives — son briefing devient la vision
    # globale du groupe. Sinon : périmètre normal de l'entreprise.
    is_parent = bool(getattr(ent, "is_parent_company", False))
    if is_parent:
        active_ids = (
            await db.execute(
                select(Entreprise.id).where(Entreprise.is_active.is_(True))
            )
        ).scalars().all()
        scope_ids = list(active_ids) or [entreprise_id]
    else:
        scope_ids = [entreprise_id]

    # Rassemble le contexte (sur scope_ids = [self] ou [tout le groupe])
    todo = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.entreprise_id.in_(scope_ids),
                EntrepriseTache.status == TacheStatus.TODO.value,
            )
            .limit(60 if is_parent else 30)
        )
    ).scalars().all()
    in_prog = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.entreprise_id.in_(scope_ids),
                EntrepriseTache.status == TacheStatus.IN_PROGRESS.value,
            )
            .limit(60 if is_parent else 30)
        )
    ).scalars().all()

    yesterday = today - timedelta(days=1)
    yest_start = datetime.combine(yesterday, dtime.min, tzinfo=timezone.utc)
    today_start = datetime.combine(today, dtime.min, tzinfo=timezone.utc)
    done_yest = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.entreprise_id.in_(scope_ids),
                EntrepriseTache.status == TacheStatus.DONE.value,
                EntrepriseTache.completed_at >= yest_start,
                EntrepriseTache.completed_at < today_start,
            )
            .limit(60 if is_parent else 30)
        )
    ).scalars().all()

    acts = (
        await db.execute(
            select(Activity).where(
                Activity.entreprise_id.in_(scope_ids),
                Activity.occurred_at >= today_start - timedelta(days=1),
            )
            .order_by(Activity.occurred_at.desc())
            .limit(60 if is_parent else 30)
        )
    ).scalars().all()

    yest_brief = await _today_briefing(db, entreprise_id, yesterday)

    # Contexte stratégique : visions actives + projets stratégiques en
    # cours. Permet à l'IA de toujours avoir matière à analyser même
    # quand l'activité quotidienne est faible.
    from app.models.qg_strategic import StrategicProject, Vision

    visions = (
        await db.execute(
            select(Vision)
            .where(Vision.entreprise_id.in_(scope_ids))
            .where(Vision.horizon_end >= today)
            .order_by(Vision.horizon_end.asc())
            .limit(10 if is_parent else 5)
        )
    ).scalars().all()
    strategic_projects = (
        await db.execute(
            select(StrategicProject)
            .where(StrategicProject.entreprise_id.in_(scope_ids))
            .order_by(StrategicProject.updated_at.desc())
            .limit(20 if is_parent else 10)
        )
    ).scalars().all()

    prompt = _build_prompt(
        entreprise=ent,
        todo_taches=list(todo),
        in_progress_taches=list(in_prog),
        done_yesterday=list(done_yest),
        today_acts=list(acts),
        yesterday_briefing=yest_brief,
        visions=list(visions),
        strategic_projects=list(strategic_projects),
    )
    # Si entreprise mère : on préfixe le prompt avec une consigne
    # spéciale « vision globale du groupe » pour que l'IA résume
    # l'ensemble du portefeuille au lieu d'une seule entité.
    if is_parent:
        prompt = (
            "## Contexte spécial — Entreprise mère\n"
            f"« {ent.name} » est l'entreprise mère du groupe. Le "
            "briefing ci-dessous concerne TOUTES les entreprises "
            "actives (tâches, activités, visions et projets de "
            "l'ensemble du portefeuille). Rédige un briefing avec un "
            "regard de dirigeant qui supervise tout le groupe — pas "
            "seulement une entité.\n\n"
        ) + prompt

    t0 = time.perf_counter()
    try:
        res = await complete(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=800 if is_parent else 600,
            temperature=0.4,
        )
    except (AIProviderUnavailable, AIProviderError) as exc:
        log.warning(
            "Daily pulse AI failed for entreprise %d: %s",
            entreprise_id,
            exc,
        )
        return None

    duration_ms = int((time.perf_counter() - t0) * 1000)

    try:
        parsed = _parse_ai_json(res.text)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Daily pulse JSON parse failed for entreprise %d: %s — raw: %s",
            entreprise_id,
            exc,
            res.text[:200],
        )
        # Fallback : utilise le texte brut, headline = 1ère ligne
        first_line = res.text.strip().split("\n", 1)[0][:120]
        parsed = {
            "headline": first_line or f"Briefing — {ent.name}",
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

    if existing is not None and force:
        existing.headline = headline or existing.headline
        existing.summary_text = summary_text or existing.summary_text
        existing.highlights_json = json.dumps(highlights, ensure_ascii=False)
        existing.model_used = res.model
        existing.provider = res.provider
        existing.input_tokens = res.input_tokens
        existing.output_tokens = res.output_tokens
        existing.generation_duration_ms = duration_ms
        existing.prompt_version = PROMPT_VERSION
        await db.flush()
        return existing

    s = Summary(
        entreprise_id=entreprise_id,
        type=SummaryType.DAILY_BRIEFING.value,
        scope=SummaryScope.COMPANY.value,
        period_start=period_start,
        period_end=period_end,
        headline=headline or f"Briefing — {ent.name}",
        summary_text=summary_text or "(résumé indisponible)",
        highlights_json=json.dumps(highlights, ensure_ascii=False),
        model_used=res.model,
        provider=res.provider,
        prompt_version=PROMPT_VERSION,
        input_tokens=res.input_tokens,
        output_tokens=res.output_tokens,
        generation_duration_ms=duration_ms,
        created_at=datetime.now(timezone.utc),
    )
    db.add(s)
    await db.flush()
    await db.refresh(s)
    return s


async def generate_for_all_active(
    db: AsyncSession, *, force: bool = False
) -> dict:
    """Génère le briefing pour toutes les entreprises actives.
    Appelé par le cron quotidien Render."""
    rows = (
        await db.execute(
            select(Entreprise).where(Entreprise.is_active.is_(True))
        )
    ).scalars().all()
    out = {"total": len(rows), "generated": 0, "skipped": 0, "errors": 0}
    for e in rows:
        try:
            s = await generate_for_entreprise(db, e.id, force=force)
            if s is None:
                out["skipped"] += 1
            else:
                out["generated"] += 1
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "Daily pulse error for entreprise %d: %s", e.id, exc
            )
            out["errors"] += 1
    return out
