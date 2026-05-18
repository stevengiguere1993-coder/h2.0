"""Daily SEO article generator — version « domination ».

Génère **3 articles par run** au lieu de 1, en diversifiant les
**types d'angle SEO** (pas juste « service in city » mais aussi coût,
comparaison, comment choisir, erreurs à éviter). Cible 54 villes du
Grand Montréal × 8 services × 5 angles = ~2 000 combinaisons uniques
avant rotation.

Utilise la cascade `app.integrations.ai.complete()` qui fallback
Gemini (gratuit) → Anthropic → Groq, donc coût ~0 $/mois en croisière.

Invoqué via Render cron : `python -m app.jobs.seo_daily`
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

from app.db.session import AsyncSessionLocal, close_db, init_db
from app.integrations.ai import complete
from app.models.seo_article import SeoArticle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seo_daily")


# ---------------------------------------------------------------------
# Cibles SEO (en miroir de frontend/src/lib/seo-locations.ts)
# ---------------------------------------------------------------------

CITIES = [
    # Île de Montréal
    "Montréal", "Westmount", "Outremont", "Saint-Laurent", "Anjou",
    "LaSalle", "Verdun", "Rosemont", "Plateau-Mont-Royal", "Villeray",
    "Mile End", "Griffintown", "Hochelaga", "Ahuntsic", "Ville-Marie",
    "Sud-Ouest", "Mercier", "Notre-Dame-de-Grâce", "Côte-des-Neiges",
    "Saint-Léonard", "Montréal-Nord", "Lachine",
    # West Island
    "Pointe-Claire", "Dollard-des-Ormeaux", "Pierrefonds",
    "Beaconsfield", "Kirkland", "Dorval", "L'Île-Bizard",
    # Rive-Sud
    "Longueuil", "Brossard", "Boucherville", "Saint-Lambert",
    "La Prairie", "Candiac", "Chambly", "Saint-Bruno",
    "Saint-Hubert", "Saint-Constant", "Châteauguay", "Delson",
    # Rive-Nord
    "Laval", "Terrebonne", "Repentigny", "Mascouche", "Blainville",
    "Sainte-Thérèse", "Saint-Eustache", "Boisbriand", "Mirabel",
    "Rosemère",
    # Vaudreuil-Soulanges
    "Vaudreuil-Dorion", "Pincourt", "L'Île-Perrot",
]

SERVICES_FR = [
    ("renovation-salle-de-bain", "Rénovation de salle de bain"),
    ("renovation-cuisine", "Rénovation de cuisine"),
    ("renovation-multilogement", "Rénovation de multilogement"),
    ("renovation-complete", "Rénovation complète"),
    ("agrandissement", "Agrandissement de maison"),
    ("finition-sous-sol", "Finition de sous-sol"),
    ("changement-fenetres", "Changement de fenêtres"),
    ("construction-terrasse", "Construction de terrasse"),
]

SERVICES_EN = [
    ("bathroom-renovation", "Bathroom renovation"),
    ("kitchen-renovation", "Kitchen renovation"),
    ("multi-unit-renovation", "Multi-unit renovation"),
    ("complete-renovation", "Complete renovation"),
    ("home-extension", "Home extension"),
    ("basement-finishing", "Basement finishing"),
    ("window-replacement", "Window replacement"),
    ("deck-construction", "Deck construction"),
]

# ---------------------------------------------------------------------
# Angles SEO — diversifie les types de queries que Google nous montre
# ---------------------------------------------------------------------

# Chaque angle a son slug-suffix unique pour ne pas écraser un autre
# article sur le même service+ville.
ANGLES_FR = [
    {
        "slug_suffix": "",
        "title_template": "{service} à {city}",
        "prompt_focus": (
            "présentation générale du service, étapes, garanties, "
            "fourchettes de prix 2026. Inclus les particularités "
            "locales de {city} (climat, contraintes municipales, "
            "marché immobilier)."
        ),
        "target_keywords": "{service_lower} {city}",
    },
    {
        "slug_suffix": "prix-2026",
        "title_template": "Combien coûte une {service_lower} à {city} en 2026",
        "prompt_focus": (
            "guide de prix DÉTAILLÉ : main d'œuvre, matériaux, "
            "fourchettes minimum / moyen / haut de gamme. Explique "
            "ce qui fait varier le prix (taille, choix matériaux, "
            "complexité). Évoque les subventions Rénoclimat et les "
            "crédits Hydro-Québec si pertinent. Ton expert mais "
            "transparent — ne cache pas les coûts."
        ),
        "target_keywords": "prix {service_lower} {city} 2026, combien coûte",
    },
    {
        "slug_suffix": "comment-choisir-entrepreneur",
        "title_template": "Comment choisir un entrepreneur pour une {service_lower} à {city}",
        "prompt_focus": (
            "guide pour choisir un entrepreneur : vérifier la "
            "licence RBQ, demander 3 soumissions comparables, "
            "questions à poser, drapeaux rouges à éviter, importance "
            "des plombiers CMMTQ / électriciens CMEQ. Termine par "
            "« ce que Horizon Services Immobiliers fait différemment »."
        ),
        "target_keywords": "entrepreneur {service_lower} {city}, choisir entrepreneur",
    },
    {
        "slug_suffix": "erreurs-a-eviter",
        "title_template": "10 erreurs à éviter pour une {service_lower} à {city}",
        "prompt_focus": (
            "liste des 10 erreurs courantes (matériaux trop bon "
            "marché, sous-traitant non licencié, mauvaise estimation "
            "des permis, etc.) avec UNE phrase concrète pour chaque. "
            "Format liste numérotée H2 ou H3. Ton direct, sans bla-bla."
        ),
        "target_keywords": "erreurs {service_lower}, conseils {city}",
    },
    {
        "slug_suffix": "delais-et-permis",
        "title_template": "Délais et permis pour une {service_lower} à {city}",
        "prompt_focus": (
            "calendrier réaliste (étapes + durée), démarches "
            "municipales à {city} (quand un permis est requis, où "
            "l'obtenir, délai administratif), saisons à privilégier "
            "ou éviter, comment planifier."
        ),
        "target_keywords": "délai {service_lower} {city}, permis {city}",
    },
]

ANGLES_EN = [
    {
        "slug_suffix": "",
        "title_template": "{service} in {city}",
        "prompt_focus": "Service overview, steps, guarantees, 2026 price ranges.",
        "target_keywords": "{service_lower} {city}",
    },
    {
        "slug_suffix": "cost-2026",
        "title_template": "How much does a {service_lower} cost in {city} in 2026",
        "prompt_focus": "Detailed cost guide: labor, materials, low/mid/high ranges.",
        "target_keywords": "cost {service_lower} {city} 2026",
    },
    {
        "slug_suffix": "how-to-choose-contractor",
        "title_template": "How to choose a contractor for a {service_lower} in {city}",
        "prompt_focus": "Guide to choosing a contractor: RBQ license, 3 quotes, questions, red flags.",
        "target_keywords": "contractor {service_lower} {city}",
    },
]

# Combien d'articles par run du cron. Bumpé de 1 → 3 pour densifier
# le contenu.
ARTICLES_PER_RUN = int(os.getenv("SEO_DAILY_ARTICLES_PER_RUN", "3"))


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[àâä]", "a", value)
    value = re.sub(r"[éèêë]", "e", value)
    value = re.sub(r"[îï]", "i", value)
    value = re.sub(r"[ôö]", "o", value)
    value = re.sub(r"[ùûü]", "u", value)
    value = re.sub(r"[ç]", "c", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def build_prompt(
    city: str,
    service_title: str,
    locale: str,
    angle: dict,
) -> str:
    """Construit le prompt avec l'angle SEO ciblé."""
    service_lower = service_title.lower()
    if locale == "fr":
        title_hint = angle["title_template"].format(
            service=service_title, service_lower=service_lower, city=city
        )
        return (
            f"Tu es rédacteur SEO pour Horizon Services Immobiliers, "
            f"entrepreneur général licencié RBQ à Montréal et dans le "
            f"Grand Montréal. Écris un article de blogue ORIGINAL et "
            f"NON-GÉNÉRIQUE en français québécois, optimisé pour le SEO "
            f"local.\n\n"
            f"Angle de l'article : {title_hint}\n"
            f"Focus du contenu : {angle['prompt_focus'].format(city=city, service_lower=service_lower)}\n"
            f"Mots-clés cibles : {angle['target_keywords'].format(city=city, service_lower=service_lower)}\n\n"
            f"Contraintes :\n"
            f"- 800 à 1200 mots, ton expert mais accessible\n"
            f"- 4 à 6 sous-titres H2 et H3 pertinents (Markdown ## et ###)\n"
            f"- Mentionne « {city} » 3 à 5 fois naturellement (jamais en bourrage)\n"
            f"- Inclus la licence RBQ + partenaires CMMTQ/CMEQ quand pertinent\n"
            f"- Évoque le climat québécois et les contraintes du Code du bâtiment QC si pertinent\n"
            f"- Termine par un CTA vers le formulaire de contact (1 phrase)\n"
            f"- Pas de listes interminables, pas de jargon corporate, pas de répétitions\n\n"
            f"Réponds UNIQUEMENT en JSON valide avec ces clés :\n"
            f"  title (max 70 car, doit inclure « {city} »),\n"
            f"  meta_description (max 160 car, intent commercial),\n"
            f"  excerpt (max 220 car),\n"
            f"  keywords (5-8 séparés par virgule, en français),\n"
            f"  content_md (article complet Markdown, SANS le H1)."
        )
    title_hint = angle["title_template"].format(
        service=service_title, service_lower=service_lower, city=city
    )
    return (
        f"You are an SEO copywriter for Horizon Services Immobiliers, a "
        f"general contractor in Greater Montreal. Write an original, "
        f"non-generic blog article in Canadian English, optimized for "
        f"local SEO.\n\n"
        f"Angle: {title_hint}\n"
        f"Focus: {angle['prompt_focus']}\n"
        f"Target keywords: {angle['target_keywords'].format(city=city, service_lower=service_lower)}\n\n"
        f"Constraints: 800-1200 words, expert tone, 4-6 H2/H3 subheadings, "
        f"mention '{city}' 3-5 times naturally, RBQ license + CMMTQ/CMEQ "
        f"partners when relevant, end with a contact CTA.\n\n"
        f"Reply in VALID JSON only: title (max 70 chars, must include "
        f"'{city}'), meta_description (max 160 chars), excerpt (max 220 "
        f"chars), keywords (5-8 comma separated), content_md (article in "
        f"Markdown, NO H1)."
    )


def parse_json(raw: str) -> dict[str, Any]:
    stripped = (raw or "").strip()
    if "```json" in stripped:
        stripped = stripped.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in stripped:
        stripped = stripped.split("```", 1)[1].split("```", 1)[0]
    return json.loads(stripped.strip())


async def call_ai(prompt: str) -> dict[str, Any]:
    """Appelle la cascade IA (Gemini → Anthropic → Groq)."""
    result = await complete(
        prompt=prompt,
        max_tokens=4096,
        temperature=0.6,
    )
    return parse_json(result.text)


# ---------------------------------------------------------------------
# Rotation : pick N slots
# ---------------------------------------------------------------------


async def pick_next_slots(n: int) -> list[tuple[str, str, str, str, str, dict]]:
    """Sélectionne les N prochains slots à générer (round-robin parmi
    les combos city × service × angle × locale jamais générés)."""
    async with AsyncSessionLocal() as session:
        existing = {
            row for row in (await session.execute(select(SeoArticle.slug))).scalars()
        }

    slots: list[tuple[str, str, str, str, str, dict]] = []
    for locale, services, angles in (
        ("fr", SERVICES_FR, ANGLES_FR),
        ("en", SERVICES_EN, ANGLES_EN),
    ):
        for angle in angles:
            for city in CITIES:
                for key, title in services:
                    suffix = angle["slug_suffix"]
                    slug = f"{key}-{slugify(city)}"
                    if suffix:
                        slug = f"{slug}-{suffix}"
                    if slug in existing:
                        continue
                    slots.append((slug, locale, city, key, title, angle))
                    if len(slots) >= n:
                        return slots
    return slots


# ---------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------


async def generate_one(
    slug: str,
    locale: str,
    city: str,
    service_key: str,
    service_title: str,
    angle: dict,
) -> bool:
    log.info(
        "Generating slug=%s locale=%s city=%s service=%s angle=%s",
        slug, locale, city, service_key, angle.get("slug_suffix") or "default",
    )
    prompt = build_prompt(city, service_title, locale, angle)
    try:
        data = await call_ai(prompt)
    except Exception as exc:  # noqa: BLE001
        log.warning("IA call failed for %s: %s", slug, exc)
        return False

    title = str(data.get("title", ""))[:200]
    meta_description = str(data.get("meta_description", ""))[:300]
    excerpt = data.get("excerpt") or None
    keywords = data.get("keywords") or None
    content_md = str(data.get("content_md", "")).strip()

    if not title or len(content_md) < 400:
        log.warning("Skip %s: title/content trop court", slug)
        return False

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
        log.info("Saved id=%s slug=%s", article.id, article.slug)
    return True


async def run_once() -> int:
    try:
        await init_db()
    except Exception as exc:
        log.warning("init_db soft-failed: %s", exc)

    slots = await pick_next_slots(ARTICLES_PER_RUN)
    if not slots:
        log.info("Aucun slot non-couvert — rotation terminée")
        return 0

    ok_count = 0
    for slot in slots:
        if await generate_one(*slot):
            ok_count += 1

    log.info("Run terminé : %d / %d articles générés", ok_count, len(slots))
    return 0 if ok_count > 0 else 1


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
