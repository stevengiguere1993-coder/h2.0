"""Service IA pour les rencontres : résumé structuré par section +
résumé global + nettoyage du transcript.

Design fault-tolerant : on cascade les providers IA via
``app.integrations.ai.complete()`` (Gemini → Anthropic → Groq selon la
config), et si AUCUN provider IA ne répond, on retombe sur un
fallback 100 % local (TextRank-light) qui produit malgré tout un
résumé extractif décent. L'app n'est JAMAIS bloquée.

Stratégie de coût :
  - Provider primaire recommandé : **Gemini Flash** (gratuit, 1 500
    req/jour, qualité équivalente à Claude pour ce cas d'usage).
  - Fallback automatique : Anthropic Claude (payant), Groq Llama 70B
    (gratuit, 14 k req/jour).
  - Dernier recours : extraction TextRank locale, zéro réseau.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Optional

from app.integrations.ai import AIProviderError, complete, is_configured


log = logging.getLogger(__name__)


# Suggestion de modèle (les providers ont leurs propres défauts ; on
# laisse `complete()` choisir le sien quand model=None). On force ici
# un modèle léger uniquement si AI_MODEL env var n'est pas définie
# côté provider.
SUMMARY_TEMPERATURE = 0.2


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

## Format de sortie (STRICT)
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
- Réponds UNIQUEMENT avec le JSON brut, sans ``` autour."""


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


# --------------------------------------------------------------------------
# Parsing / utilitaires
# --------------------------------------------------------------------------


def _parse_ai_json(raw: str) -> Optional[dict]:
    """Extrait un JSON depuis la réponse IA — tolérant aux fences
    markdown que certains modèles ajoutent malgré tout."""
    s = raw.strip()
    # Strip fences ```json ... ```
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        # Fallback : essayer de récupérer le 1er { au dernier }.
        start = s.find("{")
        end = s.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(s[start : end + 1])
            except Exception:  # noqa: BLE001
                return None
        return None


# --------------------------------------------------------------------------
# Fallback 100 % local : TextRank-light
# --------------------------------------------------------------------------

# Stopwords français courants — utilisés pour ignorer les mots vides
# dans le scoring. Liste minimale embarquée pour éviter une dépendance
# externe (nltk). Aussi efficace pour des transcripts business courts.
_FR_STOPWORDS = frozenset(
    """
    a à au aux avec ce ces dans de des du elle en et eux il ils je la
    le les leur lui ma mais me même mes moi mon ne nos notre nous on
    ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu
    un une vos votre vous c d j l à è ç m n s t y est sont être
    avoir fait fait faire dit dire être étais étaient j'ai j'avais
    j'étais cela ça ceci celui-ci celle-ci ceux celles donc alors
    aussi très plus moins comme bien après avant pendant si oui non
    """.split()
)


def _split_sentences(text: str) -> list[str]:
    """Découpe un texte en phrases. Tolère la ponctuation aléatoire
    d'une dictée vocale (retours à la ligne = séparateurs)."""
    # Normalise les sauts de ligne + ponctuation.
    t = re.sub(r"\s+", " ", text.strip())
    if not t:
        return []
    # Split sur . ! ? suivi d'espace + majuscule, ou retour de ligne.
    raw = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý])", t)
    out = [s.strip(" .!?,") for s in raw if len(s.strip()) > 5]
    return out


def _tokenize(s: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-zà-ÿ0-9'-]{2,}", s.lower())
        if w not in _FR_STOPWORDS
    ]


def _textrank_summary(text: str, max_sentences: int = 4) -> str:
    """TextRank-light : score chaque phrase par la somme TF-IDF de ses
    mots-clés. Retient les top-N. Pas de matrice de similarité (trop
    lourd pour le bénéfice), juste un ranking par densité d'info."""
    sentences = _split_sentences(text)
    if not sentences:
        return text[:300]
    if len(sentences) <= max_sentences:
        return ". ".join(sentences) + "."

    # Fréquence globale des mots-clés.
    global_freq: Counter = Counter()
    sent_tokens: list[list[str]] = []
    for s in sentences:
        toks = _tokenize(s)
        sent_tokens.append(toks)
        global_freq.update(toks)

    # Score = somme des fréquences (mots fréquents = thèmes centraux),
    # normalisée par sqrt(longueur) pour ne pas favoriser les longues.
    import math

    scored = []
    for idx, (s, toks) in enumerate(zip(sentences, sent_tokens)):
        if not toks:
            continue
        score = sum(global_freq[t] for t in toks) / math.sqrt(len(toks))
        scored.append((score, idx, s))
    if not scored:
        return ". ".join(sentences[:max_sentences]) + "."

    # Top-N par score, mais on les remet dans l'ordre du transcript.
    top = sorted(scored, key=lambda x: -x[0])[:max_sentences]
    top.sort(key=lambda x: x[1])
    return ". ".join(t[2] for t in top) + "."


def _extract_action_items(text: str) -> list[dict]:
    """Repère des phrases ressemblant à des actions : verbes d'action
    en début / impératif. Heuristique simple, sans IA."""
    action_starters = re.compile(
        r"^(faire|envoyer|contacter|appeler|relancer|signer|"
        r"rédiger|valider|vérifier|finaliser|préparer|organiser|"
        r"planifier|réserver|acheter|vendre|négocier|confirmer|"
        r"il faut|on doit|je dois|on va|je vais)\b",
        re.IGNORECASE,
    )
    out: list[dict] = []
    for s in _split_sentences(text):
        if action_starters.match(s):
            out.append(
                {
                    "title": s[:120],
                    "owner": None,
                    "entreprise_hint": None,
                    "due": None,
                }
            )
        if len(out) >= 5:
            break
    return out


def _heuristic_section_summary(title: str, transcript: str) -> dict:
    """Fallback purement local quand AUCUN provider IA n'est dispo.
    Produit un résumé extractif TextRank + une heuristique d'actions."""
    t = (transcript or "").strip()
    if not t:
        return {
            "summary": f"Section « {title} » vide.",
            "decisions": [],
            "action_items": [],
            "open_questions": [],
            "risks": [],
        }
    summary = _textrank_summary(t, max_sentences=4)
    actions = _extract_action_items(t)
    return {
        "summary": summary,
        "decisions": [],
        "action_items": actions,
        "open_questions": [],
        "risks": [],
    }


# --------------------------------------------------------------------------
# Public API — appelle le factory IA, fallback heuristique automatique
# --------------------------------------------------------------------------


async def summarize_section(
    title: str,
    transcript: str,
    entreprises_context: Optional[list[dict]] = None,
) -> dict:
    """Résume une section. Retourne toujours un dict valide.

    Cascade : Gemini → Anthropic → Groq (selon AI_PROVIDER env).
    Fallback final : TextRank local 100 % offline."""
    text = (transcript or "").strip()
    if not text:
        return _heuristic_section_summary(title, "")
    if not is_configured():
        return _heuristic_section_summary(title, text)

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

    prompt = (
        f"## Section\n{title}\n\n"
        + ents_block
        + f"## Transcript brut\n{text[:30_000]}\n\n"
        "Génère le JSON selon le schéma."
    )

    try:
        res = await complete(
            prompt=prompt,
            system=SECTION_SUMMARY_PROMPT,
            max_tokens=2000,
            temperature=SUMMARY_TEMPERATURE,
        )
    except AIProviderError as exc:
        log.warning("Section summary failed (all AI providers): %s", exc)
        return _heuristic_section_summary(title, text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Section summary unexpected error: %s", exc)
        return _heuristic_section_summary(title, text)

    parsed = _parse_ai_json(res.text)
    if parsed is None:
        log.warning(
            "Section summary unparseable (%s) — fallback heuristique",
            res.provider,
        )
        return _heuristic_section_summary(title, text)
    return parsed


async def summarize_global(sections: list[dict]) -> str:
    """sections = [{ title, summary, decisions, action_items, ... }]
    Retourne un résumé global texte (narratif).

    Fallback final : concaténation propre des résumés de section
    (sans IA, pas idéal mais lisible)."""
    if not sections:
        return ""

    # Assemblage du prompt à partir des résumés structurés.
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

    fallback_text = "\n\n---\n\n".join(blocks)

    if not is_configured():
        return fallback_text

    try:
        res = await complete(
            prompt="## Sections de la rencontre\n\n" + fallback_text,
            system=GLOBAL_SUMMARY_PROMPT,
            max_tokens=3000,
            temperature=SUMMARY_TEMPERATURE,
        )
        return res.text.strip() or fallback_text
    except AIProviderError as exc:
        log.warning("Global summary failed (all AI providers): %s", exc)
        return fallback_text
    except Exception as exc:  # noqa: BLE001
        log.warning("Global summary unexpected error: %s", exc)
        return fallback_text


async def clean_transcript(
    transcript: str,
    entreprises_context: Optional[list[dict]] = None,
) -> str:
    """Réécrit un transcript de dictée vocale en français québécois
    propre. Corrige les homophones, accents, ponctuation, mots mal
    entendus. Ne résume pas.

    Fallback : si aucun provider IA n'est dispo, retourne le transcript
    brut inchangé (ne casse jamais la dictée)."""
    text = (transcript or "").strip()
    if not text:
        return ""
    if not is_configured():
        return text

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
        res = await complete(
            prompt="## Transcript brut à corriger\n\n" + text[:30_000],
            system=TRANSCRIPT_CLEANUP_PROMPT + ents_block,
            max_tokens=4000,
            temperature=SUMMARY_TEMPERATURE,
        )
        return res.text.strip() or text
    except AIProviderError as exc:
        log.warning("Transcript cleanup failed (all AI providers): %s", exc)
        return text
    except Exception as exc:  # noqa: BLE001
        log.warning("Transcript cleanup unexpected error: %s", exc)
        return text


TRANSCRIBE_PROMPT = (
    "Tu transcris l'enregistrement audio d'une rencontre d'affaires en "
    "français québécois. Règles :\n"
    "- Transcris fidèlement TOUT ce qui est dit, en français correct "
    "(corrige accents et homophones évidents, garde le sens exact).\n"
    "- Quand tu distingues plusieurs interlocuteurs, préfixe chaque "
    "réplique par « Intervenant 1 : », « Intervenant 2 : », etc. (ou "
    "leur prénom si mentionné dans l'audio).\n"
    "- Saute une ligne entre les répliques.\n"
    "- N'ajoute AUCUN commentaire, résumé ou titre — seulement la "
    "transcription."
)

# Limite inline Gemini (~20 MB par requête). On garde une marge.
_MAX_TRANSCRIBE_BYTES = 18 * 1024 * 1024

_AUDIO_MIME_FALLBACK = "audio/mpeg"
_AUDIO_MIME_OK = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/aac",
    "audio/wav",
    "audio/x-wav",
    "audio/ogg",
    "audio/webm",
    "audio/flac",
    "video/mp4",
    "video/webm",
}


async def transcribe_audio(
    filename: str, content_type: str, data: bytes
) -> str:
    """Transcrit un enregistrement audio via Gemini (gratuit).

    Gemini accepte l'audio nativement dans ``generateContent`` — on
    cascade sur les modèles de ``GEMINI_MODEL_CASCADE`` comme pour le
    texte. Lève RuntimeError avec un message clair si la clé Gemini est
    absente ou si le fichier dépasse la limite inline (~18 MB ≈ 30-45
    minutes d'audio compressé)."""
    import os as _os

    from app.integrations.ai._base import AIProviderError as _AIError
    from app.integrations.ai._gemini import GeminiProvider

    if len(data) > _MAX_TRANSCRIBE_BYTES:
        raise RuntimeError(
            "Fichier audio trop gros pour la transcription (max ~18 MB). "
            "Astuce : exporte en m4a/mp3 compressé, ou découpe "
            "l'enregistrement en parties."
        )

    mime = (content_type or "").split(";")[0].strip().lower()
    if mime not in _AUDIO_MIME_OK:
        mime = _AUDIO_MIME_FALLBACK

    provider = GeminiProvider()
    if not provider.api_key:
        raise RuntimeError(
            "Transcription indisponible : la clé GEMINI_API_KEY n'est pas "
            "configurée côté serveur."
        )

    cascade = [
        m.strip()
        for m in (
            _os.getenv("GEMINI_MODEL_CASCADE")
            or "gemini-2.5-flash,gemini-2.5-pro,gemini-2.0-flash"
        ).split(",")
        if m.strip()
    ]
    last_err: Exception | None = None
    for model in cascade:
        try:
            res = await provider.complete_with_media(
                prompt=(
                    "Transcris cet enregistrement de rencontre "
                    f"(fichier : {filename})."
                ),
                media_bytes=data,
                mime_type=mime,
                system=TRANSCRIBE_PROMPT,
                max_tokens=60_000,
                temperature=0.1,
                model=model,
            )
            text = (res.text or "").strip()
            if text:
                return text
            last_err = RuntimeError(f"{model} : transcription vide")
        except _AIError as exc:
            log.warning("Transcription %s a échoué : %s", model, exc)
            last_err = exc
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Transcription %s erreur inattendue : %s", model, exc
            )
            last_err = exc
    raise RuntimeError(
        "La transcription a échoué sur tous les modèles Gemini "
        f"({'; '.join(cascade)}). Détail : {str(last_err)[:200]}"
    )
