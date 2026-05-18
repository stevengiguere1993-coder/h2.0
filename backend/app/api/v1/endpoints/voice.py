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

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, DBSession
from app.integrations.voice import get_voice_provider
from app.integrations.voice.routing import RoutingAction, decide_routing
from app.integrations.voice.secretary import (
    decide_initial_greeting,
    decide_next_turn,
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
# Webhook : appel entrant
# ---------------------------------------------------------------------


@router.post(
    "/twilio/voice",
    summary="Webhook Twilio : appel entrant — répond en TwiML",
    response_class=Response,
)
async def twilio_incoming_call(request: Request, db: DBSession) -> Response:
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
        log.warning("Incoming call to unknown number %s (CallSid=%s)", to_e164, call_sid)
        twiml = provider.build_say_and_hangup(
            say="Ce numéro n'est pas configuré. Au revoir.",
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
        greeting = await decide_initial_greeting(lang="fr-CA")
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

    decision = await decide_next_turn(
        history=history,
        current_turn_count=len(turns),
        caller_e164=call.from_e164,
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
        if not forward_to:
            # Pas de cible de transfert → on bascule en callback.
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
    "/twilio/outbound-bridge",
    summary="Webhook Twilio : TwiML du bridge pour un appel sortant",
    response_class=Response,
)
async def twilio_outbound_bridge(request: Request, db: DBSession) -> Response:
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
    owner_user_id: Optional[int]
    active: bool


class PhoneNumberPatch(BaseModel):
    label: Optional[str] = Field(default=None, max_length=128)
    forward_to_e164: Optional[str] = Field(default=None, max_length=20)
    secretary_mode_active: Optional[bool] = None
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
