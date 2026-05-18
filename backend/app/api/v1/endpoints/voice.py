"""Téléphonie — endpoints webhook Twilio + admin minimal.

Phase 1 (transfert direct) + Phase 2 (secrétaire IA Polly Neural) :

    POST /api/v1/voice/twilio/voice       — décrocher un appel entrant
    POST /api/v1/voice/twilio/secretary   — tour de conversation IA
    POST /api/v1/voice/twilio/status      — callback de fin d'appel
    GET  /api/v1/voice/phone-numbers      — liste (admin)
    GET  /api/v1/voice/calls              — journal récent (admin)
    GET  /api/v1/voice/calls/{id}/turns   — transcription d'un appel
    PATCH /api/v1/voice/phone-numbers/{id} — toggle secretary_mode (admin)

Les webhooks `twilio/*` sont publics mais vérifient la signature
HMAC X-Twilio-Signature. Les endpoints admin requièrent `CurrentAdmin`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, CurrentUser, DBSession
from app.integrations.voice import get_voice_provider
from app.integrations.voice.routing import RoutingAction, decide_routing
from app.integrations.voice.caller_identity import (
    CallerKind,
    build_identity_context_block,
    build_personalized_greeting,
    identify_caller,
)
from app.integrations.voice.lead_outbound import (
    build_outbound_system_prompt,
    decide_lead_outbound_turn,
)
from app.integrations.voice.secretary import (
    decide_initial_greeting,
    decide_next_turn,
)
from app.integrations.voice.spam_filter import (
    SpamCheckResult,
    check_incoming,
    maybe_mark_honeypot,
    record_call_cost,
    record_spam_block,
)
from app.integrations.voice.voice_sdk import (
    build_dial_clients_xml,
    generate_access_token,
    list_online_user_ids,
    update_presence,
    voice_sdk_configured,
)
from app.integrations.voice.twilio_provider import TwilioVoiceProvider
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.voice import (
    Call,
    CallDirection,
    CallStatus,
    CallTurn,
    PhoneNumber,
    VoiceBusinessHours,
    VoiceFilter,
    VoiceSms,
    VoiceUsageDaily,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _full_request_url(request: Request) -> str:
    """URL absolue telle que Twilio l'a calculée pour signer.

    Render termine TLS devant l'app, donc `request.url` est en `http://`
    interne. On reconstruit en `https://` via le header `X-Forwarded-Proto`
    quand il est présent, et `X-Forwarded-Host` pour le domaine public.
    """
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        return str(request.url)
    path = request.url.path
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{proto}://{host}{path}{query}"


def _secretary_base_url() -> str:
    return (
        os.getenv("VOICE_WEBHOOK_BASE_URL") or "https://h2-0.onrender.com"
    ).rstrip("/")


def _secretary_action_url() -> str:
    return f"{_secretary_base_url()}/api/v1/voice/twilio/secretary"


def _voicemail_action_url() -> str:
    return f"{_secretary_base_url()}/api/v1/voice/twilio/voicemail"


def _voicemail_transcribe_url() -> str:
    return f"{_secretary_base_url()}/api/v1/voice/twilio/voicemail-transcript"


def _voice_sdk_callback_url() -> str:
    return f"{_secretary_base_url()}/api/v1/voice/twilio/sdk-outbound"


def _outbound_bridge_url(call_id: int) -> str:
    return (
        f"{_secretary_base_url()}"
        f"/api/v1/voice/twilio/outbound-bridge?call_id={int(call_id)}"
    )


SUPPORTED_ENTITY_TYPES = {
    "prospection_lead",
    "contact_request",
    "client",
    "contact",
}


async def _validate_twilio_signature(request: Request) -> dict[str, str]:
    """Lit le body form-encoded, vérifie la signature, retourne les params."""
    try:
        provider = get_voice_provider()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice provider not configured",
        )

    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    sig = request.headers.get("x-twilio-signature", "")
    url = _full_request_url(request)
    if not provider.validate_webhook_signature(url, params, sig):
        log.warning("Twilio signature mismatch on url=%s", url)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Twilio signature",
        )
    return params


def _twilio_provider() -> TwilioVoiceProvider:
    """Cast vers le provider concret (méthodes TwiML spécifiques)."""
    p = get_voice_provider()
    if not isinstance(p, TwilioVoiceProvider):  # pragma: no cover
        raise HTTPException(
            status_code=500, detail="Expected Twilio provider for TwiML"
        )
    return p


async def _record_turn(
    db,
    *,
    call_id: int,
    role: str,
    text: str,
    confidence: Optional[float] = None,
) -> None:
    """Insère un CallTurn (role ∈ {user, assistant}) à la suite du dernier."""
    count = (
        await db.execute(
            select(CallTurn).where(CallTurn.call_id == call_id)
        )
    ).scalars().all()
    next_idx = len(count)
    db.add(
        CallTurn(
            call_id=call_id,
            turn_index=next_idx,
            role=role,
            text=text,
            confidence=int(confidence * 100) if confidence is not None else None,
        )
    )
    await db.flush()


async def _create_lead_from_callback(db, *, call: Call) -> Optional[int]:
    """Crée un ContactRequest depuis les infos capturées par la secrétaire.

    Email synthétisé depuis le numéro car notre table impose un email
    non-NULL ; le staff CRM identifie facilement les leads téléphoniques
    par `source='telephonie'` (filtre de la kanban).
    """
    if call.contact_request_id is not None:
        return call.contact_request_id

    callback_phone = (
        (call.lead_callback_phone or "").strip()
        or call.from_e164
    )
    name = (call.lead_name or "").strip() or f"Appelant {call.from_e164}"
    # Construit un message lisible depuis ce qu'on a.
    bits: list[str] = []
    if call.lead_reason:
        bits.append(call.lead_reason)
    if call.intent and call.intent not in ("unclear", "callback"):
        bits.append(f"Intent détecté : {call.intent}")
    bits.append(f"Numéro entrant : {call.from_e164}")
    message = " — ".join(bits) or "Appel reçu via la secrétaire IA."

    # Email synthétique stable par numéro (réutilisable pour matcher
    # les rappels successifs au même prospect au lieu d'en créer plein).
    sanitized = "".join(c for c in callback_phone if c.isalnum()) or "anon"
    synth_email = f"tel{sanitized}@telephonie.local"

    cr = ContactRequest(
        name=name[:255],
        email=synth_email,
        phone=callback_phone[:50],
        project_type="autre",
        message=message[:5000],
        locale="fr" if call.lang.startswith("fr") else "en",
        source="telephonie",
        gdpr_consent=True,
        marketing_consent=False,
        status=ContactRequestStatus.NEW.value,
    )
    db.add(cr)
    await db.flush()
    call.contact_request_id = cr.id
    await db.flush()
    return cr.id


# ---------------------------------------------------------------------
# Helper : fallback TwiML en cas d'erreur inattendue
# ---------------------------------------------------------------------


def _safe_error_twiml(lang: str = "fr-CA") -> Response:
    """TwiML servi quand un handler webhook lève une exception. Évite
    le « We are sorry, an application error has occurred » par défaut
    de Twilio qui sonne très moche pour l'appelant."""
    if lang.startswith("en"):
        say = (
            "Sorry, we are experiencing a technical issue. "
            "Please try again in a few minutes. Goodbye."
        )
        voice = "Polly.Joanna-Neural"
    else:
        say = (
            "Désolée, nous rencontrons un souci technique. "
            "Réessayez dans quelques minutes ou laissez-nous un message "
            "par texto. Au revoir."
        )
        voice = "Polly.Léa-Neural"
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say voice="{voice}" language="{lang}">{say}</Say>'
        "<Hangup/>"
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------
# Webhook : appel entrant
# ---------------------------------------------------------------------


@router.post(
    "/twilio/voice",
    summary="Webhook Twilio : appel entrant — répond en TwiML",
    response_class=Response,
)
async def twilio_incoming_call(request: Request, db: DBSession) -> Response:
    """Wrapper défensif : toute exception non-HTTPException renvoie un
    TwiML poli en français au lieu du message d'erreur Twilio."""
    try:
        return await _twilio_incoming_call_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_incoming_call failed")
        return _safe_error_twiml()


async def _twilio_incoming_call_impl(request: Request, db: DBSession) -> Response:
    """Décroche un appel entrant.

    Selon `PhoneNumber.secretary_mode_active` :
    - True  → renvoie la phrase d'accueil + un <Gather> qui rebondit
              sur `/twilio/secretary` à chaque tour.
    - False → comportement Phase 1 : <Dial> direct vers forward_to.
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()

    call_sid = params.get("CallSid", "")
    from_e164 = params.get("From", "")
    to_e164 = params.get("To", "")

    if not (call_sid and from_e164 and to_e164):
        raise HTTPException(status_code=400, detail="Missing CallSid / From / To")

    pn = (
        await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.e164 == to_e164, PhoneNumber.active.is_(True)
            )
        )
    ).scalar_one_or_none()

    if pn is None:
        # Self-healing : si le numéro qu'on reçoit correspond à
        # TWILIO_PHONE_NUMBER de l'env, le bootstrap a soit échoué soit
        # n'a pas encore tourné. On crée la ligne à la volée pour que
        # l'appel ne soit pas perdu — ça évite de devoir relancer un
        # bootstrap manuel quand quelque chose foire au démarrage.
        env_number = (os.getenv("TWILIO_PHONE_NUMBER") or "").strip()
        if to_e164 == env_number and env_number:
            log.warning(
                "Self-heal : aucune ligne PhoneNumber pour %s, création à la volée",
                to_e164,
            )
            pn = PhoneNumber(
                e164=to_e164,
                provider="twilio",
                label="Ligne principale (auto-créée)",
                forward_to_e164=(os.getenv("TWILIO_FORWARD_TO") or None),
                active=True,
            )
            db.add(pn)
            await db.flush()
        else:
            log.warning(
                "Incoming call to unknown number %s (CallSid=%s, env=%s)",
                to_e164, call_sid, env_number or "(non set)",
            )
            twiml = provider.build_say_and_hangup(
                say=(
                    "Ce numéro n'est pas configuré dans notre système. "
                    "Au revoir."
                ),
                lang="fr-CA",
            )
            return Response(content=twiml, media_type="application/xml")

    forward_to = (
        (pn.forward_to_e164 or os.getenv("TWILIO_FORWARD_TO") or "").strip()
    )

    # Idempotent : Twilio rejoue parfois le webhook initial.
    existing = (
        await db.execute(select(Call).where(Call.provider_sid == call_sid))
    ).scalar_one_or_none()
    if existing is None:
        existing = Call(
            phone_number_id=pn.id,
            provider_sid=call_sid,
            direction=CallDirection.INBOUND.value,
            status=CallStatus.RINGING.value,
            from_e164=from_e164,
            to_e164=to_e164,
            forwarded_to_e164=forward_to or None,
            lang="fr-CA",
        )
        db.add(existing)
        await db.flush()

    # ----- Identification CRM de l'appelant -----
    # Lookup phone dans client / locataire / lead_prospection / lead_web.
    # On stocke caller_kind + entity_type+entity_id pour la fiche, et
    # on garde l'objet `identified` pour personnaliser le greeting + le
    # system prompt secrétaire ci-dessous.
    identified = await identify_caller(db, from_e164)
    existing.caller_kind = identified.kind.value
    if identified.kind != CallerKind.UNKNOWN and identified.entity_id:
        # Le mapping kind → entity_type table name :
        kind_to_entity = {
            CallerKind.CLIENT: "client",
            CallerKind.LOCATAIRE: "locataire",
            CallerKind.LEAD_PROSPECTION: "prospection_lead",
            CallerKind.LEAD_WEB: "contact_request",
        }
        existing.entity_type = kind_to_entity.get(identified.kind)
        existing.entity_id = identified.entity_id

    # ----- Anti-spam (6 couches) -----
    # Évalué AVANT toute action coûteuse. Si bloqué, on Reject ou on
    # bascule en voicemail-only sans facturer Polly + Claude.
    # Exception : si l'appelant est identifié dans notre CRM
    # (client/locataire/lead), on lui fait confiance et on bypass les
    # filtres anti-spam. Sinon un locataire qui appelle plusieurs fois
    # en urgence se ferait bannir.
    verstat = params.get("StirVerstat") or params.get("VerStat") or None
    if identified.kind != CallerKind.UNKNOWN:
        spam = None  # type: ignore[assignment]
    else:
        spam = await check_incoming(db, from_e164=from_e164, verstat=verstat)
    if spam is not None and spam.result != SpamCheckResult.ALLOW:
        existing.was_blocked = True
        existing.intent = "spam"
        await record_spam_block(db)
        await db.flush()
        log.info(
            "Spam blocked from=%s reason=%s (%s)",
            from_e164, spam.result.value, spam.reason,
        )
        if spam.result == SpamCheckResult.BLOCK_CAP:
            # Cost cap atteint : on garde le canal ouvert mais on
            # bascule sur voicemail (au cas où c'est un vrai client).
            twiml = provider.build_voicemail(
                intro_say=(
                    "Bonjour, vous avez joint Horizon Services Immobiliers. "
                    "Laissez votre message après le bip, nous vous "
                    "rappellerons dès que possible."
                ),
                lang="fr-CA",
                action_url=_voicemail_action_url(),
                transcribe_callback_url=_voicemail_transcribe_url(),
            )
            return Response(content=twiml, media_type="application/xml")
        # Tous les autres motifs : raccrochage poli (Reject = tonalité
        # occupé, le robot ne saura pas qu'on l'a démasqué).
        twiml = provider.build_reject_response("busy")
        return Response(content=twiml, media_type="application/xml")

    # ----- Routage Phase 3 : blocklist / VIP / heures / secrétaire -----
    action = await decide_routing(
        db,
        phone_number_id=pn.id,
        from_e164=from_e164,
        secretary_mode_active=pn.secretary_mode_active,
    )

    if action == RoutingAction.BLOCK:
        existing.was_blocked = True
        existing.intent = "spam"
        await db.flush()
        twiml = provider.build_reject_response("busy")
        return Response(content=twiml, media_type="application/xml")

    if action == RoutingAction.VIP:
        existing.was_vip = True
        await db.flush()
        if not forward_to:
            twiml = provider.build_say_and_hangup(
                say="Bonjour, merci de votre appel. Au revoir.",
                lang="fr-CA",
            )
            return Response(content=twiml, media_type="application/xml")
        # VIP : on sonne sans secrétaire, même si secretary_mode_active.
        twiml = provider.build_forward_response(forward_to_e164=forward_to)
        return Response(content=twiml, media_type="application/xml")

    if action == RoutingAction.VOICEMAIL:
        existing.was_voicemail = True
        await db.flush()
        twiml = provider.build_voicemail(
            intro_say=(
                "Bonjour, vous avez joint Horizon Services Immobiliers. "
                "Nos bureaux sont actuellement fermés. Laissez votre nom, "
                "votre numéro et la raison de votre appel après le bip, "
                "nous vous rappellerons dès que possible."
            ),
            lang="fr-CA",
            action_url=_voicemail_action_url(),
            transcribe_callback_url=_voicemail_transcribe_url(),
        )
        return Response(content=twiml, media_type="application/xml")

    if action == RoutingAction.SECRETARY:
        # Tour 0 : phrase d'accueil + Gather du 1er énoncé client.
        # Si l'appelant est identifié, on personnalise le greeting.
        personalized = (
            build_personalized_greeting(identified)
            if identified.kind != CallerKind.UNKNOWN
            else None
        )
        greeting = await decide_initial_greeting(
            lang="fr-CA", personalized_say=personalized
        )
        existing.lang = greeting.lang
        await _record_turn(
            db, call_id=existing.id, role="assistant", text=greeting.say
        )
        twiml = provider.build_say_and_gather(
            say=greeting.say,
            lang=greeting.lang,
            action_url=_secretary_action_url(),
        )
        return Response(content=twiml, media_type="application/xml")

    # ----- FORWARD (Phase 1) : transfert direct -----
    if not forward_to:
        twiml = provider.build_say_and_hangup(
            say="Bonjour, nous vous rappellerons sous peu. Merci.",
            lang="fr-CA",
        )
        return Response(content=twiml, media_type="application/xml")

    twiml = provider.build_forward_response(forward_to_e164=forward_to)
    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------
# Webhook : tour de conversation avec la secrétaire IA
# ---------------------------------------------------------------------


@router.post(
    "/twilio/secretary",
    summary="Webhook Twilio : tour de la secrétaire IA",
    response_class=Response,
)
async def twilio_secretary_turn(request: Request, db: DBSession) -> Response:
    try:
        return await _twilio_secretary_turn_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_secretary_turn failed")
        return _safe_error_twiml()


async def _twilio_secretary_turn_impl(request: Request, db: DBSession) -> Response:
    """Reçoit la transcription du tour de l'appelant + renvoie le TwiML
    suivant (continue / transfer / callback / end_spam)."""
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()

    call_sid = params.get("CallSid", "")
    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing CallSid")

    call = (
        await db.execute(select(Call).where(Call.provider_sid == call_sid))
    ).scalar_one_or_none()
    if call is None:
        # Cas extrême : Twilio rappelle /secretary sans qu'on ait la ligne.
        # On répond proprement plutôt que 500 (qui ferait rejouer le hook).
        twiml = provider.build_say_and_hangup(
            say="Désolée, une erreur est survenue. Au revoir.",
            lang="fr-CA",
        )
        return Response(content=twiml, media_type="application/xml")

    speech_result = (params.get("SpeechResult") or "").strip()
    confidence_raw = params.get("Confidence")
    confidence = None
    try:
        if confidence_raw:
            confidence = float(confidence_raw)
    except ValueError:
        confidence = None

    if speech_result:
        await _record_turn(
            db,
            call_id=call.id,
            role="user",
            text=speech_result,
            confidence=confidence,
        )

    # Recharge tous les tours pour avoir l'historique complet (l'IA
    # décide en fonction du contexte).
    turns = (
        await db.execute(
            select(CallTurn)
            .where(CallTurn.call_id == call.id)
            .order_by(CallTurn.turn_index)
        )
    ).scalars().all()
    history = [(t.role, t.text) for t in turns]

    # Re-identifie l'appelant pour passer le contexte à Claude (rapide :
    # comparaison SQL sur 10 derniers chiffres, indexée).
    identified = await identify_caller(db, call.from_e164)
    identity_ctx = (
        build_identity_context_block(identified)
        if identified.kind != CallerKind.UNKNOWN
        else None
    )
    decision = await decide_next_turn(
        history=history,
        current_turn_count=len(turns),
        caller_e164=call.from_e164,
        identity_context=identity_ctx,
    )

    # Persist langue + intent à mesure (la dernière décision écrase).
    call.lang = decision.lang
    if decision.intent and decision.intent != "unclear":
        call.intent = decision.intent
    if decision.lead_name:
        call.lead_name = decision.lead_name[:255]
    if decision.lead_callback_phone:
        call.lead_callback_phone = decision.lead_callback_phone[:50]
    if decision.lead_reason:
        call.lead_reason = decision.lead_reason

    await _record_turn(
        db, call_id=call.id, role="assistant", text=decision.say
    )

    # Branche selon l'action décidée.
    if decision.next_action == "transfer":
        # Re-query PhoneNumber explicitement (async SQLAlchemy ne
        # supporte pas le lazy-load `call.phone_number` ici).
        pn = (
            await db.execute(
                select(PhoneNumber).where(PhoneNumber.id == call.phone_number_id)
            )
        ).scalar_one_or_none()
        forward_to = (
            (pn.forward_to_e164 if pn else None)
            or os.getenv("TWILIO_FORWARD_TO")
            or ""
        ).strip()

        # Voice SDK hybride : si des users sont online dans le portail,
        # on les ring d'abord via WebRTC (gratuit). Fallback mobile
        # après 15 sec via /twilio/clients-fallback.
        if voice_sdk_configured():
            online_uids = await list_online_user_ids(db)
            if online_uids:
                call.forwarded_to_e164 = forward_to or None
                clients_xml = build_dial_clients_xml(online_uids)
                fallback_url = (
                    f"{_secretary_base_url()}/api/v1/voice/twilio/"
                    f"clients-fallback?call_id={call.id}"
                )
                twiml = provider.build_say_dial_clients_then_mobile(
                    say=decision.say,
                    lang=decision.lang,
                    clients_xml=clients_xml,
                    fallback_action_url=fallback_url,
                    timeout_sec=15,
                )
                return Response(content=twiml, media_type="application/xml")

        if not forward_to:
            # Pas de cible de transfert ni de client online → callback.
            await _create_lead_from_callback(db, call=call)
            twiml = provider.build_say_and_hangup(
                say=decision.say, lang=decision.lang
            )
            return Response(content=twiml, media_type="application/xml")
        call.forwarded_to_e164 = forward_to
        twiml = provider.build_say_and_dial(
            say=decision.say, lang=decision.lang, dial_to_e164=forward_to
        )
        return Response(content=twiml, media_type="application/xml")

    if decision.next_action == "callback":
        await _create_lead_from_callback(db, call=call)
        twiml = provider.build_say_and_hangup(
            say=decision.say, lang=decision.lang
        )
        return Response(content=twiml, media_type="application/xml")

    if decision.next_action == "end_spam":
        twiml = provider.build_say_and_hangup(
            say=decision.say, lang=decision.lang
        )
        return Response(content=twiml, media_type="application/xml")

    # next_action == 'continue' → on relance un <Gather>.
    twiml = provider.build_say_and_gather(
        say=decision.say,
        lang=decision.lang,
        action_url=_secretary_action_url(),
    )
    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------
# Webhook : statut de fin d'appel
# ---------------------------------------------------------------------


@router.post(
    "/twilio/status",
    summary="Webhook Twilio : mise à jour de statut (fin d'appel)",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def twilio_call_status(request: Request, db: DBSession) -> Response:
    """Met à jour la ligne `Call` à la fin de l'appel."""
    params = await _validate_twilio_signature(request)

    call_sid = params.get("CallSid", "")
    call_status = params.get("CallStatus", "")
    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing CallSid")

    call = (
        await db.execute(select(Call).where(Call.provider_sid == call_sid))
    ).scalar_one_or_none()
    if call is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if call_status:
        call.status = call_status
    duration_raw = params.get("CallDuration") or params.get("Duration")
    if duration_raw and duration_raw.isdigit():
        call.duration_sec = int(duration_raw)
    if call_status in ("completed", "busy", "no-answer", "failed", "canceled"):
        call.ended_at = datetime.now(timezone.utc)
        if call_status == "completed" and call.answered_at is None and call.duration_sec:
            from datetime import timedelta

            call.answered_at = call.ended_at - timedelta(seconds=call.duration_sec)

    rec_url = params.get("RecordingUrl")
    if rec_url:
        call.recording_url = rec_url
        call.recording_sid = params.get("RecordingSid")

    # Anti-spam : compteurs de coût + honeypot.
    if call_status == "completed" and call.duration_sec:
        try:
            await record_call_cost(
                db,
                duration_sec=call.duration_sec,
                direction=call.direction,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("record_call_cost failed: %s", exc)
        if call.direction == "inbound":
            try:
                await maybe_mark_honeypot(
                    db,
                    from_e164=call.from_e164,
                    duration_sec=call.duration_sec,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("honeypot check failed: %s", exc)

    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# Webhook : voicemail (Phase 3)
# ---------------------------------------------------------------------


@router.post(
    "/twilio/voicemail",
    summary="Webhook Twilio : enregistrement de voicemail terminé",
    status_code=status.HTTP_200_OK,
    response_class=Response,
)
async def twilio_voicemail(request: Request, db: DBSession) -> Response:
    try:
        return await _twilio_voicemail_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_voicemail failed")
        return _safe_error_twiml()


async def _twilio_voicemail_impl(request: Request, db: DBSession) -> Response:
    """Twilio appelle ici quand l'enregistrement est terminé.

    On stocke `RecordingUrl` immédiatement (utilisable de suite pour
    écoute). La transcription arrive plus tard via
    `/twilio/voicemail-transcript`. On répond un TwiML de remerciement
    pour finir l'appel proprement.
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()
    call_sid = params.get("CallSid", "")
    if call_sid:
        call = (
            await db.execute(select(Call).where(Call.provider_sid == call_sid))
        ).scalar_one_or_none()
        if call is not None:
            call.was_voicemail = True
            rec_url = params.get("RecordingUrl")
            if rec_url:
                call.recording_url = rec_url
                call.recording_sid = params.get("RecordingSid")
            await db.flush()

    twiml = provider.build_say_and_hangup(
        say="Merci pour votre message. Au revoir.",
        lang="fr-CA",
    )
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/twilio/voicemail-transcript",
    summary="Webhook Twilio : transcription du voicemail prête",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def twilio_voicemail_transcript(request: Request, db: DBSession) -> Response:
    """Twilio POST le texte transcrit. On le persiste, on génère un
    résumé Claude (best-effort), on crée un ContactRequest CRM et on
    notifie l'admin via la cloche."""
    params = await _validate_twilio_signature(request)
    call_sid = params.get("CallSid", "")
    text = (params.get("TranscriptionText") or "").strip()
    rec_url = params.get("RecordingUrl") or ""

    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing CallSid")

    call = (
        await db.execute(select(Call).where(Call.provider_sid == call_sid))
    ).scalar_one_or_none()
    if call is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    call.voicemail_transcription = text or None
    if rec_url:
        call.recording_url = rec_url

    # Résumé IA — best-effort. Si l'IA tombe, on garde juste la transcription.
    summary: Optional[str] = None
    if text:
        try:
            from app.integrations.ai import chat, Message

            res = await chat(
                messages=[
                    Message(
                        role="user",
                        content=(
                            "Résume ce message vocal laissé sur la boîte "
                            "vocale d'Horizon Services Immobiliers en 1-2 "
                            "phrases courtes, en identifiant l'intent "
                            "(rénovation / logiciel / gestion immo / "
                            "spam / autre) et les coordonnées si "
                            "mentionnées :\n\n"
                            f"{text}"
                        ),
                    )
                ],
                system=(
                    "Tu es un assistant qui résume des messages vocaux. "
                    "Réponds en français québécois, en 2 phrases max. "
                    "Pas de markdown, juste du texte plat."
                ),
                max_tokens=200,
                temperature=0.3,
            )
            summary = res.text.strip() or None
        except Exception as exc:  # noqa: BLE001
            log.warning("Voicemail summary failed: %s", exc)
    call.voicemail_summary = summary

    # Crée un ContactRequest pour que le voicemail apparaisse dans le CRM.
    if text:
        # Réutilise l'helper qui synthétise email/nom depuis le téléphone.
        call.lead_name = call.lead_name or f"Voicemail {call.from_e164}"
        call.lead_callback_phone = call.lead_callback_phone or call.from_e164
        call.lead_reason = summary or text[:500]
        call.intent = call.intent or "callback"
        await _create_lead_from_callback(db, call=call)

    # Notif cloche pour l'owner du numéro (s'il existe), sinon tous les owners.
    try:
        from app.models.notification import Notification
        from app.models.user import User

        pn = (
            await db.execute(
                select(PhoneNumber).where(PhoneNumber.id == call.phone_number_id)
            )
        ).scalar_one_or_none()

        user_ids: list[int] = []
        if pn and pn.owner_user_id:
            user_ids = [pn.owner_user_id]
        else:
            # Fallback : tous les owners (la table est petite).
            owners = (
                await db.execute(select(User.id).where(User.role == "owner"))
            ).scalars().all()
            user_ids = list(owners)

        body = summary or (text[:200] + "…" if len(text) > 200 else text)
        for uid in user_ids:
            db.add(
                Notification(
                    user_id=uid,
                    kind="voicemail_received",
                    title=f"Voicemail de {call.from_e164}",
                    body=body or "Message vocal reçu (transcription vide).",
                    href=f"/telephonie?call={call.id}",
                )
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("Voicemail notification failed: %s", exc)

    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# Voice SDK hybride (Phase 4+) — token / presence / dispatch
# ---------------------------------------------------------------------


class VoiceTokenResponse(BaseModel):
    token: str
    identity: str
    ttl_sec: int = 3600


@router.get(
    "/sdk/token",
    response_model=VoiceTokenResponse,
    summary="Twilio Access Token pour le Voice SDK (login user)",
)
async def get_voice_sdk_token(user: CurrentUser) -> VoiceTokenResponse:
    """Le frontend appelle cet endpoint au boot pour s'enregistrer
    comme Twilio Client. Token valide 1h ; le client le re-fetch
    automatiquement à expiration (ou avant en cas de Device error).
    """
    token = generate_access_token(user_id=user.id, ttl_sec=3600)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Voice SDK not configured. Set TWILIO_TWIML_APP_SID, "
                "TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET in env."
            ),
        )
    from app.integrations.voice.voice_sdk import client_identity_for_user

    return VoiceTokenResponse(
        token=token, identity=client_identity_for_user(user.id)
    )


@router.post(
    "/sdk/presence/ping",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Heartbeat de présence (browser ouvert, accepting calls)",
)
async def presence_ping(
    user: CurrentUser,
    db: DBSession,
    accepting: bool = Query(default=True),
) -> Response:
    await update_presence(db, user_id=user.id, accepting=accepting)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/twilio/sdk-outbound",
    summary="TwiML servi à la TwiML App quand un browser fait device.connect()",
    response_class=Response,
)
async def twilio_sdk_outbound(request: Request) -> Response:
    """Twilio appelle ici quand un user du portail clique un bouton
    « Appeler » qui passe par le Voice SDK (vs notre /calls/outbound
    REST). Le frontend passe `To` dans les params de device.connect().

    On valide la signature, on lit `To`, on renvoie un TwiML qui
    appelle ce numéro avec notre numéro 438 comme callerId.
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()
    to = (params.get("To") or "").strip()
    if not to:
        twiml = provider.build_say_and_hangup(
            say="Numéro manquant. Au revoir.", lang="fr-CA"
        )
        return Response(content=twiml, media_type="application/xml")
    # CallerID = notre numéro principal (1er PhoneNumber actif).
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Dial callerId="{os.getenv("TWILIO_PHONE_NUMBER", "")}" '
        'timeout="20">'
        f"{to}"
        "</Dial>"
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/twilio/clients-fallback",
    summary="TwiML de fallback : appelé quand le dispatch <Client> a échoué",
    response_class=Response,
)
async def twilio_clients_fallback(request: Request, db: DBSession) -> Response:
    try:
        return await _twilio_clients_fallback_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_clients_fallback failed")
        return _safe_error_twiml()


async def _twilio_clients_fallback_impl(request: Request, db: DBSession) -> Response:
    """Twilio appelle ici si :
    - aucun Client n'a répondu dans le timeout (15 sec)
    - tous les Clients ont décliné
    - erreur réseau côté browser

    On bascule sur le numéro mobile fallback (forward_to_e164 ou
    TWILIO_FORWARD_TO). Si pas non plus configuré → voicemail.
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()
    call_id_raw = request.query_params.get("call_id", "")
    dial_status = (params.get("DialCallStatus") or "").lower()

    # Si le Dial a réussi (answered/completed), Twilio ne va PAS rejouer
    # le flow — il vient juste nous notifier. On répond vide.
    if dial_status in ("answered", "completed"):
        return Response(content="<Response/>", media_type="application/xml")

    forward_to = ""
    if call_id_raw.isdigit():
        call = (
            await db.execute(select(Call).where(Call.id == int(call_id_raw)))
        ).scalar_one_or_none()
        if call is not None:
            forward_to = (call.forwarded_to_e164 or "").strip()

    if not forward_to:
        forward_to = (os.getenv("TWILIO_FORWARD_TO") or "").strip()

    if not forward_to:
        twiml = provider.build_voicemail(
            intro_say=(
                "Désolée, personne n'est disponible pour l'instant. "
                "Laissez votre message après le bip."
            ),
            lang="fr-CA",
            action_url=_voicemail_action_url(),
            transcribe_callback_url=_voicemail_transcribe_url(),
        )
        return Response(content=twiml, media_type="application/xml")

    twiml = provider.build_forward_response(forward_to_e164=forward_to)
    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------
# Sortant + lien CRM (Phase 4)
# ---------------------------------------------------------------------


class OutboundCallRequest(BaseModel):
    target_e164: str = Field(min_length=4, max_length=20)
    entity_type: Optional[str] = Field(default=None, max_length=32)
    entity_id: Optional[int] = None
    # Si non fourni, on prend le 1er PhoneNumber actif comme caller ID.
    from_phone_number_id: Optional[int] = None


class OutboundCallResponse(BaseModel):
    call_id: int
    provider_sid: str
    bridge_to_e164: str
    target_e164: str


@router.post(
    "/calls/outbound",
    response_model=OutboundCallResponse,
    summary="Initie un appel sortant click-to-call (admin)",
)
async def create_outbound_call(
    payload: OutboundCallRequest, _: CurrentAdmin, db: DBSession
) -> OutboundCallResponse:
    """Click-to-call : Twilio appelle d'abord le mobile interne
    (`TWILIO_FORWARD_TO`), puis bridge vers la cible une fois qu'on a
    décroché. Crée la ligne `Call` AVANT l'API call pour pouvoir
    référencer `call_id` dans l'URL du bridge TwiML.
    """
    target = payload.target_e164.strip()
    if not target.startswith("+"):
        raise HTTPException(status_code=400, detail="target must be E.164 (+...)")
    if payload.entity_type and payload.entity_type not in SUPPORTED_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="unsupported entity_type")

    # PhoneNumber source : explicite ou le 1er actif.
    if payload.from_phone_number_id:
        pn = (
            await db.execute(
                select(PhoneNumber).where(
                    PhoneNumber.id == payload.from_phone_number_id,
                    PhoneNumber.active.is_(True),
                )
            )
        ).scalar_one_or_none()
    else:
        pn = (
            await db.execute(
                select(PhoneNumber)
                .where(PhoneNumber.active.is_(True))
                .order_by(PhoneNumber.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if pn is None:
        raise HTTPException(status_code=400, detail="no_active_phone_number")

    bridge_to = (
        (pn.forward_to_e164 or os.getenv("TWILIO_FORWARD_TO") or "").strip()
    )
    if not bridge_to:
        raise HTTPException(
            status_code=400,
            detail="no_bridge_target (set forward_to_e164 or TWILIO_FORWARD_TO)",
        )

    # On crée la ligne d'abord pour avoir l'ID dispo dans l'URL TwiML.
    call = Call(
        phone_number_id=pn.id,
        # Sera remplacé par le vrai CallSid juste après.
        provider_sid=f"pending-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        direction=CallDirection.OUTBOUND.value,
        status=CallStatus.QUEUED.value,
        from_e164=pn.e164,
        to_e164=target,
        forwarded_to_e164=bridge_to,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        lang="fr-CA",
    )
    db.add(call)
    await db.flush()

    provider = _twilio_provider()
    base_status_url = f"{_secretary_base_url()}/api/v1/voice/twilio/status"
    try:
        sid = await provider.initiate_outbound_call(
            from_e164=pn.e164,
            to_e164=bridge_to,
            twiml_url=_outbound_bridge_url(call.id),
            status_callback_url=base_status_url,
        )
    except Exception as exc:
        # Rollback la ligne pour ne pas garder une row orpheline.
        await db.delete(call)
        await db.flush()
        log.exception("Outbound call initiation failed")
        raise HTTPException(status_code=502, detail=f"twilio_error: {exc}")

    call.provider_sid = sid or call.provider_sid
    await db.flush()

    return OutboundCallResponse(
        call_id=call.id,
        provider_sid=call.provider_sid,
        bridge_to_e164=bridge_to,
        target_e164=target,
    )


@router.post(
    "/twilio/lead-outbound",
    summary="Webhook Twilio : conversation IA outbound (qualification lead)",
    response_class=Response,
)
async def twilio_lead_outbound(request: Request, db: DBSession) -> Response:
    try:
        return await _twilio_lead_outbound_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_lead_outbound failed")
        return _safe_error_twiml()


async def _twilio_lead_outbound_impl(request: Request, db: DBSession) -> Response:
    """Drive la conversation IA sortante de qualification d'un lead.

    Premier appel (sans turns) : greeting personnalisé + Gather du
    premier énoncé du lead. Tours suivants : on alimente Claude avec
    l'historique + le contexte ContactRequest, on persiste la réponse,
    et on dispatch selon `next_action` (rdv_*, callback, lost, etc.).

    À la fin : on met à jour la fiche ContactRequest (status='contacted',
    kanban_column, internal_notes avec le résumé IA).
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()

    call_id_raw = request.query_params.get("call_id", "")
    call_id = int(call_id_raw) if call_id_raw.isdigit() else 0
    if not call_id:
        twiml = provider.build_say_and_hangup(
            say="Désolée, une erreur est survenue. Au revoir.",
            lang="fr-CA",
        )
        return Response(content=twiml, media_type="application/xml")

    call = (
        await db.execute(select(Call).where(Call.id == call_id))
    ).scalar_one_or_none()
    if call is None:
        twiml = provider.build_say_and_hangup(
            say="Désolée, une erreur est survenue. Au revoir.",
            lang="fr-CA",
        )
        return Response(content=twiml, media_type="application/xml")

    # Met à jour le CallSid si on le voit pour la 1re fois.
    sid = params.get("CallSid", "")
    if sid and not call.provider_sid.startswith("CA"):
        call.provider_sid = sid

    cr = None
    if call.entity_type == "contact_request" and call.entity_id:
        cr = (
            await db.execute(
                select(ContactRequest).where(ContactRequest.id == call.entity_id)
            )
        ).scalar_one_or_none()

    speech_result = (params.get("SpeechResult") or "").strip()
    confidence_raw = params.get("Confidence")
    confidence = None
    try:
        if confidence_raw:
            confidence = float(confidence_raw)
    except ValueError:
        pass

    if speech_result:
        await _record_turn(
            db, call_id=call.id, role="user", text=speech_result,
            confidence=confidence,
        )

    turns = (
        await db.execute(
            select(CallTurn)
            .where(CallTurn.call_id == call.id)
            .order_by(CallTurn.turn_index)
        )
    ).scalars().all()

    # Tour 0 — greeting personnalisé.
    if not turns and cr is not None:
        greeting = _build_outbound_greeting(cr)
        call.lang = greeting.lang
        await _record_turn(
            db, call_id=call.id, role="assistant", text=greeting.say
        )
        twiml = provider.build_say_and_gather(
            say=greeting.say,
            lang=greeting.lang,
            action_url=f"{_secretary_base_url()}/api/v1/voice/twilio/lead-outbound?call_id={call.id}",
        )
        return Response(content=twiml, media_type="application/xml")

    # Tours suivants — pilotage Claude.
    if cr is None:
        # Cas dégénéré : pas de contexte → on raccroche poliment.
        twiml = provider.build_say_and_hangup(
            say="Merci pour votre appel. Au revoir.", lang=call.lang or "fr-CA"
        )
        return Response(content=twiml, media_type="application/xml")

    system_prompt = build_outbound_system_prompt(
        lead_name=cr.name,
        project_type=cr.project_type,
        message=cr.message or "",
        budget_range=cr.budget_range,
        address=cr.address,
        lang=call.lang or "fr-CA",
    )
    history = [(t.role, t.text) for t in turns]
    decision = await decide_lead_outbound_turn(
        history=history,
        system_prompt=system_prompt,
        turn_count=len(turns),
    )

    call.lang = decision.lang
    if decision.summary:
        call.lead_reason = decision.summary
    await _record_turn(
        db, call_id=call.id, role="assistant", text=decision.say
    )

    # Dispatch final.
    if decision.next_action == "continue":
        twiml = provider.build_say_and_gather(
            say=decision.say,
            lang=decision.lang,
            action_url=f"{_secretary_base_url()}/api/v1/voice/twilio/lead-outbound?call_id={call.id}",
        )
        return Response(content=twiml, media_type="application/xml")

    # Persistance finale dans la fiche CRM.
    await _commit_lead_outcome(
        db, cr=cr, call=call, decision=decision,
    )

    twiml = provider.build_say_and_hangup(say=decision.say, lang=decision.lang)
    return Response(content=twiml, media_type="application/xml")


def _build_outbound_greeting(cr: ContactRequest) -> "type('G', (), {})":  # type: ignore[valid-type]
    """Greeting statique court qui mentionne le contexte du lead."""
    lang = "en-US" if (cr.locale or "fr").startswith("en") else "fr-CA"
    project_fr = {
        "salle_bain": "salle de bain",
        "cuisine": "cuisine",
        "multilogement": "multilogement",
        "renovation_complete": "rénovation complète",
    }.get(cr.project_type, "rénovation")

    first_name = (cr.name or "").split(" ")[0] if cr.name else ""
    if lang.startswith("en"):
        say = (
            f"Hello{' ' + first_name if first_name else ''}, this is Léa from "
            f"Horizon Services Immobiliers. I'm calling about the {cr.project_type} "
            "request you just submitted on our website. Is now a good time?"
        )
    else:
        say = (
            f"Bonjour{' ' + first_name if first_name else ''}, c'est Léa "
            f"d'Horizon Services Immobiliers. Je vous appelle suite à "
            f"votre demande pour {project_fr} sur notre site. "
            "Vous avez 2 minutes pour qu'on en parle ?"
        )

    # Wrap in a small object compat avec ce que la fonction appelante attend.
    class _G:
        pass
    g = _G()
    g.lang = lang
    g.say = say
    return g  # type: ignore[return-value]


async def _commit_lead_outcome(
    db,
    *,
    cr: ContactRequest,
    call: Call,
    decision,
) -> None:
    """Met à jour ContactRequest selon le résultat de l'appel IA outbound
    + crée un AgendaEvent si RDV demandé."""
    from app.models.contact_request import ContactRequestStatus as _CRS

    cr.status = _CRS.CONTACTED.value
    bits: list[str] = []
    if decision.summary:
        bits.append(decision.summary)
    if decision.qualified_budget:
        bits.append(f"Budget : {decision.qualified_budget}")
    if decision.qualified_timeline:
        bits.append(f"Échéancier : {decision.qualified_timeline}")
    if decision.callback_when:
        bits.append(f"Rappel demandé : {decision.callback_when}")
    summary_text = " — ".join(bits) or "Appel IA effectué."
    cr.internal_notes = (
        (cr.internal_notes or "") + f"\n\n[IA outbound {call.id}] {summary_text}"
    ).strip()

    if decision.next_action == "lost":
        cr.kanban_column = "lost"
        cr.status = _CRS.LOST.value
        return
    if decision.next_action == "callback":
        cr.kanban_column = "rappel"
        return
    if decision.next_action == "complete_no_action":
        cr.kanban_column = "qualified"
        return

    # RDV — crée un AgendaEvent à l'heure choisie.
    if decision.next_action in ("rdv_demain_am", "rdv_demain_pm", "rdv_apres_demain"):
        from datetime import datetime as _dt, time as _time, timedelta as _td
        from zoneinfo import ZoneInfo
        from app.models.agenda_event import AgendaEvent

        tz = ZoneInfo("America/Montreal")
        today = _dt.now(tz).date()
        if decision.next_action == "rdv_demain_am":
            start_date = today + _td(days=1)
            start_time = _time(10, 0)
        elif decision.next_action == "rdv_demain_pm":
            start_date = today + _td(days=1)
            start_time = _time(14, 0)
        else:
            start_date = today + _td(days=2)
            start_time = _time(10, 0)
        start = _dt.combine(start_date, start_time, tz)
        end = start + _td(hours=1)
        ev = AgendaEvent(
            title=f"RDV qualification : {cr.name}",
            description=(
                f"RDV auto-créé par Léa (IA outbound). Budget : "
                f"{decision.qualified_budget or 'n/c'}. Échéancier : "
                f"{decision.qualified_timeline or 'n/c'}."
            ),
            start_at=start,
            end_at=end,
            scope="construction",
            event_type="rdv",
            contact_request_id=cr.id,
        )
        db.add(ev)
        cr.kanban_column = "rdv_pris"
        await db.flush()
        log.info(
            "RDV auto-créé : contact=%d agenda=%d at %s",
            cr.id, ev.id, start.isoformat(),
        )


@router.post(
    "/calls/{contact_request_id}/qualify",
    summary="Lance manuellement la qualification IA outbound d'un lead (admin)",
)
async def trigger_lead_qualification(
    contact_request_id: int, _: CurrentAdmin, db: DBSession
) -> dict:
    """Permet de relancer l'appel IA depuis le CRM (utile si auto a échoué
    ou si on a édité le numéro du lead après coup)."""
    from app.integrations.voice.lead_outbound import start_lead_qualification_call

    # Fire-and-forget, sans délai cette fois (manuel).
    # force=True : le déclencheur manuel admin outrepasse le toggle
    # `lead_auto_callback_enabled` puisque l'admin agit explicitement.
    asyncio.create_task(
        start_lead_qualification_call(
            contact_request_id=contact_request_id, delay_sec=0, force=True,
        )
    )
    return {"queued": True, "contact_request_id": contact_request_id}


@router.post(
    "/twilio/outbound-bridge",
    summary="Webhook Twilio : TwiML du bridge pour un appel sortant",
    response_class=Response,
)
async def twilio_outbound_bridge(request: Request, db: DBSession) -> Response:
    try:
        return await _twilio_outbound_bridge_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_outbound_bridge failed")
        return _safe_error_twiml()


async def _twilio_outbound_bridge_impl(request: Request, db: DBSession) -> Response:
    """TwiML servi quand l'utilisateur interne décroche : <Dial> vers
    la cible CRM. Le query-string contient `call_id` pour nous permettre
    de log la cible exacte (Twilio ne renvoie pas le `To` original).
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()

    call_id_raw = request.query_params.get("call_id", "")
    target = ""
    if call_id_raw and call_id_raw.isdigit():
        call = (
            await db.execute(
                select(Call).where(Call.id == int(call_id_raw))
            )
        ).scalar_one_or_none()
        if call is not None:
            target = call.to_e164
            # Met à jour le provider_sid avec le CallSid réel si on l'a
            # raté à l'init (latence d'API).
            sid = params.get("CallSid", "")
            if sid and not call.provider_sid.startswith("CA"):
                call.provider_sid = sid
                await db.flush()

    if not target:
        twiml = provider.build_say_and_hangup(
            say="Désolée, cible introuvable. Au revoir.", lang="fr-CA"
        )
        return Response(content=twiml, media_type="application/xml")

    twiml = provider.build_forward_response(forward_to_e164=target)
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/calls/{call_id}/suggest-followup",
    summary="Génère une suggestion de suivi via Claude (admin)",
)
async def suggest_followup(
    call_id: int, _: CurrentAdmin, db: DBSession
) -> dict:
    """Demande à Claude une suggestion d'action de suivi post-appel.

    Lit le contexte disponible (intent, transcription voicemail, tours
    secrétaire) et propose 1 action concrète (créer follow-up, planifier
    RDV, envoyer soumission, etc.). Persiste dans Call.followup_suggestion
    pour pouvoir le ré-afficher sans refacturer l'IA.
    """
    call = (
        await db.execute(select(Call).where(Call.id == call_id))
    ).scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=404, detail="call_not_found")

    # Construit un contexte compact.
    parts: list[str] = [
        f"Direction : {call.direction}",
        f"De : {call.from_e164} → vers : {call.to_e164}",
    ]
    if call.intent:
        parts.append(f"Intent détecté : {call.intent}")
    if call.duration_sec:
        parts.append(f"Durée : {call.duration_sec}s")
    if call.lead_name:
        parts.append(f"Nom appelant : {call.lead_name}")
    if call.lead_reason:
        parts.append(f"Raison : {call.lead_reason}")
    if call.voicemail_transcription:
        parts.append(f"Voicemail : {call.voicemail_transcription}")
    if call.voicemail_summary:
        parts.append(f"Résumé voicemail : {call.voicemail_summary}")

    # Tours secrétaire (si y en a).
    turns = (
        await db.execute(
            select(CallTurn)
            .where(CallTurn.call_id == call.id)
            .order_by(CallTurn.turn_index)
        )
    ).scalars().all()
    if turns:
        parts.append("Échange secrétaire IA :")
        for t in turns:
            tag = "Secrétaire" if t.role == "assistant" else "Appelant"
            parts.append(f"- {tag} : {t.text}")

    context = "\n".join(parts) or "Aucune information disponible."

    try:
        from app.integrations.ai import chat, Message

        res = await chat(
            messages=[
                Message(
                    role="user",
                    content=(
                        "Contexte d'un appel téléphonique chez Horizon "
                        "Services Immobiliers :\n\n"
                        f"{context}\n\n"
                        "Propose UNE action de suivi concrète (max 2 "
                        "phrases) : rappel, envoi de soumission, "
                        "planification de RDV, ajout au CRM, etc. "
                        "Si aucun suivi n'est nécessaire (spam, "
                        "démarchage…), dis-le simplement."
                    ),
                )
            ],
            system=(
                "Tu aides un entrepreneur québécois à décider quoi faire "
                "après un appel. Réponds en français, 2 phrases max, pas "
                "de markdown. Sois actionnable et direct."
            ),
            max_tokens=200,
            temperature=0.4,
        )
        suggestion = (res.text or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("Suggest followup IA failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"ai_error: {exc}")

    call.followup_suggestion = suggestion
    await db.flush()
    return {"call_id": call.id, "suggestion": suggestion}


# ---------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------


class PhoneNumberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    e164: str
    provider: str
    label: Optional[str]
    forward_to_e164: Optional[str]
    secretary_mode_active: bool
    lead_auto_callback_enabled: bool = False
    owner_user_id: Optional[int]
    active: bool


class PhoneNumberPatch(BaseModel):
    label: Optional[str] = Field(default=None, max_length=128)
    forward_to_e164: Optional[str] = Field(default=None, max_length=20)
    secretary_mode_active: Optional[bool] = None
    lead_auto_callback_enabled: Optional[bool] = None
    active: Optional[bool] = None


class CallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone_number_id: int
    direction: str
    status: str
    from_e164: str
    to_e164: str
    forwarded_to_e164: Optional[str]
    started_at: datetime
    answered_at: Optional[datetime]
    ended_at: Optional[datetime]
    duration_sec: Optional[int]
    lang: str
    intent: Optional[str]
    lead_name: Optional[str]
    lead_callback_phone: Optional[str]
    lead_reason: Optional[str]
    contact_request_id: Optional[int]
    was_blocked: bool = False
    was_vip: bool = False
    was_voicemail: bool = False
    voicemail_transcription: Optional[str] = None
    voicemail_summary: Optional[str] = None
    recording_url: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    followup_suggestion: Optional[str] = None
    caller_kind: Optional[str] = None


class CallTurnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    turn_index: int
    role: str
    text: str
    confidence: Optional[int]
    created_at: datetime


@router.get(
    "/phone-numbers",
    response_model=List[PhoneNumberRead],
    summary="Liste des numéros possédés (admin)",
)
async def list_phone_numbers(_: CurrentAdmin, db: DBSession) -> List[PhoneNumberRead]:
    rows = (
        await db.execute(select(PhoneNumber).order_by(PhoneNumber.id))
    ).scalars().all()
    return [PhoneNumberRead.model_validate(r) for r in rows]


@router.patch(
    "/phone-numbers/{number_id}",
    response_model=PhoneNumberRead,
    summary="Modifie un numéro (toggle secretary_mode, forward_to, label, active)",
)
async def patch_phone_number(
    number_id: int,
    payload: PhoneNumberPatch,
    _: CurrentAdmin,
    db: DBSession,
) -> PhoneNumberRead:
    pn = (
        await db.execute(select(PhoneNumber).where(PhoneNumber.id == number_id))
    ).scalar_one_or_none()
    if pn is None:
        raise HTTPException(status_code=404, detail="phone_number_not_found")
    if payload.label is not None:
        pn.label = payload.label or None
    if payload.forward_to_e164 is not None:
        pn.forward_to_e164 = payload.forward_to_e164.strip() or None
    if payload.secretary_mode_active is not None:
        pn.secretary_mode_active = payload.secretary_mode_active
    if payload.lead_auto_callback_enabled is not None:
        pn.lead_auto_callback_enabled = payload.lead_auto_callback_enabled
    if payload.active is not None:
        pn.active = payload.active
    await db.flush()
    return PhoneNumberRead.model_validate(pn)


@router.get(
    "/calls",
    response_model=List[CallRead],
    summary="Journal d'appels récent (admin) — optionnel : filtre par entité",
)
async def list_calls(
    _: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[int] = Query(default=None),
) -> List[CallRead]:
    stmt = select(Call)
    if entity_type:
        stmt = stmt.where(Call.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(Call.entity_id == entity_id)
    stmt = stmt.order_by(Call.started_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [CallRead.model_validate(r) for r in rows]


@router.get(
    "/calls/{call_id}/turns",
    response_model=List[CallTurnRead],
    summary="Transcription tour-par-tour d'un appel (admin)",
)
async def get_call_turns(
    call_id: int, _: CurrentAdmin, db: DBSession
) -> List[CallTurnRead]:
    rows = (
        await db.execute(
            select(CallTurn)
            .where(CallTurn.call_id == call_id)
            .order_by(CallTurn.turn_index)
        )
    ).scalars().all()
    return [CallTurnRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------
# SMS (Phase 6) — bidirectionnel via le même numéro 438
# ---------------------------------------------------------------------


@router.post(
    "/twilio/sms",
    summary="Webhook Twilio : SMS entrant",
    response_class=Response,
)
async def twilio_incoming_sms(request: Request, db: DBSession) -> Response:
    """Twilio POST ici à chaque SMS entrant. On stocke + on identifie
    l'expéditeur via le CRM. Notif cloche aux owners.

    Réponse : `<Response/>` vide (pas de réponse SMS auto pour l'instant —
    un futur SMS bot IA pourrait répondre ici).
    """
    try:
        return await _twilio_incoming_sms_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_incoming_sms failed")
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
            media_type="application/xml",
        )


async def _twilio_incoming_sms_impl(request: Request, db: DBSession) -> Response:
    params = await _validate_twilio_signature(request)

    message_sid = params.get("MessageSid", "")
    from_e164 = params.get("From", "")
    to_e164 = params.get("To", "")
    body = params.get("Body", "")
    num_media = int(params.get("NumMedia", "0") or 0)

    if not (message_sid and from_e164 and to_e164):
        raise HTTPException(status_code=400, detail="Missing MessageSid / From / To")

    pn = (
        await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.e164 == to_e164, PhoneNumber.active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if pn is None:
        log.warning("Inbound SMS to unknown number %s", to_e164)
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
            media_type="application/xml",
        )

    # Idempotent : Twilio peut rejouer.
    existing = (
        await db.execute(
            select(VoiceSms).where(VoiceSms.provider_sid == message_sid)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
            media_type="application/xml",
        )

    # Récupère les media URLs si MMS.
    import json as _json

    media_urls: list[str] = []
    for i in range(num_media):
        url = params.get(f"MediaUrl{i}")
        if url:
            media_urls.append(url)

    # Identification CRM (même logique que les appels).
    identified = await identify_caller(db, from_e164)
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    if identified.kind != CallerKind.UNKNOWN and identified.entity_id:
        from app.integrations.voice.caller_identity import CallerKind as _CK

        kind_to_entity = {
            _CK.CLIENT: "client",
            _CK.LOCATAIRE: "locataire",
            _CK.LEAD_PROSPECTION: "prospection_lead",
            _CK.LEAD_WEB: "contact_request",
        }
        entity_type = kind_to_entity.get(identified.kind)
        entity_id = identified.entity_id

    sms = VoiceSms(
        phone_number_id=pn.id,
        provider_sid=message_sid,
        direction="inbound",
        status="received",
        from_e164=from_e164,
        to_e164=to_e164,
        body=body or None,
        media_urls=_json.dumps(media_urls) if media_urls else None,
        num_media=num_media,
        caller_kind=identified.kind.value,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(sms)
    await db.flush()

    # Notif cloche aux owners (ou à l'owner du numéro si défini).
    try:
        from app.models.notification import Notification
        from app.models.user import User

        if pn.owner_user_id:
            user_ids = [pn.owner_user_id]
        else:
            user_ids = list(
                (
                    await db.execute(
                        select(User.id).where(User.role == "owner")
                    )
                ).scalars().all()
            )
        preview = (body or "")[:140]
        for uid in user_ids:
            db.add(
                Notification(
                    user_id=uid,
                    kind="sms_received",
                    title=f"SMS de {identified.name or from_e164}",
                    body=preview or "(MMS sans texte)",
                    href=f"/telephonie?sms={sms.id}",
                )
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("SMS notification failed: %s", exc)

    await db.flush()
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
        media_type="application/xml",
    )


# ---------- SMS admin (envoi + liste threadée) ----------


class SmsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone_number_id: int
    provider_sid: str
    direction: str
    status: str
    from_e164: str
    to_e164: str
    body: Optional[str]
    media_urls: Optional[str]
    num_media: int
    received_at: datetime
    sent_at: Optional[datetime]
    caller_kind: Optional[str]
    entity_type: Optional[str]
    entity_id: Optional[int]
    sent_by_user_id: Optional[int]
    read_at: Optional[datetime]


class SmsSend(BaseModel):
    to_e164: str = Field(min_length=4, max_length=20)
    body: str = Field(min_length=1, max_length=1600)
    from_phone_number_id: Optional[int] = None


@router.get(
    "/sms",
    response_model=List[SmsRead],
    summary="Liste les SMS (admin, optionnel filtre par contact)",
)
async def list_sms(
    _: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=100, ge=1, le=500),
    peer_e164: Optional[str] = Query(default=None, description="Filtre par numéro pair (entrant ou sortant)"),
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[int] = Query(default=None),
) -> List[SmsRead]:
    from sqlalchemy import or_

    stmt = select(VoiceSms)
    if peer_e164:
        stmt = stmt.where(
            or_(VoiceSms.from_e164 == peer_e164, VoiceSms.to_e164 == peer_e164)
        )
    if entity_type:
        stmt = stmt.where(VoiceSms.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(VoiceSms.entity_id == entity_id)
    stmt = stmt.order_by(VoiceSms.received_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [SmsRead.model_validate(r) for r in rows]


@router.get(
    "/sms/threads",
    summary="Threads SMS : groupe par numéro pair avec last message + unread count",
)
async def list_sms_threads(
    _: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> List[dict]:
    """Pour la vue Messages (inbox). Renvoie une ligne par contact
    pair (numéro extérieur à Horizon), avec son dernier SMS, le nombre
    de non-lus et l'identification CRM si reconnue.
    """
    rows = (
        await db.execute(
            select(VoiceSms).order_by(VoiceSms.received_at.desc()).limit(limit * 4)
        )
    ).scalars().all()
    # Group by peer (extérieur).
    threads: dict[str, dict] = {}
    for r in rows:
        peer = r.from_e164 if r.direction == "inbound" else r.to_e164
        if peer in threads:
            t = threads[peer]
            if r.direction == "inbound" and r.read_at is None:
                t["unread"] += 1
            continue
        threads[peer] = {
            "peer_e164": peer,
            "last_message": {
                "id": r.id,
                "direction": r.direction,
                "body": r.body,
                "received_at": r.received_at.isoformat(),
                "num_media": r.num_media,
            },
            "caller_kind": r.caller_kind,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "unread": (1 if (r.direction == "inbound" and r.read_at is None) else 0),
        }
        if len(threads) >= limit:
            break
    return list(threads.values())


@router.post(
    "/sms",
    response_model=SmsRead,
    status_code=status.HTTP_201_CREATED,
    summary="Envoie un SMS via notre numéro (admin)",
)
async def send_sms(
    payload: SmsSend, user: CurrentUser, db: DBSession
) -> SmsRead:
    target = payload.to_e164.strip()
    if not target.startswith("+"):
        raise HTTPException(status_code=400, detail="to_e164 must be E.164 (+...)")

    if payload.from_phone_number_id:
        pn = (
            await db.execute(
                select(PhoneNumber).where(
                    PhoneNumber.id == payload.from_phone_number_id,
                    PhoneNumber.active.is_(True),
                )
            )
        ).scalar_one_or_none()
    else:
        pn = (
            await db.execute(
                select(PhoneNumber)
                .where(PhoneNumber.active.is_(True))
                .order_by(PhoneNumber.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if pn is None:
        raise HTTPException(status_code=400, detail="no_active_phone_number")

    provider = _twilio_provider()
    try:
        data = await provider.send_sms(
            from_e164=pn.e164, to_e164=target, body=payload.body
        )
    except Exception as exc:
        log.exception("Twilio SMS send failed")
        raise HTTPException(status_code=502, detail=f"twilio_error: {exc}")

    msg_sid = str(data.get("sid") or "")
    if not msg_sid:
        raise HTTPException(status_code=502, detail="twilio_no_sid")

    # Identification CRM (au cas où le destinataire est connu).
    identified = await identify_caller(db, target)
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    if identified.kind != CallerKind.UNKNOWN and identified.entity_id:
        from app.integrations.voice.caller_identity import CallerKind as _CK

        kind_to_entity = {
            _CK.CLIENT: "client",
            _CK.LOCATAIRE: "locataire",
            _CK.LEAD_PROSPECTION: "prospection_lead",
            _CK.LEAD_WEB: "contact_request",
        }
        entity_type = kind_to_entity.get(identified.kind)
        entity_id = identified.entity_id

    sms = VoiceSms(
        phone_number_id=pn.id,
        provider_sid=msg_sid,
        direction="outbound",
        status=str(data.get("status") or "queued"),
        from_e164=pn.e164,
        to_e164=target,
        body=payload.body,
        sent_at=datetime.now(timezone.utc),
        caller_kind=identified.kind.value,
        entity_type=entity_type,
        entity_id=entity_id,
        sent_by_user_id=user.id,
    )
    db.add(sms)
    await db.flush()
    return SmsRead.model_validate(sms)


@router.post(
    "/sms/{sms_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Marque un SMS entrant comme lu",
)
async def mark_sms_read(
    sms_id: int, _: CurrentUser, db: DBSession
) -> Response:
    sms = (
        await db.execute(select(VoiceSms).where(VoiceSms.id == sms_id))
    ).scalar_one_or_none()
    if sms is None:
        raise HTTPException(status_code=404, detail="sms_not_found")
    if sms.read_at is None:
        sms.read_at = datetime.now(timezone.utc)
        await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Diagnostic infra téléphonie (admin) ------------


@router.post(
    "/diag/bootstrap",
    summary="Relance manuellement le bootstrap Twilio (admin)",
)
async def trigger_bootstrap(_: CurrentAdmin) -> dict:
    """Relance bootstrap_twilio() avec force=True pour reconfigurer
    le webhook URL chez Twilio + créer/refresh la ligne PhoneNumber
    en DB. Utile quand le bootstrap auto a échoué au démarrage."""
    from app.scripts.twilio_bootstrap import bootstrap_twilio

    try:
        rc = await bootstrap_twilio(force=True)
        return {"ok": rc == 0, "return_code": rc}
    except Exception as exc:  # noqa: BLE001
        log.exception("Manual bootstrap failed")
        return {"ok": False, "error": str(exc)}


@router.get(
    "/diag",
    summary="État du système téléphonie pour troubleshooting (admin)",
)
async def voice_diag(_: CurrentAdmin, db: DBSession) -> dict:
    """Reporte tout ce qui peut faire planter le webhook entrant :
    env vars, tables DB, provider IA, état Twilio. Sert quand l'appelant
    tombe sur le TwiML d'erreur poli (`_safe_error_twiml`).
    """
    from sqlalchemy import text as _text

    out: dict = {}

    # 1) Env vars (présence seulement, pas de valeur pour les secrets)
    out["env"] = {
        "TWILIO_ACCOUNT_SID": bool(os.getenv("TWILIO_ACCOUNT_SID")),
        "TWILIO_AUTH_TOKEN": bool(os.getenv("TWILIO_AUTH_TOKEN")),
        "TWILIO_PHONE_NUMBER": os.getenv("TWILIO_PHONE_NUMBER") or None,
        "TWILIO_FORWARD_TO": os.getenv("TWILIO_FORWARD_TO") or None,
        "VOICE_WEBHOOK_BASE_URL": os.getenv("VOICE_WEBHOOK_BASE_URL")
        or "https://h2-0.onrender.com",
        "TWILIO_TWIML_APP_SID": bool(os.getenv("TWILIO_TWIML_APP_SID")),
        "TWILIO_API_KEY_SID": bool(os.getenv("TWILIO_API_KEY_SID")),
        "TWILIO_API_KEY_SECRET": bool(os.getenv("TWILIO_API_KEY_SECRET")),
        "voice_sdk_configured": voice_sdk_configured(),
        "GEMINI_API_KEY": bool(os.getenv("GEMINI_API_KEY")),
        "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY")),
        "GROQ_API_KEY": bool(os.getenv("GROQ_API_KEY")),
    }

    # 2) Provider IA actif (chat) — on essaie de l'initialiser sans
    #    déclencher d'appel API.
    try:
        from app.integrations.ai import current_provider, is_configured

        out["ai"] = {
            "configured": is_configured(),
            "provider": current_provider(),
        }
    except Exception as exc:  # noqa: BLE001
        out["ai"] = {"error": str(exc)}

    # 3) Tables téléphonie présentes ?
    required_tables = [
        "voice_phone_numbers",
        "voice_calls",
        "voice_call_routes",
        "voice_call_transcripts",
        "voice_call_turns",
        "voice_filters",
        "voice_business_hours",
        "voice_caller_intel",
        "voice_usage_daily",
        "voice_client_presence",
        "voice_sms",
    ]
    tables_status: dict[str, str] = {}
    for tbl in required_tables:
        try:
            res = await db.execute(
                _text(f"SELECT to_regclass('public.{tbl}')")
            )
            present = res.scalar() is not None
            tables_status[tbl] = "ok" if present else "MISSING"
        except Exception as exc:  # noqa: BLE001
            tables_status[tbl] = f"error: {exc}"
    out["tables"] = tables_status

    # 4) Colonnes critiques ajoutées via ALTER (les plus récentes)
    columns_to_check = [
        ("voice_phone_numbers", "secretary_mode_active"),
        ("voice_phone_numbers", "lead_auto_callback_enabled"),
        ("voice_calls", "lang"),
        ("voice_calls", "intent"),
        ("voice_calls", "caller_kind"),
        ("voice_calls", "entity_type"),
        ("voice_calls", "entity_id"),
        ("voice_calls", "was_blocked"),
        ("voice_calls", "was_voicemail"),
        ("voice_calls", "voicemail_transcription"),
        ("voice_calls", "followup_suggestion"),
    ]
    cols_status: dict[str, str] = {}
    for tbl, col in columns_to_check:
        key = f"{tbl}.{col}"
        try:
            res = await db.execute(
                _text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ),
                {"t": tbl, "c": col},
            )
            cols_status[key] = "ok" if res.scalar() else "MISSING"
        except Exception as exc:  # noqa: BLE001
            cols_status[key] = f"error: {exc}"
    out["columns"] = cols_status

    # 5) PhoneNumber configuré ?
    try:
        rows = (
            await db.execute(select(PhoneNumber).order_by(PhoneNumber.id))
        ).scalars().all()
        out["phone_numbers"] = [
            {
                "id": r.id,
                "e164": r.e164,
                "provider_sid": r.provider_sid,
                "active": r.active,
                "secretary_mode_active": r.secretary_mode_active,
                "lead_auto_callback_enabled": getattr(
                    r, "lead_auto_callback_enabled", None
                ),
                "forward_to_e164": r.forward_to_e164,
            }
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        out["phone_numbers"] = {"error": str(exc)}

    # 6) Compteur usage du jour
    try:
        from datetime import date as _date

        today = _date.today().isoformat()
        usage = (
            await db.execute(
                select(VoiceUsageDaily).where(
                    VoiceUsageDaily.usage_date == today
                )
            )
        ).scalar_one_or_none()
        out["usage_today"] = (
            {
                "cents": usage.cents_spent,
                "calls": usage.calls_count,
                "spam_blocked": usage.spam_blocked,
            }
            if usage
            else {"cents": 0, "calls": 0, "spam_blocked": 0}
        )
    except Exception as exc:  # noqa: BLE001
        out["usage_today"] = {"error": str(exc)}

    return out


# ---------- Anti-spam : stats + intel (admin) ------------


class UsageDayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    usage_date: str
    cents_spent: int
    calls_count: int
    spam_blocked: int


class CallerIntelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_e164: str
    line_type: Optional[str]
    caller_name: Optional[str]
    spam_hangup_count: int
    banned_until: Optional[datetime]
    last_verstat: Optional[str]
    notes: Optional[str]


@router.get(
    "/usage/today",
    response_model=UsageDayRead,
    summary="Usage Twilio du jour (cents dépensés, appels, spam bloqué)",
)
async def get_usage_today(_: CurrentAdmin, db: DBSession) -> UsageDayRead:
    from datetime import date as _date

    today = _date.today().isoformat()
    row = (
        await db.execute(
            select(VoiceUsageDaily).where(VoiceUsageDaily.usage_date == today)
        )
    ).scalar_one_or_none()
    if row is None:
        return UsageDayRead(
            usage_date=today, cents_spent=0, calls_count=0, spam_blocked=0
        )
    return UsageDayRead.model_validate(row)


from app.models.voice import VoiceCallerIntel as _VCI  # for the next endpoint


@router.get(
    "/caller-intel",
    response_model=List[CallerIntelRead],
    summary="Renseignements anti-spam par numéro (admin)",
)
async def list_caller_intel(
    _: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
    banned_only: bool = Query(default=False),
) -> List[CallerIntelRead]:
    stmt = select(_VCI)
    if banned_only:
        from datetime import datetime as _dt, timezone as _tz

        stmt = stmt.where(_VCI.banned_until > _dt.now(_tz.utc))
    stmt = stmt.order_by(_VCI.updated_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [CallerIntelRead.model_validate(r) for r in rows]


# ---------- Filtres (blocklist + whitelist VIP) Phase 3 ------------


class FilterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone_number_id: int
    kind: str
    pattern: Optional[str]
    label: Optional[str]
    active: bool


class FilterCreate(BaseModel):
    phone_number_id: int
    kind: str = Field(pattern="^(block|vip)$")
    pattern: Optional[str] = Field(default=None, max_length=32)
    label: Optional[str] = Field(default=None, max_length=255)


@router.get(
    "/filters",
    response_model=List[FilterRead],
    summary="Liste des filtres blocklist + VIP (admin)",
)
async def list_filters(
    _: CurrentAdmin,
    db: DBSession,
    phone_number_id: Optional[int] = Query(default=None),
) -> List[FilterRead]:
    stmt = select(VoiceFilter)
    if phone_number_id is not None:
        stmt = stmt.where(VoiceFilter.phone_number_id == phone_number_id)
    stmt = stmt.order_by(VoiceFilter.kind, VoiceFilter.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [FilterRead.model_validate(r) for r in rows]


@router.post(
    "/filters",
    response_model=FilterRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crée un filtre (block ou vip)",
)
async def create_filter(
    payload: FilterCreate, _: CurrentAdmin, db: DBSession
) -> FilterRead:
    # Sanity : pn existe
    pn = (
        await db.execute(
            select(PhoneNumber).where(PhoneNumber.id == payload.phone_number_id)
        )
    ).scalar_one_or_none()
    if pn is None:
        raise HTTPException(status_code=404, detail="phone_number_not_found")
    f = VoiceFilter(
        phone_number_id=payload.phone_number_id,
        kind=payload.kind,
        pattern=(payload.pattern or None),
        label=payload.label,
        active=True,
    )
    db.add(f)
    await db.flush()
    return FilterRead.model_validate(f)


@router.delete(
    "/filters/{filter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprime un filtre",
)
async def delete_filter(
    filter_id: int, _: CurrentAdmin, db: DBSession
) -> Response:
    f = (
        await db.execute(select(VoiceFilter).where(VoiceFilter.id == filter_id))
    ).scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="filter_not_found")
    await db.delete(f)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Heures d'ouverture Phase 3 ------------


class BusinessHoursRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone_number_id: int
    day_of_week: int
    open_time: str
    close_time: str
    timezone: str


class BusinessHoursReplace(BaseModel):
    """Remplace TOUTES les plages d'un numéro par celles fournies.

    Pour effacer toutes les règles (= ouvert 24/7), envoyer `hours=[]`.
    """

    phone_number_id: int
    hours: List["BusinessHoursItem"]


class BusinessHoursItem(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    # Format "HH:MM" 24h.
    open_time: str
    close_time: str
    timezone: str = "America/Montreal"


BusinessHoursReplace.model_rebuild()


@router.get(
    "/business-hours",
    response_model=List[BusinessHoursRead],
    summary="Liste des plages horaires (admin, par numéro)",
)
async def list_business_hours(
    _: CurrentAdmin,
    db: DBSession,
    phone_number_id: int = Query(...),
) -> List[BusinessHoursRead]:
    rows = (
        await db.execute(
            select(VoiceBusinessHours)
            .where(VoiceBusinessHours.phone_number_id == phone_number_id)
            .order_by(VoiceBusinessHours.day_of_week, VoiceBusinessHours.open_time)
        )
    ).scalars().all()
    return [
        BusinessHoursRead(
            id=r.id,
            phone_number_id=r.phone_number_id,
            day_of_week=r.day_of_week,
            open_time=r.open_time.strftime("%H:%M"),
            close_time=r.close_time.strftime("%H:%M"),
            timezone=r.timezone,
        )
        for r in rows
    ]


@router.put(
    "/business-hours",
    response_model=List[BusinessHoursRead],
    summary="Remplace toutes les plages horaires du numéro (atomique)",
)
async def replace_business_hours(
    payload: BusinessHoursReplace, _: CurrentAdmin, db: DBSession
) -> List[BusinessHoursRead]:
    pn = (
        await db.execute(
            select(PhoneNumber).where(PhoneNumber.id == payload.phone_number_id)
        )
    ).scalar_one_or_none()
    if pn is None:
        raise HTTPException(status_code=404, detail="phone_number_not_found")

    # Wipe & replace.
    existing = (
        await db.execute(
            select(VoiceBusinessHours).where(
                VoiceBusinessHours.phone_number_id == payload.phone_number_id
            )
        )
    ).scalars().all()
    for row in existing:
        await db.delete(row)

    from datetime import time as _time

    def _parse_hm(s: str) -> _time:
        h, m = s.split(":")
        return _time(int(h), int(m))

    new_rows: List[VoiceBusinessHours] = []
    for item in payload.hours:
        r = VoiceBusinessHours(
            phone_number_id=payload.phone_number_id,
            day_of_week=item.day_of_week,
            open_time=_parse_hm(item.open_time),
            close_time=_parse_hm(item.close_time),
            timezone=item.timezone,
        )
        db.add(r)
        new_rows.append(r)
    await db.flush()
    return [
        BusinessHoursRead(
            id=r.id,
            phone_number_id=r.phone_number_id,
            day_of_week=r.day_of_week,
            open_time=r.open_time.strftime("%H:%M"),
            close_time=r.close_time.strftime("%H:%M"),
            timezone=r.timezone,
        )
        for r in new_rows
    ]
