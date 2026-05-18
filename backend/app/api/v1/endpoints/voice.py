"""Téléphonie — endpoints webhook Twilio + admin minimal.

Phase 1 :

    POST /api/v1/voice/twilio/voice    — décrocher un appel entrant
    POST /api/v1/voice/twilio/status   — callback de fin d'appel
    GET  /api/v1/voice/phone-numbers   — liste (admin)
    GET  /api/v1/voice/calls           — journal récent (admin)

Les deux webhooks `twilio/*` sont publics mais vérifient la signature
HMAC X-Twilio-Signature. Les endpoints admin requièrent `CurrentAdmin`.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentAdmin, DBSession
from app.integrations.voice import get_voice_provider
from app.models.voice import (
    Call,
    CallDirection,
    CallStatus,
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


async def _validate_twilio_signature(request: Request) -> dict[str, str]:
    """Lit le body form-encoded, vérifie la signature, retourne les params."""
    try:
        provider = get_voice_provider()
    except RuntimeError:
        # Credentials non configurés — on refuse plutôt que d'accepter
        # n'importe quoi en signalant proprement.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice provider not configured",
        )

    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    sig = request.headers.get("x-twilio-signature", "")
    url = _full_request_url(request)
    if not provider.validate_webhook_signature(url, params, sig):
        # On log l'URL pour pouvoir diagnostiquer un mismatch de domaine
        # (ex. webhook configuré sur immohorizon.com vs reçu sur
        # h2-0.onrender.com), sans logger la signature ni les params.
        log.warning("Twilio signature mismatch on url=%s", url)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Twilio signature",
        )
    return params


# ---------------------------------------------------------------------
# Webhook : appel entrant
# ---------------------------------------------------------------------


@router.post(
    "/twilio/voice",
    summary="Webhook Twilio : appel entrant — répond en TwiML",
    response_class=Response,
)
async def twilio_incoming_call(request: Request, db: DBSession) -> Response:
    """Décroche un appel entrant et le transfère.

    Phase 1 : dispatch simple. On cherche le `PhoneNumber` correspondant
    au `To` reçu, on log l'appel dans `voice_calls`, puis on renvoie un
    TwiML `<Dial>` vers `forward_to_e164` (table) ou `TWILIO_FORWARD_TO`
    (env) en fallback.

    Si aucun forward n'est configuré, on renvoie un message d'attente
    poli et on raccroche — comme ça on ne perd pas l'appel en silence.
    """
    params = await _validate_twilio_signature(request)
    provider = get_voice_provider()

    call_sid = params.get("CallSid", "")
    from_e164 = params.get("From", "")
    to_e164 = params.get("To", "")

    if not (call_sid and from_e164 and to_e164):
        raise HTTPException(status_code=400, detail="Missing CallSid / From / To")

    # Trouve le PhoneNumber qu'on possède.
    pn = (
        await db.execute(
            select(PhoneNumber).where(PhoneNumber.e164 == to_e164, PhoneNumber.active.is_(True))
        )
    ).scalar_one_or_none()

    if pn is None:
        log.warning("Incoming call to unknown number %s (CallSid=%s)", to_e164, call_sid)
        # On répond quand même un TwiML valide pour ne pas laisser
        # Twilio sur une erreur HTTP (ce qui rejouerait le webhook).
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response><Say language=\"fr-CA\">"
            "Ce numéro n'est pas configuré. Au revoir."
            "</Say><Hangup/></Response>"
        )
        return Response(content=twiml, media_type="application/xml")

    forward_to = pn.forward_to_e164 or os.getenv("TWILIO_FORWARD_TO") or ""
    forward_to = forward_to.strip()

    # Idempotent : Twilio peut rejouer le webhook. On utilise
    # provider_sid comme clé naturelle.
    existing = (
        await db.execute(select(Call).where(Call.provider_sid == call_sid))
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            Call(
                phone_number_id=pn.id,
                provider_sid=call_sid,
                direction=CallDirection.INBOUND.value,
                status=CallStatus.RINGING.value,
                from_e164=from_e164,
                to_e164=to_e164,
                forwarded_to_e164=forward_to or None,
            )
        )
        await db.flush()

    if not forward_to:
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response><Say language=\"fr-CA\">"
            "Bonjour, nous vous rappellerons sous peu. Merci."
            "</Say><Hangup/></Response>"
        )
        return Response(content=twiml, media_type="application/xml")

    twiml = provider.build_forward_response(forward_to_e164=forward_to)
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
        # Race condition possible : statut reçu avant qu'on ait flushé
        # l'insert de l'appel entrant. On accepte sans erreur — Twilio
        # ne rejouera pas un 2xx.
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if call_status:
        call.status = call_status
    duration_raw = params.get("CallDuration") or params.get("Duration")
    if duration_raw and duration_raw.isdigit():
        call.duration_sec = int(duration_raw)
    if call_status in ("completed", "busy", "no-answer", "failed", "canceled"):
        call.ended_at = datetime.now(timezone.utc)
        if call_status == "completed" and call.answered_at is None and call.duration_sec:
            # Estimation : si on a une durée et que le call a abouti,
            # answered_at ≈ ended_at - duration. Suffisant pour la
            # Phase 1 ; un callback dédié `answer` viendra plus tard.
            from datetime import timedelta

            call.answered_at = call.ended_at - timedelta(seconds=call.duration_sec)

    rec_url = params.get("RecordingUrl")
    if rec_url:
        call.recording_url = rec_url
        call.recording_sid = params.get("RecordingSid")

    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# Admin (lecture seule, Phase 1)
# ---------------------------------------------------------------------


class PhoneNumberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    e164: str
    provider: str
    label: Optional[str]
    forward_to_e164: Optional[str]
    owner_user_id: Optional[int]
    active: bool


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
