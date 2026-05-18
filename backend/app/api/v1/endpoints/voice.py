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

    # ----- Secrétaire IA (Phase 2) -----
    if pn.secretary_mode_active:
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

    # ----- Phase 1 : transfert direct -----
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
    summary="Journal d'appels récent (admin)",
)
async def list_calls(
    _: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> List[CallRead]:
    rows = (
        await db.execute(
            select(Call).order_by(Call.started_at.desc()).limit(limit)
        )
    ).scalars().all()
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
