"""Audit IA des modifications du code.

Lit les pull requests mergés sur GitHub via l'API REST publique
(ou avec ``GITHUB_TOKEN`` si défini pour augmenter le quota). Les
regroupe par fenêtre temporelle (24h, 7j, 30j…) puis demande à l'IA
de les résumer en thèmes lisibles pour qu'un partner reprenant le
développement comprenne d'un coup d'œil ce qui a été ajouté ou
modifié.

Endpoints :
    GET /api/v1/audit/changes?window=24h|48h|7d|30d|90d

Restrictions : owner + admin uniquement.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx

from app.integrations.ai import (
    AIProviderError,
    AIProviderUnavailable,
    complete,
)

log = logging.getLogger(__name__)

REPO_OWNER = "stevengiguere1993-coder"
REPO_NAME = "h2.0"

# Cache en mémoire { window_key: (timestamp, AuditOut) }. Évite de
# rappeler GitHub + IA à chaque rendu de la page d'accueil.
_CACHE: dict[str, tuple[float, "AuditOut"]] = {}
_CACHE_TTL_SECONDS = 60 * 30  # 30 min


@dataclass
class PRSummary:
    number: int
    title: str
    merged_at: str
    url: str
    body: Optional[str]


@dataclass
class AuditTheme:
    title: str
    bullets: List[str]


@dataclass
class AuditOut:
    window: str
    period_start: str
    period_end: str
    pr_count: int
    themes: List[AuditTheme]
    headline: str
    raw_prs: List[PRSummary]
    model_used: Optional[str]
    provider: Optional[str]
    generated_at: str


def _window_to_hours(window: str) -> int:
    """Convertit '24h', '48h', '7d', '30d', '90d' en heures.
    Défaut 168h (7 jours) sur entrée invalide."""
    w = window.strip().lower()
    mapping = {
        "24h": 24,
        "48h": 48,
        "7d": 168,
        "30d": 720,
        "90d": 2160,
    }
    return mapping.get(w, 168)


async def _fetch_merged_prs(since: datetime) -> List[PRSummary]:
    """Récupère jusqu'à 50 PRs récents et filtre côté local sur
    merged_at >= since."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = (
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls"
        "?state=closed&sort=updated&direction=desc&per_page=50"
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        rows = resp.json()

    out: List[PRSummary] = []
    for row in rows:
        merged_at = row.get("merged_at")
        if not merged_at:
            continue
        merged_dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
        if merged_dt < since:
            continue
        out.append(
            PRSummary(
                number=int(row.get("number", 0)),
                title=str(row.get("title") or "").strip(),
                merged_at=merged_at,
                url=str(row.get("html_url") or ""),
                body=(row.get("body") or "")[:1500] or None,
            )
        )
    out.sort(key=lambda p: p.merged_at, reverse=True)
    return out


async def _summarize_with_ai(
    prs: List[PRSummary], window: str
) -> tuple[str, List[AuditTheme], Optional[str], Optional[str]]:
    """Demande à l'IA de regrouper les PRs en thèmes. Retourne
    (headline, themes, provider, model). Fallback no-AI si l'IA
    échoue : un seul thème listant les PRs en brut."""
    if not prs:
        return ("Aucun changement sur cette période.", [], None, None)

    # Construit le bloc d'entrée IA — limite la taille pour ne pas
    # exploser le contexte si beaucoup de PRs.
    lines: list[str] = []
    for p in prs[:40]:
        body_excerpt = (p.body or "").replace("\n", " ").strip()[:300]
        lines.append(
            f"- #{p.number} {p.title}"
            + (f" — {body_excerpt}" if body_excerpt else "")
        )
    pr_block = "\n".join(lines)

    prompt = (
        f"Voici les pull requests mergés sur la branche principale "
        f"durant les dernières {window}.\n\n"
        + pr_block
        + "\n\nTu rédiges un audit pour un partner qui reprend le "
        "développement et veut comprendre vite ce qui a été modifié.\n"
        "Réponds STRICTEMENT en JSON :\n"
        '  "headline" (string, ≤120 char, accroche du résumé)\n'
        '  "themes" (array de 2-5 objets — regroupe les PRs par sujet) :\n'
        '     { "title": string, "bullets": [string, …] }\n'
        "Reste factuel. Pas de marketing. Bullets en français québécois "
        "court (≤140 char chacun). Référence les PR par leur numéro "
        "« #N » dans les bullets quand utile."
    )
    system = (
        "Tu es un assistant technique qui rédige des audits de "
        "changements de code de façon factuelle, sans flatterie."
    )

    try:
        res = await complete(
            prompt=prompt, system=system, max_tokens=900, temperature=0.3
        )
    except (AIProviderUnavailable, AIProviderError) as exc:
        log.info("Audit IA: AI unavailable, fallback brut: %s", exc)
        return (
            f"{len(prs)} PR(s) mergé(s)",
            [
                AuditTheme(
                    title="PRs récents",
                    bullets=[f"#{p.number} {p.title}" for p in prs[:30]],
                )
            ],
            None,
            None,
        )

    raw = res.text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
    try:
        parsed = json.loads(raw.strip())
        headline = str(parsed.get("headline") or "").strip()[:300]
        raw_themes = parsed.get("themes") or []
        themes: List[AuditTheme] = []
        if isinstance(raw_themes, list):
            for t in raw_themes:
                if not isinstance(t, dict):
                    continue
                bullets = t.get("bullets") or []
                if not isinstance(bullets, list):
                    bullets = [str(bullets)]
                themes.append(
                    AuditTheme(
                        title=str(t.get("title") or "").strip()[:120],
                        bullets=[str(b)[:300] for b in bullets[:8]],
                    )
                )
        return (
            headline or f"{len(prs)} PR(s) mergé(s)",
            themes,
            res.provider,
            res.model,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Audit IA: parse failed: %s — raw=%r", exc, raw[:200])
        return (
            f"{len(prs)} PR(s) mergé(s)",
            [
                AuditTheme(
                    title="PRs récents",
                    bullets=[f"#{p.number} {p.title}" for p in prs[:30]],
                )
            ],
            None,
            None,
        )


async def get_audit(window: str, *, force: bool = False) -> AuditOut:
    """Récupère + résume. Cache 30 min par fenêtre temporelle."""
    cache_key = window
    now = time.time()
    if not force and cache_key in _CACHE:
        ts, cached = _CACHE[cache_key]
        if now - ts < _CACHE_TTL_SECONDS:
            return cached

    hours = _window_to_hours(window)
    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(hours=hours)

    try:
        prs = await _fetch_merged_prs(period_start)
    except httpx.HTTPError as exc:
        log.warning("Audit IA: GitHub fetch failed: %s", exc)
        prs = []

    headline, themes, provider, model = await _summarize_with_ai(
        prs, window
    )

    out = AuditOut(
        window=window,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        pr_count=len(prs),
        themes=themes,
        headline=headline,
        raw_prs=prs,
        model_used=model,
        provider=provider,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    _CACHE[cache_key] = (now, out)
    return out
