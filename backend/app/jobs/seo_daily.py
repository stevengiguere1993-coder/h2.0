"""
Daily SEO article generator.

Runs as a Render cron at 11:00 UTC (07:00 America/Montreal). Picks the
next rotation slot (city x service x locale), asks Claude for a SEO
article tailored to that slot, stores it, and bumps the sitemap.

Invoked via: python -m app.jobs.seo_daily
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, close_db, init_db
from app.models.seo_article import SeoArticle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seo_daily")

CITIES = [
    "Montréal", "Laval", "Longueuil", "Brossard", "Boucherville",
    "Saint-Lambert", "Westmount", "Outremont", "Saint-Laurent",
    "Pointe-Claire", "Dollard-des-Ormeaux", "Anjou", "LaSalle",
    "Verdun", "Rosemont", "Plateau-Mont-Royal", "Villeray",
    "Mile End", "Griffintown", "Hochelaga",
]

SERVICES_FR = [
    ("renovation-salle-de-bain", "Rénovation de salle de bain"),
    ("renovation-cuisine", "Rénovation de cuisine"),
    ("renovation-multilogement", "Rénovation d'appartement multilogement"),
    ("renovation-complete", "Rénovation complète"),
]

SERVICES_EN = [
    ("bathroom-renovation", "Bathroom renovation"),
    ("kitchen-renovation", "Kitchen renovation"),
    ("multi-unit-renovation", "Multi-unit apartment renovation"),
    ("complete-renovation", "Complete renovation"),
]


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[\u00e0\u00e2\u00e4]", "a", value)
    value = re.sub(r"[\u00e9\u00e8\u00ea\u00eb]", "e", value)
    value = re.sub(r"[\u00ee\u00ef]", "i", value)
    value = re.sub(r"[\u00f4\u00f6]", "o", value)
    value = re.sub(r"[\u00f9\u00fb\u00fc]", "u", value)
    value = re.sub(r"[\u00e7]", "c", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def build_prompt(city: str, service_title: str, locale: str) -> str:
    if locale == "fr":
        return (
            f"Tu es rédacteur SEO pour Horizon Services Immobiliers, une entreprise"
            f" de rénovation du Grand Montréal. \u00c9cris un article de blogue"
            f" original, non-générique, en français québécois, ciblé pour le SEO"
            f" local.\n\nSujet: {service_title} à {city}\n\nContraintes:\n"
            f"- 700 à 1000 mots, ton expert mais accessible\n"
            f"- Au moins 4 sous-titres (H2) pertinents\n"
            f"- Mentionne 2-3 fois '{city}' naturellement\n"
            f"- Évoque le climat et les contraintes réglementaires du Québec si pertinent\n"
            f"- Inclut une section coûts/budget avec fourchettes 2026\n"
            f"- Se termine par un CTA vers le formulaire de contact\n\n"
            f"Réponds UNIQUEMENT en JSON valide avec ces clés:\n"
            f'  title (max 70 car), meta_description (max 160 car),'
            f' excerpt (max 220 car),'
            f' keywords (5-8 séparés par virgule),'
            f' content_md (l’article au format Markdown, sans le titre H1).'
        )
    return (
        f"You are an SEO copywriter for Horizon Services Immobiliers, a Greater"
        f" Montreal renovation company. Write an original, non-generic blog"
        f" article in Canadian English, optimized for local SEO.\n\n"
        f"Topic: {service_title} in {city}\n\nConstraints:\n"
        f"- 700 to 1000 words, expert but accessible tone\n"
        f"- At least 4 relevant H2 subheadings\n"
        f"- Mention '{city}' 2-3 times naturally\n"
        f"- Cover climate and Quebec regulatory constraints when relevant\n"
        f"- Include a costs/budget section with 2026 ranges (CAD)\n"
        f"- End with a CTA to the contact form\n\n"
        f"Reply with VALID JSON only with these keys:\n"
        f'  title (max 70 chars), meta_description (max 160 chars),'
        f' excerpt (max 220 chars),'
        f' keywords (5-8 comma separated),'
        f' content_md (the article in Markdown, without the H1 title).'
    )


def parse_claude_json(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    if "```json" in stripped:
        stripped = stripped.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in stripped:
        stripped = stripped.split("```", 1)[1].split("```", 1)[0]
    return json.loads(stripped.strip())


def call_claude(prompt: str) -> dict[str, Any]:
    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    try:
        from anthropic import Anthropic  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "The `anthropic` package is required for the SEO cron. "
            "Add it to backend/requirements.txt."
        ) from exc

    client = Anthropic(api_key=api_key)
    model = settings.claude_model or "claude-sonnet-4-5"
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "text", None)
    )
    return parse_claude_json(text)


async def pick_next_slot() -> tuple[str, str, str, str, str]:
    """Rotate through city x service x locale combinations.

    Deterministic: we take the least-recently-created slot by scanning
    the existing articles. Ensures coverage before repetition.
    """
    async with AsyncSessionLocal() as session:
        q = select(SeoArticle.slug)
        existing = {row for row in (await session.execute(q)).scalars()}

    for locale, services in (("fr", SERVICES_FR), ("en", SERVICES_EN)):
        for city in CITIES:
            for key, title in services:
                slug = f"{key}-{slugify(city)}"
                if slug not in existing:
                    return slug, locale, city, key, title

    # Everything covered; fall back to oldest slug
    async with AsyncSessionLocal() as session:
        q = select(SeoArticle).order_by(SeoArticle.created_at.asc()).limit(1)
        oldest: Optional[SeoArticle] = (await session.execute(q)).scalar_one_or_none()
        if oldest:
            return (
                f"{oldest.target_service}-{slugify(oldest.target_city or 'montreal')}-"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                oldest.locale,
                oldest.target_city or "Montréal",
                oldest.target_service or SERVICES_FR[0][0],
                SERVICES_FR[0][1],
            )

    # Sensible default if the DB is empty
    return "renovation-salle-de-bain-montreal", "fr", "Montréal", SERVICES_FR[0][0], SERVICES_FR[0][1]


async def run_once() -> int:
    try:
        await init_db()
    except Exception as exc:
        log.warning("init_db soft-failed: %s", exc)

    slug, locale, city, service_key, service_title = await pick_next_slot()
    log.info("Generating article: slug=%s locale=%s city=%s service=%s", slug, locale, city, service_key)

    prompt = build_prompt(city=city, service_title=service_title, locale=locale)
    data = call_claude(prompt)

    title = str(data.get("title", ""))[:200]
    meta_description = str(data.get("meta_description", ""))[:300]
    excerpt = (data.get("excerpt") or None)
    keywords = (data.get("keywords") or None)
    content_md = str(data.get("content_md", "")).strip()

    if not title or not content_md:
        log.error("Claude returned empty title or content. Aborting.")
        return 1

    async with AsyncSessionLocal() as session:
        article = SeoArticle(
            slug=slug,
            locale=locale,
            title=title,
            meta_description=meta_description,
            content_md=content_md,
            excerpt=excerpt,
            keywords=keywords,
            target_city=city,
            target_service=service_key,
            published=True,
            published_at=datetime.now(timezone.utc),
        )
        session.add(article)
        await session.commit()
        log.info("Saved article id=%s slug=%s", article.id, article.slug)

    return 0


def main() -> int:
    try:
        return asyncio.run(run_once())
    finally:
        try:
            asyncio.run(close_db())
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
