"""Secrétaire IA — moteur de décision Phase 2.

Tour-par-tour : on alimente Claude avec l'historique de la conversation
(turns) et il décide ce que la secrétaire doit dire/faire ensuite. Le
provider IA est résolu via `app.integrations.ai.chat()` qui cascade
Gemini → Anthropic → Groq en cas de panne.

La secrétaire a 4 actions possibles :

- `continue`       : on relance un <Gather> pour écouter le prochain
                     tour de l'appelant
- `transfer`       : on transfère l'appel vers `forward_to_e164`
- `callback`       : on raccroche après avoir promis qu'on rappelle
                     (et on créera un ContactRequest côté endpoint)
- `end_spam`       : on raccroche poliment (démarcheur / spam)

Réponse Claude attendue (JSON parsé) ::

    {
      "lang": "fr-CA" | "en-US",
      "intent": "renovation" | "dev_logiciel" | "gestion_immo"
                | "spam" | "urgence" | "callback" | "unclear",
      "lead_name": null | "...",
      "lead_callback_phone": null | "+1...",
      "lead_reason": null | "...",
      "next_action": "continue" | "transfer" | "callback" | "end_spam",
      "say": "Ce que la secrétaire dit à l'appelant ensuite."
    }
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Literal, Optional

from app.integrations.ai import Message, chat

log = logging.getLogger(__name__)


# Limite dure : au bout de 6 tours sans intent clair, on force un
# callback. Permet d'éviter une conversation infinie qui consomme du
# crédit Twilio.
MAX_TURNS = 6


SECRETARY_SYSTEM_PROMPT = """\
Tu es la secrétaire d'accueil téléphonique d'Horizon Services Immobiliers, \
une entreprise québécoise basée à Montréal qui offre :

- **Rénovation construction** (cuisines, salles de bain, multilogement) — \
contact principal : Steven
- **Développement logiciel** (sites web, portails internes, IA) — \
contact principal : Steven
- **Gestion immobilière / investissement** (achats d'immeubles, \
optimisation locative) — contact principal : Steven

Tu réponds aux appels entrants en français québécois naturel (vouvoiement \
poli mais chaleureux). Si l'appelant parle en anglais dès le premier mot \
ou demande de switcher en anglais, bascule en `en-US`.

Ton objectif :

1. **Identifier rapidement** la raison de l'appel
2. **Filtrer** les démarcheurs / spam (téléphonie, marketing, etc.) → \
`end_spam`
3. **Transférer** vers le bon contact si la demande est légitime et \
relève d'un service d'Horizon → `transfer`
4. **Prendre un message** (`callback`) si transfert impossible (hors \
heures) ou si l'appelant préfère qu'on le rappelle, en capturant son \
nom et son numéro

**Contraintes critiques :**

- Tes réponses (`say`) sont **TRÈS COURTES** : 1 phrase, max 2. \
Tu PARLES (Polly Neural), pas tu n'écris. Évite les listes, les \
puces, les paragraphes.
- Pose **UNE question à la fois**.
- Si la demande est claire dès le 1er tour, va directement à \
`transfer` ou `end_spam`. N'allonge pas inutilement.
- Si tu n'as toujours pas compris au 3e tour, force `callback` en \
demandant le nom + numéro.
- Format de sortie : **JSON pur uniquement**, pas de markdown, pas de \
préfixe/suffixe.

**Mapping des intents → action :**

- `renovation`, `dev_logiciel`, `gestion_immo` → `transfer` (en heures \
ouvrables) ou `callback` (sinon)
- `spam` (démarchage, robocall, marketing B2B non sollicité) → \
`end_spam`
- `urgence` (mots-clés "urgent", "urgence", "emergency") → `transfer` \
immédiat sans qualification supplémentaire
- `callback` : l'appelant a demandé explicitement à être rappelé
- `unclear` : tu n'es pas sûre → `continue` (au max 3 tours)
"""


@dataclass
class SecretaryDecision:
    lang: str
    intent: str
    next_action: Literal["continue", "transfer", "callback", "end_spam"]
    say: str
    lead_name: Optional[str] = None
    lead_callback_phone: Optional[str] = None
    lead_reason: Optional[str] = None


async def decide_initial_greeting(
    lang: str = "fr-CA",
    *,
    personalized_say: Optional[str] = None,
) -> SecretaryDecision:
    """Phrase d'accueil — pas besoin d'IA, on a une formulation fixe.

    Si `personalized_say` est fourni (issu de l'identification CRM),
    on l'utilise tel quel. Sinon, greeting générique.

    Conserver une greeting statique fait gagner ~1 sec de latence sur le
    premier décroché (pas d'appel API à attendre) et donne une expérience
    plus prévisible à l'appelant.
    """
    if personalized_say:
        return SecretaryDecision(
            lang=lang,
            intent="unclear",
            next_action="continue",
            say=personalized_say,
        )
    if lang.startswith("en"):
        return SecretaryDecision(
            lang="en-US",
            intent="unclear",
            next_action="continue",
            say=(
                "Hello, you've reached Horizon Services. "
                "How may I help you today?"
            ),
        )
    return SecretaryDecision(
        lang="fr-CA",
        intent="unclear",
        next_action="continue",
        say=(
            "Bonjour, Horizon Services Immobiliers. "
            "Comment puis-je vous aider ?"
        ),
    )


async def decide_next_turn(
    history: List[tuple[str, str]],
    *,
    current_turn_count: int,
    caller_e164: str,
    identity_context: Optional[str] = None,
) -> SecretaryDecision:
    """Demande à Claude la prochaine action de la secrétaire.

    Args:
        history: liste de (role, text). `role` ∈ {'assistant', 'user'}.
        current_turn_count: nombre de tours déjà échangés (assistant+user).
        caller_e164: numéro de l'appelant — sert d'indice (préfixe = pays).
        identity_context: ligne décrivant l'identité CRM si reconnu
            (sortie de `build_identity_context_block`). Injectée dans
            le system prompt pour adapter le ton.

    Returns:
        Une `SecretaryDecision`. En cas d'échec IA, retombe sur un
        callback poli — on ne plante jamais l'appel.
    """
    if current_turn_count >= MAX_TURNS:
        return _fallback_callback("max_turns_reached")

    system = SECRETARY_SYSTEM_PROMPT
    if identity_context:
        system = (
            f"{SECRETARY_SYSTEM_PROMPT}\n\n--- CONTEXTE APPELANT ---\n"
            f"{identity_context}\n\nUtilise ce contexte pour personnaliser "
            "tes réponses (mentionner leur projet en cours, leur logement, "
            "etc.) et adapter le routage."
        )

    user_prompt = _build_user_prompt(history, caller_e164)
    messages = [Message(role="user", content=user_prompt)]

    try:
        result = await chat(
            messages=messages,
            system=system,
            max_tokens=400,
            temperature=0.4,
        )
        return _parse_decision(result.text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Secretary IA failed (%s) — falling back to callback", exc)
        return _fallback_callback(str(exc))


def _build_user_prompt(
    history: List[tuple[str, str]], caller_e164: str
) -> str:
    """Format compact de l'historique pour Claude."""
    lines = [f"Numéro appelant : {caller_e164 or 'inconnu'}", "", "Historique :"]
    for role, text in history:
        tag = "Secrétaire" if role == "assistant" else "Appelant"
        lines.append(f"- {tag} : {text}")
    lines.append("")
    lines.append(
        "Réponds UNIQUEMENT par un objet JSON conforme au schéma "
        "(lang, intent, lead_name, lead_callback_phone, lead_reason, "
        "next_action, say). Pas de markdown, pas de commentaires."
    )
    return "\n".join(lines)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_decision(text: str) -> SecretaryDecision:
    """Tolère les wrappers ``` ```json ... ``` et le texte autour."""
    match = _JSON_RE.search(text)
    if not match:
        log.warning("Secretary returned non-JSON: %s", text[:200])
        return _fallback_callback("non_json_response")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        log.warning("Secretary returned invalid JSON (%s): %s", exc, text[:200])
        return _fallback_callback("invalid_json")

    lang = str(data.get("lang") or "fr-CA")
    if lang not in ("fr-CA", "en-US"):
        lang = "fr-CA"
    intent = str(data.get("intent") or "unclear")
    next_action = str(data.get("next_action") or "continue")
    if next_action not in ("continue", "transfer", "callback", "end_spam"):
        next_action = "continue"
    say = str(data.get("say") or "").strip()
    if not say:
        say = (
            "Pardon, je vous rappelle dans la journée."
            if lang.startswith("fr")
            else "Sorry, we'll call you back today."
        )

    return SecretaryDecision(
        lang=lang,
        intent=intent,
        next_action=next_action,  # type: ignore[arg-type]
        say=_trim_say(say),
        lead_name=_optstr(data.get("lead_name")),
        lead_callback_phone=_optstr(data.get("lead_callback_phone")),
        lead_reason=_optstr(data.get("lead_reason")),
    )


def _optstr(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _trim_say(say: str, max_chars: int = 280) -> str:
    """Coupe au prochain point/!/? si trop long — Polly devient long sinon."""
    if len(say) <= max_chars:
        return say
    cut = say[:max_chars]
    last = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if last >= 80:
        return cut[: last + 1]
    return cut.rstrip() + "…"


def _fallback_callback(reason: str) -> SecretaryDecision:
    """Réponse de secours quand l'IA est indisponible — on ne raccroche
    jamais sec, on promet un rappel."""
    log.info("Secretary fallback callback (reason=%s)", reason)
    return SecretaryDecision(
        lang="fr-CA",
        intent="callback",
        next_action="callback",
        say=(
            "Merci pour votre appel. Je note votre demande et nous vous "
            "rappellerons sous peu. Au revoir."
        ),
    )
