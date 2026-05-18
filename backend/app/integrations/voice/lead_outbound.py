"""AI outbound — Léa appelle automatiquement un nouveau lead pour qualifier.

Déclenché 60 sec après la création d'un `ContactRequest` (formulaire web
ou création manuelle CRM). Twilio appelle le numéro de l'appelant et
exécute le TwiML fourni par `/twilio/lead-outbound` qui pilote une
conversation IA semblable à la secrétaire Phase 2, mais :

- Contexte pré-rempli (nom du lead, type de projet, message)
- Léa initie au lieu de répondre — ton plus chaleureux et direct
- Objectif explicite : qualifier (budget, timeline) + commit RDV ou
  callback dans les 24-48 h
- Mise à jour automatique de la fiche CRM à la fin (status,
  kanban_column, internal_notes avec résumé IA)

Best-effort : tout échec (lead injoignable, IA en panne, Twilio down)
ne casse jamais la création du ContactRequest initial. On log et on
continue — un humain reprendra la main depuis le kanban.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.integrations.ai import Message, chat
from app.integrations.voice.twilio_provider import TwilioVoiceProvider
from app.models.contact_request import ContactRequest
from app.models.voice import Call, CallDirection, CallStatus, PhoneNumber

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Décision de la secrétaire outbound (parser dédié — actions différentes
# de la secrétaire entrante)
# ---------------------------------------------------------------------


OutboundAction = Literal[
    "continue",
    "rdv_demain_am",
    "rdv_demain_pm",
    "rdv_apres_demain",
    "callback",
    "lost",
    "complete_no_action",
]


@dataclass
class LeadDecision:
    lang: str
    next_action: OutboundAction
    say: str
    qualified_budget: Optional[str] = None
    qualified_timeline: Optional[str] = None
    callback_when: Optional[str] = None
    summary: Optional[str] = None


MAX_OUTBOUND_TURNS = 10


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_VALID_ACTIONS = {
    "continue", "rdv_demain_am", "rdv_demain_pm", "rdv_apres_demain",
    "callback", "lost", "complete_no_action",
}


def _parse_lead_decision(text: str) -> LeadDecision:
    match = _JSON_RE.search(text or "")
    if not match:
        return _fallback_lead_callback("non_json")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _fallback_lead_callback("invalid_json")

    lang = str(data.get("lang") or "fr-CA")
    if lang not in ("fr-CA", "en-US"):
        lang = "fr-CA"
    action = str(data.get("next_action") or "continue")
    if action not in _VALID_ACTIONS:
        action = "continue"
    say = str(data.get("say") or "").strip() or (
        "Merci, je vous fais rappeler dans la journée."
        if lang.startswith("fr") else "Thanks, we'll call you back today."
    )
    return LeadDecision(
        lang=lang,
        next_action=action,  # type: ignore[arg-type]
        say=_trim_say(say),
        qualified_budget=_optstr(data.get("qualified_budget")),
        qualified_timeline=_optstr(data.get("qualified_timeline")),
        callback_when=_optstr(data.get("callback_when")),
        summary=_optstr(data.get("summary")),
    )


def _fallback_lead_callback(reason: str) -> LeadDecision:
    log.info("Lead outbound fallback (reason=%s)", reason)
    return LeadDecision(
        lang="fr-CA",
        next_action="callback",
        say=(
            "Merci pour votre demande. Je note que vous préférez qu'on vous "
            "rappelle. À très bientôt."
        ),
        summary="Échec IA — humain à rappeler.",
    )


def _optstr(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _trim_say(s: str, max_chars: int = 320) -> str:
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars]
    last = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    return cut[: last + 1] if last >= 80 else cut.rstrip() + "…"


async def decide_lead_outbound_turn(
    *,
    history: List[tuple[str, str]],
    system_prompt: str,
    turn_count: int,
) -> LeadDecision:
    """Demande à Claude la prochaine action de la secrétaire outbound."""
    if turn_count >= MAX_OUTBOUND_TURNS:
        return _fallback_lead_callback("max_turns")
    convo = "\n".join(
        f"- {'Léa' if r == 'assistant' else 'Lead'} : {t}" for r, t in history
    )
    user_prompt = (
        f"Historique :\n{convo}\n\n"
        "Réponds UNIQUEMENT par un objet JSON conforme au schéma."
    )
    try:
        result = await chat(
            messages=[Message(role="user", content=user_prompt)],
            system=system_prompt,
            max_tokens=500,
            temperature=0.4,
        )
        return _parse_lead_decision(result.text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Lead outbound IA failed: %s", exc)
        return _fallback_lead_callback(str(exc))


def _bridge_url(base_url: str, call_id: int) -> str:
    return f"{base_url.rstrip('/')}/api/v1/voice/twilio/lead-outbound?call_id={call_id}"


def _status_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/voice/twilio/status"


async def start_lead_qualification_call(
    *,
    contact_request_id: int,
    delay_sec: int = 60,
    force: bool = False,
) -> Optional[int]:
    """Schedule + initiate l'appel sortant de qualification.

    Sleep `delay_sec` (laisser le temps au lead de finir sa session
    browser et de poser son téléphone), puis appelle Twilio. Doit être
    lancé via `asyncio.create_task()` ou `BackgroundTasks.add_task()`
    pour ne pas bloquer la réponse HTTP du POST /contact.

    Args:
        force: si True, ignore le toggle `lead_auto_callback_enabled`
            (utilisé par le déclencheur manuel admin depuis le CRM).
            Si False (auto-trigger sur création), on vérifie le toggle
            et on skip si désactivé.
    """
    if delay_sec > 0:
        await asyncio.sleep(delay_sec)

    base_url = (
        os.getenv("VOICE_WEBHOOK_BASE_URL") or "https://h2-0.onrender.com"
    )

    async with AsyncSessionLocal() as db:
        cr = (
            await db.execute(
                select(ContactRequest).where(ContactRequest.id == contact_request_id)
            )
        ).scalar_one_or_none()
        if cr is None:
            log.warning("Lead qualification: contact_request %d not found", contact_request_id)
            return None

        # Skip si déjà contacté (ex. humain a déjà rappelé entre-temps).
        if cr.status not in ("new", None):
            log.info(
                "Lead qualification skipped: contact %d already status=%s",
                contact_request_id, cr.status,
            )
            return None

        phone = (cr.phone or "").strip()
        if not phone:
            log.info("Lead qualification skipped: no phone for contact %d", contact_request_id)
            return None
        phone = _normalize_e164(phone)
        if phone is None:
            log.info(
                "Lead qualification skipped: invalid phone %r for contact %d",
                cr.phone, contact_request_id,
            )
            return None

        # Anti-double-appel : si on a déjà tenté un outbound dans les
        # dernières 24h vers ce lead, on n'en relance pas un.
        recent = (
            await db.execute(
                select(Call).where(
                    Call.entity_type == "contact_request",
                    Call.entity_id == contact_request_id,
                    Call.direction == CallDirection.OUTBOUND.value,
                    Call.started_at >= datetime.now(timezone.utc) - timedelta(hours=24),
                )
            )
        ).scalar_one_or_none()
        if recent is not None:
            log.info("Lead qualification skipped: already tried in last 24h (call %d)", recent.id)
            return None

        # 1er PhoneNumber actif comme source.
        pn = (
            await db.execute(
                select(PhoneNumber)
                .where(PhoneNumber.active.is_(True))
                .order_by(PhoneNumber.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if pn is None:
            log.warning("Lead qualification skipped: no active phone number")
            return None

        # Toggle safety : par défaut OFF tant que l'admin n'a pas
        # explicitement activé « Rappel auto des leads » depuis la page
        # /telephonie. Le déclencheur manuel admin passe `force=True`
        # pour outrepasser ce filet.
        if not force and not pn.lead_auto_callback_enabled:
            log.info(
                "Lead qualification skipped: lead_auto_callback_enabled=False "
                "on PhoneNumber %s (contact_request=%d)",
                pn.e164, contact_request_id,
            )
            return None

        # Crée la ligne Call AVANT l'API call (référence dans la TwiML URL).
        call = Call(
            phone_number_id=pn.id,
            provider_sid=f"pending-lead-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
            direction=CallDirection.OUTBOUND.value,
            status=CallStatus.QUEUED.value,
            from_e164=pn.e164,
            to_e164=phone,
            forwarded_to_e164=None,
            entity_type="contact_request",
            entity_id=contact_request_id,
            lang="fr-CA" if (cr.locale or "fr").startswith("fr") else "en-US",
            intent="lead_qualification",
        )
        db.add(call)
        await db.flush()

        sid_acct = os.getenv("TWILIO_ACCOUNT_SID") or ""
        tok = os.getenv("TWILIO_AUTH_TOKEN") or ""
        if not (sid_acct and tok):
            log.warning("Lead qualification: Twilio not configured")
            await db.commit()
            return call.id

        provider = TwilioVoiceProvider(sid_acct, tok)
        try:
            sid = await provider.initiate_outbound_call(
                from_e164=pn.e164,
                to_e164=phone,
                twiml_url=_bridge_url(base_url, call.id),
                status_callback_url=_status_url(base_url),
            )
            if sid:
                call.provider_sid = sid
            await db.commit()
            log.info(
                "Lead qualification call initiated: contact=%d call=%d sid=%s",
                contact_request_id, call.id, sid,
            )
            return call.id
        except Exception as exc:  # noqa: BLE001
            log.exception("Lead qualification initiate failed: %s", exc)
            # Garde la ligne Call avec status='failed' pour audit.
            call.status = CallStatus.FAILED.value
            await db.commit()
            return call.id


def _normalize_e164(s: str) -> Optional[str]:
    """Normalise un numéro vers E.164 NANP. Retourne None si invalide."""
    digits = "".join(c for c in s if c.isdigit() or c == "+")
    if digits.startswith("+"):
        d = digits[1:]
        return digits if d.isdigit() and len(d) >= 8 else None
    plain = "".join(c for c in s if c.isdigit())
    if len(plain) == 10:
        return f"+1{plain}"
    if len(plain) == 11 and plain.startswith("1"):
        return f"+{plain}"
    return None


# ---------------------------------------------------------------------
# System prompt pour la qualification outbound
# ---------------------------------------------------------------------


def build_outbound_system_prompt(
    *,
    lead_name: str,
    project_type: str,
    message: str,
    budget_range: Optional[str] = None,
    address: Optional[str] = None,
    lang: str = "fr-CA",
) -> str:
    """Personnalise le prompt secrétaire avec le contexte du lead."""
    lang_en = lang.startswith("en")
    project_label = _project_label_fr(project_type) if not lang_en else project_type

    ctx_lines = [
        f"NOM : {lead_name}",
        f"TYPE DE PROJET : {project_label}",
    ]
    if budget_range:
        ctx_lines.append(f"BUDGET INDIQUÉ : {budget_range}")
    if address:
        ctx_lines.append(f"ADRESSE : {address}")
    if message:
        ctx_lines.append(f"MESSAGE : {message[:500]}")

    if lang_en:
        return _OUTBOUND_PROMPT_EN.format(ctx="\n".join(ctx_lines))
    return _OUTBOUND_PROMPT_FR.format(ctx="\n".join(ctx_lines))


_OUTBOUND_PROMPT_FR = """\
Tu es Léa, secrétaire d'accueil d'Horizon Services Immobiliers (Montréal). \
Tu rappelles un lead qui vient juste de remplir notre formulaire de \
demande sur immohorizon.com. C'est TOI qui appelles, pas l'inverse.

CONTEXTE DU LEAD :
{ctx}

OBJECTIF DE L'APPEL :

1. Te présenter chaleureusement et faire référence à la demande ("je vous \
appelle parce que vous avez rempli notre formulaire pour…")
2. Confirmer que c'est bien un bon moment pour parler (sinon → callback)
3. Qualifier rapidement (3-4 questions max) :
   - Type de travaux précis (cuisine complète vs juste comptoir, etc.)
   - Échéancier souhaité (mois prévu)
   - Budget approximatif (s'ils n'ont rien indiqué)
4. Proposer un RDV pour estimation : « demain matin », « demain après-midi », \
ou « après-demain ». S'ils refusent les 3, → callback à l'heure de leur \
choix.
5. Conclure chaleureusement.

CONTRAINTES CRITIQUES :

- Tes réponses (`say`) sont **TRÈS COURTES** : 1 phrase, max 2. Tu PARLES \
(Polly Neural), pas tu n'écris.
- UNE seule question par tour.
- Maximum 8 tours — au-delà, force `complete` avec `next_action='callback'`.
- Si la personne dit qu'elle n'est plus intéressée → `next_action='lost'` \
avec un mot poli.
- Si elle a déjà choisi un autre entrepreneur → `next_action='lost'`.
- Format de sortie : **JSON pur uniquement**, pas de markdown.

CHAMPS JSON ATTENDUS :

    {{
      "lang": "fr-CA" | "en-US",
      "qualified_budget": null | "5-15k" | "15-50k" | "50-100k" | "100k+",
      "qualified_timeline": null | "ce mois" | "1-3 mois" | "3-6 mois" | "6m+",
      "next_action": "continue" | "rdv_demain_am" | "rdv_demain_pm" \
| "rdv_apres_demain" | "callback" | "lost" | "complete_no_action",
      "callback_when": null | "ce soir 18h" | "demain 10h" | etc.,
      "say": "Ce que tu dis ensuite à l'appelant.",
      "summary": null (sauf au tour final : résumé 2 phrases de l'appel \
pour la fiche CRM)
    }}
"""


_OUTBOUND_PROMPT_EN = """\
You are Léa, receptionist for Horizon Services Immobiliers (Montreal). \
You are calling a lead who just submitted our request form on \
immohorizon.com. YOU are initiating the call.

LEAD CONTEXT:
{ctx}

CALL OBJECTIVE:

1. Warm intro referencing their request
2. Confirm it's a good time to talk (otherwise → callback)
3. Quick qualification (3-4 questions max): precise scope, timeline, budget
4. Propose an estimation appointment: tomorrow morning, tomorrow afternoon, \
or the day after. If they refuse → callback at their preferred time.
5. Close warmly.

CRITICAL CONSTRAINTS:

- Very short replies (`say`): 1 sentence, 2 max. You SPEAK, you don't write.
- One question per turn.
- Max 8 turns — force `complete` afterward with `next_action='callback'`.
- Output: **pure JSON only**, no markdown.

JSON SCHEMA:

    {{
      "lang": "fr-CA" | "en-US",
      "qualified_budget": null | "5-15k" | "15-50k" | "50-100k" | "100k+",
      "qualified_timeline": null | "this month" | "1-3 months" | "3-6 months" | "6m+",
      "next_action": "continue" | "rdv_demain_am" | "rdv_demain_pm" \
| "rdv_apres_demain" | "callback" | "lost" | "complete_no_action",
      "callback_when": null | "tonight 6pm" | "tomorrow 10am" | etc.,
      "say": "What you tell the lead next.",
      "summary": null (except final turn: 2-sentence summary for CRM)
    }}
"""


_PROJECT_LABELS_FR = {
    "salle_bain": "rénovation de salle de bain",
    "cuisine": "rénovation de cuisine",
    "multilogement": "rénovation de multilogement",
    "renovation_complete": "rénovation complète",
    "autre": "rénovation",
}


def _project_label_fr(t: str) -> str:
    return _PROJECT_LABELS_FR.get(t, "rénovation")
