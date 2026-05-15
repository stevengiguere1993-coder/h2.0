"""Service IA pour les rencontres : résumé structuré par section +
résumé global, transcription audio via Whisper (OpenAI).

Tout est défensif : si l'IA est indisponible, on retourne un fallback
qui garde le transcript brut + un résumé heuristique court."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

from app.core.config import settings


log = logging.getLogger(__name__)


SUMMARY_MODEL = "claude-sonnet-4-6"


SECTION_SUMMARY_PROMPT = """Tu es l'assistant qui résume les rencontres \
stratégiques d'un dirigeant qui gère plusieurs entreprises. Tu reçois \
le titre d'une section et son transcript brut (dicté, tapé ou transcrit \
depuis un audio). Tu produis un résumé STRUCTURÉ en JSON strict.

## Contexte de transcription
Le transcript peut provenir d'une **dictée vocale en français québécois** \
(Web Speech API du navigateur). Il contient fréquemment :
- des homophones mal choisis (sont/son, c'est/ces/sait/s'est, a/à, ou/où, \
  ces/ses/c'est, leur/leurs) ;
- des accents manquants ou mal placés (« etre » au lieu de « être ») ;
- des mots anglais mal transcrits (« rapport » au lieu de « report », \
  « charte » au lieu de « chart ») ;
- de la ponctuation aberrante ou absente ;
- des noms d'entreprises / personnes en phonétique approximative ;
- des coupures abruptes ou des répétitions (l'utilisateur s'est repris).

Tu **corriges implicitement** ces erreurs dans ton résumé — tu ne les \
mentionnes JAMAIS. Tu produis du français québécois professionnel correct.

## Format de sortie
{
  "summary": "1-2 paragraphes synthétiques en français québécois",
  "decisions": ["Décision 1", "Décision 2", ...],
  "action_items": [
    {
      "title": "Action à faire (max 120 car)",
      "owner": "Qui s'en charge (texte libre, ou null)",
      "entreprise_hint": "Nom de l'entreprise concernée si mentionné, ou null",
      "due": "Échéance si mentionnée (texte libre), ou null"
    }
  ],
  "open_questions": ["Question en suspens 1", ...],
  "risks": ["Risque identifié 1", ...]
}

## Règles
- Tu ne dis JAMAIS « rien à résumer ». Même un transcript court doit \
sortir au moins le `summary` + 1 action ou question.
- Reste fidèle au fond du transcript — n'invente pas d'actions non \
mentionnées (mais reconstitue le sens malgré les erreurs de transcription).
- Si un nom d'entreprise / de personne semble approximatif, choisis la \
meilleure correspondance avec la liste fournie ; sinon, conserve la \
graphie la plus probable.
- Réponds UNIQUEMENT avec le JSON."""


GLOBAL_SUMMARY_PROMPT = """Tu reçois l'ensemble des résumés de sections \
d'une rencontre stratégique multi-entreprises. Tu produis un résumé \
GLOBAL exploitable pour le dirigeant.

Format : 4-6 paragraphes en français québécois professionnel couvrant :
1. Contexte de la rencontre (objectifs, durée, participants si \
mentionnés).
2. Grands thèmes abordés section par section (1 paragraphe par section \
clé).
3. Décisions stratégiques prises.
4. Actions concrètes à exécuter dans les 30 jours.
5. Points en suspens à reprendre.

Pas de bullet points — du texte narratif. Pas de blabla. Si certaines \
sections contiennent des coquilles évidentes (résidus de dictée \
vocale), tu corriges silencieusement le français en restant fidèle au \
fond."""


TRANSCRIPT_CLEANUP_PROMPT = """Tu reçois un transcript brut produit par \
une dictée vocale en français québécois (Web Speech API du navigateur). \
Ta tâche : **réécrire le transcript en français québécois correct**, \
sans le résumer, sans en ajouter, sans en retirer le fond.

Corrections à appliquer systématiquement :
1. **Homophones** : sont/son, c'est/ces/sait/s'est, a/à, ou/où, \
   ces/ses, leur/leurs, peux/peut/peu, etc.
2. **Accents manquants ou mal placés** : être, à, où, déjà, là, etc.
3. **Ponctuation** : majuscule en début de phrase, espaces correctes \
   avant `: ; ! ?`, virgules logiques, points pour fermer les phrases.
4. **Anglicismes mal transcrits** : « rapport » → « report », \
   « charte » → « chart » si le contexte business l'indique. NE PAS \
   sur-traduire le franglais légitime du Québec si l'intention est claire.
5. **Répétitions et reprises** : si l'utilisateur s'est manifestement \
   repris (« euh, je veux dire »), enlève les répétitions mais garde \
   la version finale.
6. **Mots manifestement mal entendus** : remplace par le mot le plus \
   plausible compte tenu du contexte d'affaires.
7. **Paragraphes** : sépare les idées par des paragraphes (\\n\\n) \
   quand le sens change.

Ne fais PAS :
- Ne résume pas — tu réécris à la même longueur (± 10 %).
- Ne reformule pas pour « mieux » dire — reste fidèle au registre de \
  l'orateur.
- N'ajoute pas de bullet points si l'original n'en avait pas.
- N'invente pas d'information qui n'est pas dans l'original.

Réponds UNIQUEMENT avec le texte corrigé, sans préambule, sans \
explication, sans guillemets autour."""


def _parse_claude_json(raw: str) -> Optional[dict]:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return None


def _heuristic_section_summary(title: str, transcript: str) -> dict:
    """Fallback : sans IA, on extrait juste les phrases clés et on
    propose un résumé minimal."""
    t = (transcript or "").strip()
    first_para = t.split("\n\n", 1)[0] if t else ""
    summary = first_para[:500] or f"Section « {title} » sans contenu."
    return {
        "summary": summary,
        "decisions": [],
        "action_items": [
            {
                "title": f"Relire et structurer la section « {title }»",
                "owner": None,
                "entreprise_hint": None,
                "due": None,
            }
        ],
        "open_questions": [],
        "risks": [],
    }


async def summarize_section(
    title: str,
    transcript: str,
    entreprises_context: Optional[list[dict]] = None,
) -> dict:
    """Résume une section. Retourne toujours un dict valide
    (fallback heuristique si Claude indisponible).

    `entreprises_context` : liste optionnelle [{id, name}, ...] des
    entreprises concernées par la rencontre. Permet à Claude de tagger
    chaque action_item avec le nom exact de l'entreprise (utile quand
    une rencontre couvre plusieurs sociétés)."""
    text = (transcript or "").strip()
    if not text:
        return _heuristic_section_summary(title, "")
    if not settings.anthropic_api_key:
        return _heuristic_section_summary(title, text)
    import anthropic

    ents_block = ""
    if entreprises_context:
        lines = [
            f"- {e.get('name', '?')}"
            for e in entreprises_context
            if e.get("name")
        ]
        if lines:
            ents_block = (
                "## Entreprises concernées par cette rencontre\n"
                + "\n".join(lines)
                + "\n\nQuand une action concerne une entreprise précise "
                "ci-dessus, mets son NOM EXACT dans `entreprise_hint`. "
                "Si transverse, laisse null.\n\n"
            )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=2000,
            system=SECTION_SUMMARY_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"## Section\n{title}\n\n"
                        + ents_block
                        + f"## Transcript brut\n{text[:30_000]}\n\n"
                        "Génère le JSON selon le schéma."
                    ),
                }
            ],
        )
        raw = "\n".join(
            b.text for b in msg.content if b.type == "text"
        ).strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("Section summary failed (Claude): %s", exc)
        return _heuristic_section_summary(title, text)

    parsed = _parse_claude_json(raw)
    if parsed is None:
        return _heuristic_section_summary(title, text)
    return parsed


async def summarize_global(sections: list[dict]) -> str:
    """sections = [{ title, summary, decisions, action_items, ... }]
    Retourne un résumé global texte. Fallback : concaténation."""
    if not sections:
        return ""
    if not settings.anthropic_api_key:
        # Fallback : assemblage simple
        parts: list[str] = []
        for s in sections:
            parts.append(f"## {s.get('title')}\n{s.get('summary') or ''}")
        return "\n\n".join(parts)
    import anthropic

    blocks: list[str] = []
    for s in sections:
        block = [f"### {s.get('title', '(sans titre)')}"]
        if s.get("summary"):
            block.append(f"Résumé : {s['summary']}")
        if s.get("decisions"):
            block.append("Décisions : " + " ; ".join(s["decisions"]))
        if s.get("action_items"):
            actions = [
                f"{a.get('title')}"
                + (f" — {a['owner']}" if a.get("owner") else "")
                + (
                    f" (entreprise : {a['entreprise_hint']})"
                    if a.get("entreprise_hint")
                    else ""
                )
                for a in s["action_items"]
            ]
            block.append("Actions : " + " ; ".join(actions))
        if s.get("open_questions"):
            block.append(
                "Questions en suspens : " + " ; ".join(s["open_questions"])
            )
        if s.get("risks"):
            block.append("Risques : " + " ; ".join(s["risks"]))
        blocks.append("\n".join(block))

    user_prompt = (
        "## Sections de la rencontre\n\n" + "\n\n---\n\n".join(blocks)
    )
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=3000,
            system=GLOBAL_SUMMARY_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = "\n".join(
            b.text for b in msg.content if b.type == "text"
        ).strip()
        return raw
    except Exception as exc:  # noqa: BLE001
        log.warning("Global summary failed: %s", exc)
        return "\n\n".join(blocks)


async def clean_transcript(
    transcript: str,
    entreprises_context: Optional[list[dict]] = None,
) -> str:
    """Réécrit un transcript de dictée vocale en français québécois
    propre. Corrige les homophones, les accents, la ponctuation et les
    mots manifestement mal entendus. Ne résume pas.

    Fallback : si Claude est indisponible, retourne le transcript brut
    inchangé (ne casse jamais la dictée)."""
    text = (transcript or "").strip()
    if not text:
        return ""
    if not settings.anthropic_api_key:
        return text
    import anthropic

    # Indice de noms propres : entreprises de la rencontre, pour que
    # Claude reconnaisse une mauvaise transcription d'un nom et la
    # corrige avec l'orthographe exacte.
    ents_block = ""
    if entreprises_context:
        names = [
            e.get("name", "")
            for e in entreprises_context
            if e.get("name")
        ]
        if names:
            ents_block = (
                "\n\n## Noms propres connus dans cette rencontre\n"
                "Si un nom phonétiquement approchant apparaît dans le "
                "transcript, corrige avec l'orthographe exacte de cette "
                "liste :\n"
                + "\n".join(f"- {n}" for n in names)
            )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=4000,
            system=TRANSCRIPT_CLEANUP_PROMPT + ents_block,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "## Transcript brut à corriger\n\n"
                        + text[:30_000]
                    ),
                }
            ],
        )
        cleaned = "\n".join(
            b.text for b in msg.content if b.type == "text"
        ).strip()
        return cleaned or text
    except Exception as exc:  # noqa: BLE001
        log.warning("Transcript cleanup failed: %s", exc)
        return text


async def transcribe_audio(
    filename: str, content_type: str, data: bytes
) -> str:
    """Transcription audio désactivée — on s'appuie uniquement sur la
    dictée vocale Web Speech API (gratuite, native navigateur).

    Ce stub est conservé pour ne pas casser les imports / endpoints,
    mais lève toujours une RuntimeError. L'UI doit éviter d'appeler
    cet endpoint et orienter l'utilisateur vers la dictée live."""
    raise RuntimeError(
        "La transcription d'audio uploadé est désactivée. Utilise la "
        "dictée vocale en direct (bouton « Dicter ») — c'est gratuit, "
        "100 % navigateur, et bien adapté au français québécois."
    )
