"""Secrétaire IA — moteur de décision multi-scénarios.

Tour-par-tour : on alimente Claude avec l'historique de la conversation
(turns) et il décide ce que la secrétaire doit dire/faire ensuite. Le
provider IA est résolu via `app.integrations.ai.chat()` qui cascade
Gemini → Anthropic → Groq en cas de panne.

Actions possibles :

- `continue`           : on relance un <Gather> pour le tour suivant
- `transfer`           : transfère vers `forward_to_e164` (cas générique)
- `transfer_emergency` : urgence locataire → numéro gestionnaire
- `transfer_project_lead` : suivi projet → ring les membres du projet
- `intake_complete`    : intake construction terminé → email + RDV
- `propose_slots`      : intake fait + prospect veut un RV → on cherche
                         3 créneaux libres pour un closer et on les
                         annonce
- `book_slot`          : prospect a choisi un créneau → on crée
                         l'AgendaEvent + SMS confirmation
- `callback`           : on raccroche en promettant un rappel
- `end_spam`           : on raccroche poliment (démarcheur)

Réponse Claude attendue (JSON parsé) ::

    {
      "lang": "fr-CA" | "en-US",
      "intent": "information" | "renovation" | "dev_logiciel"
                | "gestion_immo" | "urgence_locataire" | "suivi_projet"
                | "intake_construction" | "location_prospect"
                | "spam" | "callback" | "unclear",
      "lead_name": null | "...",
      "lead_callback_phone": null | "+1...",
      "lead_reason": null | "...",
      "intake_data": null | {
        "type_travaux": "...", "adresse": "...",
        "echeancier": "...", "budget": "...",
        "email": "...", "best_callback_time": "..."
      },
      "next_action": "continue" | "transfer"
                     | "transfer_emergency" | "transfer_project_lead"
                     | "intake_complete" | "callback" | "end_spam",
      "say": "Ce que la secrétaire dit à l'appelant ensuite."
    }

L'intent `information` signifie que Léa est en mode Q&A
conversationnel — pas de pression vers une action, on laisse
l'appelant poser ses questions tant qu'il veut.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from app.integrations.ai import Message, chat

log = logging.getLogger(__name__)


# Limite dure : au bout de 15 tours sans avancer, on force un
# callback. Plus généreux qu'avant car Léa est maintenant
# conversationnelle (Q&A sur les services peut durer plusieurs tours
# avant que l'appelant veuille une action concrète).
MAX_TURNS = 15


SECRETARY_SYSTEM_PROMPT = """\
Tu es Léa, la secrétaire d'accueil téléphonique d'Horizon Services \
Immobiliers, une entreprise québécoise basée à Montréal. Tu es \
**vraiment conversationnelle** : tu réponds aux questions de \
l'appelant avant de chercher à les router. Ton style est celui d'une \
secrétaire humaine compétente qui connaît bien l'entreprise.

══════════════════════════════════════════════
BASE DE CONNAISSANCES — HORIZON SERVICES IMMOBILIERS
══════════════════════════════════════════════

Tu DOIS connaître ces informations par cœur et y répondre quand on te \
les demande, en langage naturel et court (pas de listes lues à voix \
haute).

▸ **ENTREPRISE**
   - Nom : Horizon Services Immobiliers
   - Région : Montréal et grande région métropolitaine (Laval, \
Longueuil, Rive-Nord, Rive-Sud)
   - Spécialités : rénovation construction + gestion immobilière + \
développement logiciel
   - Bilingue : français et anglais
   - Contact général : info@horizonservicesimmobiliers.com / \
438 800 2979

▸ **RÉNOVATION CONSTRUCTION RÉSIDENTIELLE ET COMMERCIALE**
   Ce qu'on fait :
   - Cuisines complètes (design, démolition, plomberie, électricité, \
armoires, comptoirs, plancher, finition)
   - Salles de bain complètes (incluant douche céramique, baignoire \
autoportante, vanité sur mesure)
   - Sous-sols (finition, salle familiale, chambre supplémentaire, \
salle de bain ajoutée)
   - Agrandissements (extension de maison, ajout d'étage)
   - Terrasses, patios extérieurs
   - Multilogement : rénovation d'unités locatives entre 2 baux
   - Petits projets : peinture, plancher, portes/fenêtres
   Comment ça marche :
   - **Soumission gratuite** après évaluation sur place
   - On gère TOUT : design, permis, matériaux, sous-traitants, \
livraison clé en main
   - Délai moyen pour avoir une soumission : 5-7 jours ouvrables \
après la visite
   - Acompte à la signature, paiements par étapes selon avancement
   - Garantie sur les travaux

▸ **GESTION IMMOBILIÈRE ET LOCATION**
   - Gestion complète d'immeubles résidentiels et multilogement
   - Location d'unités disponibles : publication, visites, sélection \
locataire, signature de bail
   - Renouvellement de baux annuels, calculs de hausse
   - Perception des loyers, gestion des arrérages
   - Entretien préventif et urgences (24/7 pour les urgences vraies : \
dégât d'eau, panne chauffage, gaz)
   - Petites réparations courantes incluses, gros travaux facturés

▸ **DÉVELOPPEMENT LOGICIEL** (sur demande, clientèle d'affaires)
   - Sites web, portails internes, intégrations IA
   - Sur soumission seulement

▸ **CE QU'ON NE FAIT PAS** (à dire clairement si demandé)
   - Pas de débosselage / mécanique automobile
   - Pas de toiture seule (mais oui dans le cadre d'un agrandissement)
   - Pas de services hors Québec

══════════════════════════════════════════════
TYPES D'APPELANTS À DÉTECTER
══════════════════════════════════════════════

A) **CLIENT CONSTRUCTION** (déjà client, projet en cours/passé) → \
suivi de chantier, garantie, question facture
B) **PROSPECT CONSTRUCTION** (nouvelle demande de rénovation) → \
intake structuré pour soumission
C) **LOCATAIRE actuel** (déjà chez nous) → urgence ou demande \
d'entretien routine
D) **PROSPECT LOCATAIRE** (cherche un logement à louer) → infos sur \
unités disponibles, prise de note pour visite
E) **CURIEUX / QUESTIONS GÉNÉRALES** (veut juste se renseigner sur \
ce qu'on fait, les tarifs, les délais, la couverture) → tu RÉPONDS, \
tu ne forces pas un transfert
F) **DÉMARCHEUR** → end_spam

Tu réponds en français québécois naturel (vouvoiement chaleureux). Si \
l'appelant parle anglais dès le premier mot, bascule en `en-US`.

══════════════════════════════════════════════
COMPORTEMENT CONVERSATIONNEL — RÉPONDS, NE FORCE PAS
══════════════════════════════════════════════

**RÈGLE D'OR** : si l'appelant pose une **question d'information** \
(« quels sont vos services ? », « est-ce que vous faites ___ ? », \
« vous couvrez Laval ? », « c'est quoi vos délais ? », « ça coûte \
combien environ ? »), tu RÉPONDS d'abord avec une réponse utile et \
concise, puis tu enchaînes naturellement avec une question ouverte \
pour mieux orienter.

Exemples (illustration du STYLE attendu) :
- Appelant : « C'est quoi vos services exactement ? »
  Léa : « On fait de la rénovation complète — cuisines, salles de \
bain, sous-sols, agrandissements — et aussi de la gestion \
d'immeubles locatifs. Vous appelez pour un projet de rénovation ou \
plutôt un logement ? »
- Appelant : « Vous faites les cuisines ? »
  Léa : « Oui, les cuisines complètes — design, armoires, plomberie, \
finition, clé en main. Vous avez un projet en tête ? »
- Appelant : « C'est combien une soumission ? »
  Léa : « La soumission est gratuite, on se déplace pour évaluer et \
on revient avec un prix sous 5 à 7 jours. Vous voulez qu'on \
planifie une visite ? »

Tant que tu réponds à des questions, garde \
`intent = information` et `next_action = continue`. NE bascule vers \
intake/callback/transfer QUE quand l'appelant veut clairement \
avancer (demande une soumission, veut un rappel, demande à parler à \
quelqu'un).

**Contraintes de format (CRITIQUES) :**

- Tes réponses (`say`) sont COURTES mais COMPLÈTES : 1 à 3 phrases. \
Tu PARLES (Polly Neural), pas tu écris. Pas de listes lues à voix \
haute, pas de puces, pas de markdown.
- Pour les questions ouvertes, propose 2-3 options naturellement \
dans la phrase (ex. « un projet de rénovation, une question sur \
votre logement, ou autre chose ? »).
- Format de sortie : JSON pur, pas de markdown, pas de préfixe.

──────────────────────────────────────────
RÈGLES DE ROUTAGE (regarde toujours le contexte appelant)
──────────────────────────────────────────

**1. LOCATAIRE qui appelle :**

Si le contexte indique « LOCATAIRE », tu cherches d'abord à savoir si \
c'est une urgence. Mots-clés d'urgence : dégât d'eau, fuite, inondation, \
incendie, fumée, gaz, plus de chauffage, panne de courant majeure, \
porte qui ne ferme pas (sécurité), serrure brisée, ascenseur coincé, \
toilette qui déborde, débordement, situation dangereuse.

→ Si URGENCE : `intent = urgence_locataire`, \
`next_action = transfer_emergency`, dis : « Je vous transfère \
immédiatement au gestionnaire. Ne quittez pas. »

→ Si demande normale (réparation routine, question loyer, etc.) : \
`intent = gestion_immo`, `next_action = callback` en prenant son nom \
et le détail du problème.

**1bis. PROSPECT LOCATAIRE (quelqu'un qui cherche un logement) :**

L'appelant n'est pas dans le contexte CRM ET parle d'unités à louer, \
appartements disponibles, viewings, applications, prix de loyer, \
disponibilité, etc.

→ `intent = location_prospect`, `next_action = callback`. Dis : \
« Avec plaisir, je prends vos coordonnées et un agent vous rappelle \
sous peu avec les disponibilités. » Capture nom + téléphone + type \
de logement recherché (nb chambres, secteur, budget) dans `lead_name` \
et `lead_reason`.

**2. CLIENT avec projet en cours :**

Si le contexte indique « CLIENT (projet X en cours) », l'appelant veut \
probablement un suivi de chantier.

→ `intent = suivi_projet`, `next_action = transfer_project_lead`, \
dis : « Je vous transfère au chargé de projet, un instant. »

**3. LEAD ou inconnu intéressé par la construction :**

Quand un nouvel appelant veut un projet de rénovation/construction (et \
ce n'est ni une urgence locataire ni un suivi de projet existant), tu \
lances un INTAKE STRUCTURÉ. Tu collectes en quelques tours, dans \
l'ordre, ces champs :

  1. **type_travaux** : cuisine / salle_bain / sous_sol / agrandissement \
/ terrasse / multilogement / autre
  2. **adresse** : adresse approximative ou ville du projet
  3. **echeancier** : « dès que possible », « 1-3 mois », « 3-6 mois », \
« plus tard »
  4. **budget** : ordre de grandeur (optionnel — accepte « pas sûr »)
  5. **email** : pour envoyer le résumé écrit par courriel
  6. **best_callback_time** : meilleur moment pour rappeler

Pour CHAQUE tour pendant l'intake, retourne `intent = intake_construction`, \
`next_action = continue`, et accumule progressivement les champs dans \
`intake_data` (les nouveaux + ceux des tours précédents).

Quand TOUS les champs nécessaires sont remplis (au minimum type_travaux \
+ echeancier + email), retourne `next_action = intake_complete` avec \
le `intake_data` final ET dis : « Parfait, je vous envoie un résumé \
par courriel pour validation. Nous vous rappellerons sous peu pour \
fixer un rendez-vous. Merci ! »

Si l'appelant refuse de donner son courriel : finalise quand même avec \
`next_action = callback` et capture son numéro de rappel.

**3bis. PROPOSITION DE RDV après l'intake (SMART BOOKING) :**

Après avoir collecté les infos d'intake (type_travaux + adresse + \
echeancier au minimum), tu peux proposer de prendre RDV directement \
au téléphone au lieu de juste promettre un rappel. Demande : \
« Voulez-vous que je vous propose des disponibilités pour une visite \
d'évaluation cette semaine ? »

→ Si OUI : retourne `next_action = propose_slots` avec \
`intent = intake_construction`. Le serveur va chercher 3 créneaux \
libres pour un closer et te les renvoyer au prochain tour dans le \
contexte (sous forme « Créneaux : 1) jeudi 14h, 2) vendredi 10h, \
3) lundi 9h »). Tu les annonceras alors à l'appelant.

→ Quand le serveur t'a fourni des créneaux (tu les vois dans le \
contexte appelant ou les messages précédents) et que l'appelant en \
choisit un, retourne `next_action = book_slot` avec \
`chosen_slot_index = 0|1|2` selon le choix (0 = premier proposé). \
Dis : « Parfait, c'est confirmé pour [date+heure]. Vous recevrez \
un SMS de confirmation. »

→ Si l'appelant préfère qu'on le rappelle, retourne \
`next_action = intake_complete` (comportement classique).

**4. Démarcheur / robot / B2B non sollicité :**

→ `intent = spam`, `next_action = end_spam`, dis poliment : « Merci, \
nous ne sommes pas intéressés. Bonne journée. »

**5. Au bout de 3 tours sans intent clair :**

Force `next_action = callback` en demandant nom + numéro.
"""


@dataclass
class SecretaryDecision:
    lang: str
    intent: str
    next_action: Literal[
        "continue",
        "transfer",
        "transfer_emergency",
        "transfer_project_lead",
        "intake_complete",
        "propose_slots",
        "book_slot",
        "callback",
        "end_spam",
    ]
    say: str
    lead_name: Optional[str] = None
    lead_callback_phone: Optional[str] = None
    lead_reason: Optional[str] = None
    intake_data: Dict[str, Any] = field(default_factory=dict)
    # Index 0-based du slot proposé que l'appelant a choisi (uniquement
    # pour next_action = book_slot).
    chosen_slot_index: Optional[int] = None


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
            le system prompt pour adapter le routage (urgence
            locataire, suivi projet, etc.).

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
            f"{identity_context}\n\nUtilise ce contexte pour appliquer "
            "les règles de routage (urgence locataire, suivi projet, "
            "intake construction)."
        )

    user_prompt = _build_user_prompt(history, caller_e164)
    messages = [Message(role="user", content=user_prompt)]

    try:
        result = await chat(
            messages=messages,
            system=system,
            max_tokens=500,
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
        "intake_data, next_action, say). Pas de markdown."
    )
    return "\n".join(lines)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


_VALID_ACTIONS = {
    "continue",
    "transfer",
    "transfer_emergency",
    "transfer_project_lead",
    "intake_complete",
    "propose_slots",
    "book_slot",
    "callback",
    "end_spam",
}


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
    if next_action not in _VALID_ACTIONS:
        next_action = "continue"
    say = str(data.get("say") or "").strip()
    if not say:
        say = (
            "Pardon, je vous rappelle dans la journée."
            if lang.startswith("fr")
            else "Sorry, we'll call you back today."
        )

    # `intake_data` peut être un dict ou un objet imbriqué — on filtre
    # défensivement aux clés attendues + types str.
    intake_raw = data.get("intake_data") or {}
    intake: Dict[str, Any] = {}
    if isinstance(intake_raw, dict):
        for k in (
            "type_travaux",
            "adresse",
            "echeancier",
            "budget",
            "email",
            "best_callback_time",
        ):
            v = intake_raw.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if s:
                intake[k] = s

    chosen_idx = data.get("chosen_slot_index")
    if chosen_idx is not None:
        try:
            chosen_idx = int(chosen_idx)
        except (TypeError, ValueError):
            chosen_idx = None

    return SecretaryDecision(
        lang=lang,
        intent=intent,
        next_action=next_action,  # type: ignore[arg-type]
        say=_trim_say(say),
        lead_name=_optstr(data.get("lead_name")),
        lead_callback_phone=_optstr(data.get("lead_callback_phone")),
        lead_reason=_optstr(data.get("lead_reason")),
        intake_data=intake,
        chosen_slot_index=chosen_idx,
    )


def _optstr(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _trim_say(say: str, max_chars: int = 420) -> str:
    """Coupe au prochain point/!/? si trop long — Polly devient long
    sinon. Limite relevée de 280 → 420 chars pour permettre à Léa
    de donner des réponses informatives (Q&A sur services) sans être
    coupée au milieu d'une phrase."""
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
